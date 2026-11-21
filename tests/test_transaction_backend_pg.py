"""Real writes are restricted by conftest's disposable local expense_test guard."""
import asyncio

import httpx
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.api import app
from app.models import Category, Transaction, User
from app.schema_readiness import check_schema_ready
from app.schemas import TransactionCreate
from app.transactions import OwnerUnavailable, create_transaction
from test_migration import LEGACY_SQL, MIGRATION, execute_script
from test_transaction_post import PAYLOAD

pytestmark = pytest.mark.asyncio


async def owners(db):
    async with db() as session:
        async with session.begin():
            session.add_all([User(id=1, telegram_id=101), User(id=2, telegram_id=202)])


async def test_post_read_summary_and_isolation(db, local_engine, monkeypatch):
    await owners(db)
    await check_schema_ready(local_engine)
    monkeypatch.setattr(app.state, "session_factory", db, raising=False)
    monkeypatch.setattr(app.state, "allowed_user_id", 1, raising=False)
    monkeypatch.setattr(app.state, "admin_password", b"synthetic-admin", raising=False)
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as client:
        for kind, amount in [("expense", "120"), ("expense", "75"), ("income", "300"), ("income", "0.10"), ("income", "0.20")]:
            response = await client.post("/api/transactions?user_id=2", json={**PAYLOAD, "type": kind, "amount": amount},
                                         headers={"Authorization": "Bearer synthetic-admin", "X-User-Id": "2"})
            assert response.status_code == 201
            assert response.json()["type"] == kind
            assert response.json()["date"] == "2026-11-21"
        await create_transaction(db, 2, TransactionCreate.model_validate({**PAYLOAD, "amount": "999"}))
        assert (await client.get("/api/summary")).json() == {
            "total_income": "300.30", "total_expense": "195.00", "balance": "105.30"}
        rows = (await client.get("/api/transactions")).json()
        assert len(rows) == 5 and {r["type"] for r in rows} == {"income", "expense"}
        async with db() as session:
            assert await session.scalar(select(func.count()).select_from(Category)) == 1
            assert await session.scalar(select(func.count()).select_from(Transaction).where(
                Transaction.telegram_chat_id.is_not(None))) == 0


async def test_concurrent_category_reuse(db):
    await owners(db)
    data = TransactionCreate.model_validate(PAYLOAD)
    results = await asyncio.gather(*(create_transaction(db, 1, data) for _ in range(4)))
    assert len({row.id for row in results}) == 4
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Category)) == 1


async def test_missing_owner_and_rollback(db, local_engine):
    data = TransactionCreate.model_validate(PAYLOAD)
    with pytest.raises(OwnerUnavailable):
        await create_transaction(db, 99, data)
    await owners(db)
    async with local_engine.begin() as conn:
        await conn.execute(text("ALTER TABLE transactions ADD CONSTRAINT synthetic_failure CHECK (amount < 1)"))
    with pytest.raises(IntegrityError):
        await create_transaction(db, 1, data)
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Category)) == 0
        assert await session.scalar(select(func.count()).select_from(Transaction)) == 0


async def test_old_then_migrated_schema(local_engine):
    await execute_script(local_engine, LEGACY_SQL)
    await execute_script(local_engine, MIGRATION.read_text(encoding="utf-8"))
    with pytest.raises(RuntimeError, match="migration 002"):
        await check_schema_ready(local_engine)
    await execute_script(local_engine, (MIGRATION.parent / "002_transaction_type_date.sql").read_text(encoding="utf-8"))
    await check_schema_ready(local_engine)


@pytest.mark.parametrize("change", [
    "ALTER TABLE transactions ALTER COLUMN type DROP NOT NULL",
    "ALTER TABLE transactions ALTER COLUMN date DROP DEFAULT",
    "ALTER TABLE transactions DROP CONSTRAINT ck_transactions_type",
    "ALTER TABLE categories DROP CONSTRAINT uq_categories_name",
    "ALTER TABLE transactions DROP CONSTRAINT ck_transactions_type; ALTER TABLE transactions ADD CONSTRAINT ck_transactions_type CHECK (type IN ('income', 'expense')) NOT VALID",
    "ALTER TABLE transactions DROP CONSTRAINT ck_transactions_type; ALTER TABLE transactions ADD CONSTRAINT ck_transactions_type CHECK (type IN ('income', 'expense') OR true)",
])
async def test_incompatible_schema_rejected(db, local_engine, change):
    async with local_engine.begin() as conn:
        # Execute individually; asyncpg prepared execution accepts one statement.
        for statement in change.split(";"):
            await conn.execute(text(statement))
    with pytest.raises(RuntimeError, match="migration 002"):
        await check_schema_ready(local_engine)
