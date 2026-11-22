"""Schema compilation and bot intent checks without connecting to any database."""
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy import Date, Numeric
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.expenses import save_expense
from app.models import Transaction


def test_postgresql_model_contract():
    table = Transaction.__table__
    ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
    assert "type VARCHAR(7) DEFAULT 'expense' NOT NULL" in ddl
    assert "date DATE DEFAULT date(timezone('Europe/Kyiv', CURRENT_TIMESTAMP)) NOT NULL" in ddl
    assert "CHECK (type IN ('income', 'expense'))" in ddl
    assert "CHECK (amount > 0)" in ddl
    assert isinstance(table.c.date.type, Date)
    assert isinstance(table.c.amount.type, Numeric)
    assert (table.c.amount.type.precision, table.c.amount.type.scale) == (12, 2)
    assert table.c.created_at.type.timezone


@pytest.mark.asyncio
async def test_bot_explicit_type_and_kyiv_date_before_commit():
    session = AsyncMock()
    session.scalar.side_effect = [1, 1, 7]
    transaction = AsyncMock()
    session.begin = MagicMock(return_value=transaction)
    context = AsyncMock()
    context.__aenter__.return_value = session
    factory = MagicMock(return_value=context)
    assert await save_expense(factory, telegram_id=101, chat_id=101,
                             message_id=7, amount=Decimal("120.00"), description="тест")
    statement = session.scalar.call_args_list[-1].args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    assert compiled.params["type"] == "expense"
    assert "date(timezone(" in str(compiled)
    assert "Europe/Kyiv" in compiled.params.values()
    transaction.__aexit__.assert_awaited_once()
