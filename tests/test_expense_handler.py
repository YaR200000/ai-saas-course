from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
import sys

import pytest

from app.expenses import parse_expense
from app.main import expense_handler, help_handler, start_handler


@pytest.mark.parametrize("args", [None, "", "   ", "abc кава", "0 кава",
    "-1 кава", "NaN кава", "Infinity кава", "1.001 кава",
    "10000000000 кава", "125", "125   ", "125,50 кава"])
def test_invalid_input(args):
    with pytest.raises(ValueError):
        parse_expense(args)


@pytest.mark.parametrize("args,expected", [
    ("125.50 кава", (Decimal("125.50"), "кава")),
    ("0.01  кава з молоком  ", (Decimal("0.01"), "кава з молоком")),
    ("9999999999.99 опис", (Decimal("9999999999.99"), "опис")),
])
def test_valid_input(args, expected):
    assert parse_expense(args) == expected


def message(chat_type="private"):
    return SimpleNamespace(chat=SimpleNamespace(type=chat_type, id=101),
        from_user=SimpleNamespace(id=101), message_id=11, answer=AsyncMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("chat_type,args", [("group", "125 кава"),
    ("supergroup", "125 кава"), ("private", " "), ("private", "-1 кава")])
async def test_rejected_before_storage(monkeypatch, chat_type, args):
    save = AsyncMock()
    monkeypatch.setattr("app.main.save_expense", save)
    await expense_handler(message(chat_type), SimpleNamespace(args=args), object())
    save.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_user(monkeypatch):
    save = AsyncMock()
    monkeypatch.setattr("app.main.save_expense", save)
    msg = message()
    msg.from_user = None
    await expense_handler(msg, SimpleNamespace(args="125 кава"), object())
    save.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("created,expected", [(True, "125.50 UAH"), (False, "вже оброблено")])
async def test_reply_after_storage(monkeypatch, created, expected):
    msg = message()
    async def save(*args, **kwargs):
        msg.answer.assert_not_awaited()
        return created
    monkeypatch.setattr("app.main.save_expense", save)
    await expense_handler(msg, SimpleNamespace(args="125.50 приватний опис"), object())
    assert expected in msg.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_error_does_not_leak(monkeypatch, caplog):
    secret_marker = "confidential-description-and-id"
    technical_details = (
        secret_marker + " PostgreSQL asyncpg RuntimeError "
        "[SQL: INSERT INTO transactions] "
        "[parameters: telegram_id=101, description=приватний опис]"
    )
    monkeypatch.setattr("app.main.save_expense", AsyncMock(side_effect=RuntimeError(technical_details)))
    msg = message()
    await expense_handler(msg, SimpleNamespace(args="125 приватний опис"), object())
    assert secret_marker not in caplog.text
    assert "приватний опис" not in caplog.text
    msg.answer.assert_awaited_once()
    response = msg.answer.call_args.args[0]
    assert "Не вдалося підтвердити збереження" in response
    uncertainty = "витрату могло бути збережено"
    assert uncertainty in response
    # Only the explicit uncertainty warning may mention a saved expense.
    remaining = response.replace(uncertainty, "").casefold()
    assert "збережено" not in remaining
    assert "успішно" not in remaining
    assert "вже оброблено" not in remaining
    assert "expense_storage_failed" in caplog.text
    for output in (response, caplog.text):
        for private_detail in (
            secret_marker, "приватний опис", "PostgreSQL", "asyncpg",
            "RuntimeError", "INSERT INTO", "parameters", "telegram_id", "101",
        ):
            assert private_detail not in output
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_delivery_failure_does_not_repeat_save(monkeypatch, caplog):
    save = AsyncMock(return_value=True)
    monkeypatch.setattr("app.main.save_expense", save)
    msg = message()
    msg.answer.side_effect = RuntimeError("private delivery details")
    await expense_handler(msg, SimpleNamespace(args="125 кава"), object())
    save.assert_awaited_once()
    assert "private delivery details" not in caplog.text


@pytest.mark.asyncio
async def test_help():
    msg = message()
    await help_handler(msg)
    assert "/expense" in msg.answer.call_args.args[0]
    assert "UAH" in msg.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_start_success(caplog):
    session = AsyncMock()
    session.scalar.return_value = 1
    context = AsyncMock()
    context.__aenter__.return_value = session
    msg = message()
    await start_handler(msg, MagicMock(return_value=context))
    assert str(session.scalar.call_args.args[0]) == "SELECT 1"
    assert "Привіт!" in msg.answer.call_args.args[0]
    assert "недоступна" not in msg.answer.call_args.args[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_stage", ["connect", "query", "result"])
async def test_start_database_failure_is_safe(caplog, failure_stage):
    marker = "synthetic-private-connection-details"
    session = AsyncMock()
    session.scalar.return_value = 1
    context = AsyncMock()
    context.__aenter__.return_value = session
    if failure_stage == "connect":
        context.__aenter__.side_effect = RuntimeError(marker)
    elif failure_stage == "query":
        session.scalar.side_effect = RuntimeError(marker)
    else:
        session.scalar.return_value = 0
    msg = message()
    await start_handler(msg, MagicMock(return_value=context))
    msg.answer.assert_awaited_once()
    assert "тимчасово недоступна" in msg.answer.call_args.args[0]
    assert marker not in msg.answer.call_args.args[0] + caplog.text
    assert "start_database_check_failed" in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_start_database_and_delivery_failure_is_safe(caplog):
    context = AsyncMock()
    context.__aenter__.side_effect = RuntimeError("private database details")
    msg = message()
    active_exceptions = []

    async def fail_delivery(response):
        active_exceptions.append(sys.exception())
        raise RuntimeError("private delivery details")

    msg.answer.side_effect = fail_delivery
    await start_handler(msg, MagicMock(return_value=context))
    assert active_exceptions == [None]
    assert "start_database_check_failed" in caplog.text
    assert "start_response_delivery_failed" in caplog.text
    assert "private" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.asyncio
async def test_storage_and_delivery_fail_without_exception_chain(monkeypatch, caplog):
    save = AsyncMock(side_effect=RuntimeError("private database details 101"))
    monkeypatch.setattr("app.main.save_expense", save)
    msg = message()
    active_exceptions = []

    async def fail_delivery(response):
        # The storage exception must no longer be active at delivery time.
        active_exceptions.append(sys.exception())
        raise RuntimeError("private Telegram details 101")

    msg.answer.side_effect = fail_delivery
    await expense_handler(msg, SimpleNamespace(args="125 приватний опис"), object())
    save.assert_awaited_once()
    msg.answer.assert_awaited_once()
    assert active_exceptions == [None]
    assert "expense_storage_failed" in caplog.text
    assert "expense_confirmation_delivery_failed" in caplog.text
    assert "private" not in caplog.text
    assert "приватний опис" not in caplog.text
    assert "101" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)
