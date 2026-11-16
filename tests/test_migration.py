"""Execute the actual migration only in local_engine's disposable schema."""
from pathlib import Path
from decimal import Decimal

import pytest
from asyncpg import PostgresError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.expenses import save_expense

pytestmark = pytest.mark.asyncio
MIGRATION = Path(__file__).resolve().parents[1] / "migrations" / "001_expense_messages.sql"

# Snapshot of the pre-migration structure, intentionally independent of models.
LEGACY_SQL = """
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY, telegram_id BIGINT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL
);
CREATE TABLE categories (id BIGSERIAL PRIMARY KEY, name VARCHAR(100) NOT NULL);
CREATE TABLE transactions (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT NOT NULL REFERENCES users(id),
    category_id BIGINT NOT NULL REFERENCES categories(id),
    amount NUMERIC(12,2) NOT NULL,
    description TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_transactions_amount_positive CHECK (amount > 0)
);
INSERT INTO users (telegram_id, created_at) VALUES (101, now());
INSERT INTO categories (name) VALUES ('Інше');
INSERT INTO transactions (user_id, category_id, amount, description)
    VALUES (1, 1, 12.50, 'навчальний запис');
"""


async def execute_script(engine, script):
    # asyncpg supports the full SQL script, including DO $$ and BEGIN/COMMIT.
    # Do not split by semicolons: that would break the migration's DO block.
    async with engine.connect() as connection:
        raw = await connection.get_raw_connection()
        driver = raw.driver_connection
        try:
            await driver.execute(script)
        finally:
            # Failed explicit transactions remain aborted until rolled back.
            if driver.is_in_transaction():
                await driver.execute("ROLLBACK")


async def legacy_snapshot(engine):
    async with engine.connect() as connection:
        return [list((await connection.execute(text(f"SELECT * FROM {table} ORDER BY id"))).tuples())
                for table in ("users", "categories", "transactions")]


async def columns(engine):
    async with engine.connect() as connection:
        return set((await connection.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = 'transactions'"
        ))).scalars())


async def category_unique_exists(engine):
    async with engine.connect() as connection:
        return await connection.scalar(text(
            "SELECT EXISTS (SELECT 1 FROM pg_constraint "
            "WHERE conrelid = 'categories'::regclass AND conname = 'uq_categories_name')"
        ))


async def test_upgrade_preserves_data_and_supports_new_code(local_engine):
    await execute_script(local_engine, LEGACY_SQL)
    before = await legacy_snapshot(local_engine)
    await execute_script(local_engine, MIGRATION.read_text(encoding="utf-8"))
    async with local_engine.connect() as connection:
        old_rows = list((await connection.execute(text(
            "SELECT id, user_id, category_id, amount, description, created_at "
            "FROM transactions ORDER BY id"
        ))).tuples())
        assert old_rows == before[2]
        assert (await connection.execute(text(
            "SELECT telegram_chat_id, telegram_message_id FROM transactions"
        ))).one() == (None, None)
        for table, expected in zip(("users", "categories"), before[:2]):
            assert list((await connection.execute(text(f"SELECT * FROM {table} ORDER BY id"))).tuples()) == expected
    factory = async_sessionmaker(local_engine, expire_on_commit=False)
    values = dict(telegram_id=101, chat_id=101, message_id=10,
                  amount=Decimal("25.00"), description="нова тестова витрата")
    assert await save_expense(factory, **values)
    assert not await save_expense(factory, **values)
    async with local_engine.connect() as connection:
        assert await connection.scalar(text("SELECT count(*) FROM transactions")) == 2


async def test_duplicate_categories_abort_without_changing_data(local_engine):
    await execute_script(local_engine, LEGACY_SQL + "INSERT INTO categories(name) VALUES ('Інше');")
    before = await legacy_snapshot(local_engine)
    with pytest.raises(PostgresError) as caught:
        await execute_script(local_engine, MIGRATION.read_text(encoding="utf-8"))
    assert caught.value.sqlstate == "P0001"
    assert await legacy_snapshot(local_engine) == before
    assert "telegram_chat_id" not in await columns(local_engine)
    assert not await category_unique_exists(local_engine)


async def test_late_ddl_error_rolls_back_earlier_schema_changes(local_engine):
    await execute_script(local_engine, LEGACY_SQL +
                         "ALTER TABLE transactions ADD COLUMN telegram_chat_id BIGINT;")
    before = await legacy_snapshot(local_engine)
    with pytest.raises(PostgresError) as caught:
        await execute_script(local_engine, MIGRATION.read_text(encoding="utf-8"))
    assert caught.value.sqlstate == "42701"  # duplicate column
    assert await legacy_snapshot(local_engine) == before
    assert not await category_unique_exists(local_engine)
    assert "telegram_message_id" not in await columns(local_engine)


@pytest.mark.parametrize("statement,sqlstate", [
    ("INSERT INTO categories(name) VALUES ('Інше')", "23505"),
    ("INSERT INTO transactions(user_id, category_id, amount, description, telegram_chat_id) "
     "VALUES (1, 1, 1, 'тест', 101)", "23514"),
])
async def test_migrated_constraints_are_enforced(local_engine, statement, sqlstate):
    await execute_script(local_engine, LEGACY_SQL)
    await execute_script(local_engine, MIGRATION.read_text(encoding="utf-8"))
    with pytest.raises(PostgresError) as caught:
        await execute_script(local_engine, statement)
    assert caught.value.sqlstate == sqlstate
