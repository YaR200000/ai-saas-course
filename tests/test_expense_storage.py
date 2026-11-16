import asyncio
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from app.expenses import save_expense
from app.models import Category, Transaction, User
from app.main import expense_handler, start_handler, help_handler

pytestmark = pytest.mark.asyncio


async def save(db, message_id=1, **overrides):
    values = dict(telegram_id=101, chat_id=101, message_id=message_id,
                  amount=Decimal("125.50"), description="тестовий опис")
    values.update(overrides)
    return await save_expense(db, **values)


async def counts(db):
    async with db() as session:
        return [await session.scalar(select(func.count()).select_from(model))
                for model in (User, Category, Transaction)]


async def blocked_writes(engine, table, operations):
    """Release writes only after PostgreSQL confirms every worker is waiting.

    A real table lock replaces timing assumptions. All workers use independent
    sessions; the lock observer checks only this fixture's schema/table.
    """
    assert table in {"users", "categories"}
    tasks = []
    try:
        async with asyncio.timeout(15):
            async with engine.connect() as blocker, engine.connect() as observer:
                async with blocker.begin():
                    await blocker.execute(text(f"LOCK TABLE {table} IN SHARE MODE"))
                    tasks = [asyncio.create_task(operation()) for operation in operations]
                    while True:
                        waiting = await observer.scalar(text(
                            "SELECT count(DISTINCT pid) FROM pg_locks "
                            "WHERE relation = to_regclass(:table) "
                            "AND database = (SELECT oid FROM pg_database "
                            "WHERE datname = current_database()) "
                            "AND NOT granted AND mode = 'RowExclusiveLock'"
                        ), {"table": table})
                        if waiting == len(tasks):
                            break
                        # Surface worker failures instead of hiding them in a timeout.
                        for task in tasks:
                            if task.done():
                                task.result()
                                raise AssertionError("Worker finished before reaching lock")
                        await asyncio.sleep(0.01)
                # Commit releases the blocker only after every worker reached it.
                return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


async def test_persistence_and_existing_user(db):
    assert await save(db)
    assert await save(db, 2)
    assert await counts(db) == [1, 1, 2]
    async with db() as session:
        row = await session.scalar(select(Transaction).where(Transaction.telegram_message_id == 1))
        assert row.amount == Decimal("125.50")
        assert row.description == "тестовий опис"
        assert row.telegram_chat_id == 101
        assert row.created_at is not None
        assert await session.scalar(select(User.telegram_id).where(User.id == row.user_id)) == 101
        assert await session.scalar(select(Category.name).where(Category.id == row.category_id)) == "Інше"


async def test_full_rollback(db):
    # Force a database constraint violation after user/category inserts.
    with pytest.raises(IntegrityError):
        await save(db, amount=Decimal("-1"))
    assert await counts(db) == [0, 0, 0]


async def test_duplicate_message(db):
    assert await save(db)
    assert not await save(db)
    assert await counts(db) == [1, 1, 1]


async def test_concurrent_duplicate(db, local_engine):
    results = await blocked_writes(local_engine, "users", [lambda: save(db)] * 4)
    assert results.count(True) == 1
    assert await counts(db) == [1, 1, 1]


async def test_concurrent_distinct_messages(db, local_engine):
    operations = [lambda i=i: save(db, i) for i in range(1, 5)]
    assert all(await blocked_writes(local_engine, "users", operations))
    assert await counts(db) == [1, 1, 4]


async def test_concurrent_users_share_category(db, local_engine):
    operations = [lambda i=i: save(db, telegram_id=i, chat_id=i) for i in range(201, 205)]
    assert all(await blocked_writes(local_engine, "categories", operations))
    assert await counts(db) == [4, 1, 4]


async def test_commit_failure_cannot_return_success():
    # No database: model an error specifically at transaction context exit.
    session = AsyncMock()
    session.scalar.side_effect = [1, 1, 1]
    transaction = AsyncMock()
    transaction.__aexit__.side_effect = RuntimeError("simulated commit failure")
    session.begin = MagicMock(return_value=transaction)
    context = AsyncMock()
    context.__aenter__.return_value = session
    factory = MagicMock(return_value=context)
    with pytest.raises(RuntimeError, match="simulated commit failure"):
        await save(factory)


async def test_failed_expense_preserves_existing_records(db):
    assert await save(db)
    with pytest.raises(IntegrityError):
        await save(db, 2, amount=Decimal("-1"))
    assert await counts(db) == [1, 1, 1]


async def test_explicit_read_committed(db):
    async with db() as session:
        assert await session.scalar(text("SHOW transaction_isolation")) == "read committed"


async def test_expense_command_commits_before_confirmation(db):
    # Real handler and PostgreSQL storage; only Telegram delivery is replaced.
    msg = SimpleNamespace(
        chat=SimpleNamespace(type="private", id=101),
        from_user=SimpleNamespace(id=101),
        message_id=120,
    )

    async def confirm(response):
        # An independent session must see the committed expense at reply time.
        async with db() as session:
            row = await session.scalar(select(Transaction))
            assert row.amount == Decimal("120.00")
            assert row.description == "кава"
            assert row.telegram_chat_id == 101
            assert row.telegram_message_id == 120
        assert "120.00 UAH" in response
        assert "збережено" in response

    msg.answer = AsyncMock(side_effect=confirm)
    await expense_handler(msg, SimpleNamespace(args="120 кава"), db)
    msg.answer.assert_awaited_once()
    assert await counts(db) == [1, 1, 1]


async def test_start_and_help_with_local_database(db):
    msg = SimpleNamespace(answer=AsyncMock())
    await start_handler(msg, db)
    assert "Привіт!" in msg.answer.call_args.args[0]
    assert "недоступна" not in msg.answer.call_args.args[0]
    msg.answer.reset_mock()
    await help_handler(msg)
    for command in ("/start", "/help", "/expense"):
        assert command in msg.answer.call_args.args[0]
