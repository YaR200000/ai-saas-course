"""Real DELETE only in conftest's explicitly opted-in disposable expense_test schema.

No migration scripts are executed. The db fixture creates the model schema.
"""
import asyncio
from datetime import date
from decimal import Decimal

import httpx
import pytest
from sqlalchemy import event, func, select

from app.api import app
from app.models import Category, Transaction, User
from app.transactions import delete_transaction

pytestmark = pytest.mark.asyncio
AUTH = {"Authorization": "Bearer synthetic-admin"}


async def seed(db, monkeypatch):
    async with db() as session:
        async with session.begin():
            session.add_all([User(id=1, telegram_id=101), User(id=2, telegram_id=202)])
            session.add(Category(id=1, name="Інше"))
            await session.flush()
            session.add_all([
                Transaction(id=1, user_id=1, category_id=1, type="income", amount=Decimal("300.10"), description="income", date=date(2026, 1, 1)),
                Transaction(id=2, user_id=1, category_id=1, type="expense", amount=Decimal("120.00"), description="expense", date=date(2026, 1, 1)),
                Transaction(id=3, user_id=2, category_id=1, type="expense", amount=Decimal("75.00"), description="other", date=date(2026, 1, 1)),
            ])
    monkeypatch.setattr(app.state, "session_factory", db, raising=False)
    monkeypatch.setattr(app.state, "allowed_user_id", 1, raising=False)
    monkeypatch.setattr(app.state, "admin_password", b"synthetic-admin", raising=False)


def http_client(peer="127.0.0.1"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=(peer, 12345)),
                             base_url="http://127.0.0.1:8000")


@pytest.mark.parametrize("target,expected", [
    (1, {"total_income": "0.00", "total_expense": "120.00", "balance": "-120.00"}),
    (2, {"total_income": "300.10", "total_expense": "0.00", "balance": "300.10"}),
])
async def test_delete_204_repeat_summary_preserves_related(db, monkeypatch, target, expected):
    await seed(db, monkeypatch)
    async with http_client() as client:
        response = await client.delete(f"/api/transactions/{target}", headers=AUTH)
        assert response.status_code == 204 and response.content == b""
        assert (await client.delete(f"/api/transactions/{target}", headers=AUTH)).status_code == 404
        assert (await client.get("/api/summary")).json() == expected
        assert len((await client.get("/api/transactions")).json()) == 1
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(User)) == 2
        assert await session.scalar(select(func.count()).select_from(Category)) == 1
        assert await session.scalar(select(func.count()).select_from(Transaction)) == 2
        assert await session.get(Transaction, 3) is not None


async def test_foreign_missing_and_owner_forgery(db, monkeypatch):
    await seed(db, monkeypatch)
    async with http_client() as client:
        foreign = await client.delete("/api/transactions/3?user_id=2", headers={**AUTH, "X-User-Id": "2"})
        absent = await client.delete("/api/transactions/999", headers=AUTH)
        assert foreign.status_code == absent.status_code == 404
        assert foreign.json() == absent.json()
    async with db() as session:
        assert await session.scalar(select(func.count()).select_from(Transaction)) == 3


@pytest.mark.parametrize("headers,status", [({}, 401), ({"Authorization": "Bearer wrong"}, 401),
    ({**AUTH, "Origin": "https://attacker.example"}, 403), ({**AUTH, "Host": "attacker.example"}, 403)])
async def test_denied_requests_preserve_record(db, monkeypatch, headers, status):
    await seed(db, monkeypatch)
    async with http_client() as client:
        assert (await client.delete("/api/transactions/1", headers=headers)).status_code == status
    async with db() as session:
        assert await session.get(Transaction, 1) is not None


async def test_nonloopback_preserves_record(db, monkeypatch):
    await seed(db, monkeypatch)
    async with http_client("192.0.2.1") as client:
        assert (await client.delete("/api/transactions/1", headers=AUTH)).status_code == 403
    async with db() as session:
        assert await session.get(Transaction, 1) is not None


async def test_concurrent_delete_one_success_one_missing(db, monkeypatch):
    await seed(db, monkeypatch)
    async with http_client() as client:
        responses = await asyncio.gather(*(client.delete("/api/transactions/1", headers=AUTH) for _ in range(2)))
    assert sorted(r.status_code for r in responses) == [204, 404]


@pytest.mark.parametrize("stage", ["execute", "commit"])
async def test_real_transaction_rolls_back_on_injected_failure(db, local_engine, monkeypatch, stage):
    await seed(db, monkeypatch)

    def fail_after_execute(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("DELETE"):
            raise RuntimeError("synthetic execute failure")

    def fail_before_commit(connection):
        raise RuntimeError("synthetic pre-commit failure")

    name, listener = ("after_cursor_execute", fail_after_execute) if stage == "execute" else ("commit", fail_before_commit)
    event.listen(local_engine.sync_engine, name, listener)
    try:
        with pytest.raises(RuntimeError):
            await delete_transaction(db, 1, 1)
    finally:
        event.remove(local_engine.sync_engine, name, listener)
    async with db() as session:
        assert await session.get(Transaction, 1) is not None
