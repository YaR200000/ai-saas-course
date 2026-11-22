"""Actual PostgreSQL migration tests; only the guarded local_engine fixture is used."""
from datetime import date
from decimal import Decimal

import pytest
from asyncpg import PostgresError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.expenses import save_expense
from test_migration import LEGACY_SQL, MIGRATION, columns, execute_script, legacy_snapshot

pytestmark = pytest.mark.asyncio
SQL = (MIGRATION.parent / "002_transaction_type_date.sql").read_text(encoding="utf-8")
OLD_FIELDS = "id, user_id, category_id, amount, description, created_at, telegram_chat_id, telegram_message_id"


async def prepare(engine):
    await execute_script(engine, LEGACY_SQL)
    await execute_script(engine, MIGRATION.read_text(encoding="utf-8"))
    async with engine.begin() as conn:
        await conn.execute(text("""
            UPDATE transactions SET amount = 120.00,
                created_at = '2026-01-01 22:30:00+00',
                telegram_chat_id = 101, telegram_message_id = 10 WHERE id = 1
        """))
        await conn.execute(text("""
            INSERT INTO transactions(user_id, category_id, amount, description, created_at)
            VALUES (1, 1, 75.00, 'друга стара витрата', '2026-07-01 21:30:00+00')
        """))
    return await legacy_snapshot(engine)


async def test_preserves_two_expenses_and_kyiv_dates(local_engine):
    before = await prepare(local_engine)
    await execute_script(local_engine, SQL)
    async with local_engine.connect() as conn:
        rows = (await conn.execute(text(f"SELECT {OLD_FIELDS} FROM transactions ORDER BY id"))).tuples().all()
        assert rows == before[2]
        assert [r[3] for r in rows] == [Decimal("120.00"), Decimal("75.00")]
        assert (await conn.execute(text("SELECT type, date FROM transactions ORDER BY id"))).tuples().all() == [
            ("expense", date(2026, 1, 2)), ("expense", date(2026, 7, 2))]
        for table, expected in zip(("users", "categories"), before[:2]):
            assert (await conn.execute(text(f"SELECT * FROM {table} ORDER BY id"))).tuples().all() == expected


async def test_legacy_insert_defaults_and_bot(local_engine):
    await prepare(local_engine)
    await execute_script(local_engine, SQL)
    async with local_engine.begin() as conn:
        # A non-Kyiv session timezone must not affect the calendar-date default.
        await conn.execute(text("SET LOCAL TIME ZONE 'Pacific/Honolulu'"))
        row = (await conn.execute(text("""
            INSERT INTO transactions(user_id, category_id, amount, description)
            VALUES (1, 1, 1.00, 'старий виклик')
            RETURNING type, date, date(timezone('Europe/Kyiv', CURRENT_TIMESTAMP))
        """))).one()
        assert row[0] == "expense"
        assert row[1] == row[2]
    factory = async_sessionmaker(local_engine, expire_on_commit=False)
    values = dict(telegram_id=101, chat_id=101, message_id=99,
                  amount=Decimal("2.50"), description="бот")
    assert await save_expense(factory, **values)
    assert not await save_expense(factory, **values)
    async with local_engine.connect() as conn:
        row = (await conn.execute(text("""
            SELECT type, date, date(timezone('Europe/Kyiv', created_at))
            FROM transactions WHERE telegram_message_id = 99
        """))).one()
        assert row[0] == "expense" and row[1] == row[2]


@pytest.mark.parametrize("value,sqlstate", [
    ("'income'", None), ("'expense'", None), ("'other'", "23514"),
    ("NULL", "23502"),
])
async def test_type_constraint(local_engine, value, sqlstate):
    await prepare(local_engine)
    await execute_script(local_engine, SQL)
    statement = f"INSERT INTO transactions(user_id, category_id, amount, description, type) VALUES (1, 1, 1, 'test', {value})"
    if sqlstate is None:
        await execute_script(local_engine, statement)
    else:
        with pytest.raises(PostgresError) as caught:
            await execute_script(local_engine, statement)
        assert caught.value.sqlstate == sqlstate


async def test_date_not_null(local_engine):
    await prepare(local_engine)
    await execute_script(local_engine, SQL)
    with pytest.raises(PostgresError) as caught:
        await execute_script(local_engine, "INSERT INTO transactions(user_id, category_id, amount, description, date) VALUES (1, 1, 1, 'test', NULL)")
    assert caught.value.sqlstate == "23502"


async def test_late_failure_rolls_back_backfill_and_schema(local_engine):
    before = await prepare(local_engine)
    # Existing conflicting constraint fails after the UPDATE, before COMMIT.
    await execute_script(local_engine, "ALTER TABLE transactions ADD CONSTRAINT injected_failure CHECK (amount > 0)")
    failing = SQL.replace("COMMIT;", "ALTER TABLE transactions ADD CONSTRAINT injected_failure CHECK (amount > 0);\nCOMMIT;")
    with pytest.raises(PostgresError):
        await execute_script(local_engine, failing)
    assert await legacy_snapshot(local_engine) == before
    assert not {"type", "date"} & await columns(local_engine)


async def test_repeated_migration_fails_without_data_changes(local_engine):
    await prepare(local_engine)
    await execute_script(local_engine, SQL)
    before = await legacy_snapshot(local_engine)
    with pytest.raises(PostgresError) as caught:
        await execute_script(local_engine, SQL)
    assert caught.value.sqlstate == "42701"
    assert await legacy_snapshot(local_engine) == before
