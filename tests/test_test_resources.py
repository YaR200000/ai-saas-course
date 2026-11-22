"""Unit checks for test infrastructure; no PostgreSQL connection is opened."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from conftest import cleanup_engine
from test_migration import execute_script


@pytest.mark.asyncio
async def test_engine_disposed_even_if_schema_cleanup_fails():
    connection = AsyncMock()
    connection.execute.side_effect = RuntimeError("simulated cleanup failure")
    context = AsyncMock()
    context.__aenter__.return_value = connection
    engine = MagicMock()
    engine.begin.return_value = context
    engine.dispose = AsyncMock()
    with pytest.raises(RuntimeError, match="simulated cleanup failure"):
        await cleanup_engine(engine, "expense_test_synthetic")
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
async def test_engine_disposed_when_schema_was_not_created():
    engine = MagicMock()
    engine.dispose = AsyncMock()
    await cleanup_engine(engine, None)
    engine.begin.assert_not_called()
    engine.dispose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("failed", [False, True])
async def test_raw_script_retires_pool_after_connection_return(failed):
    events = []
    driver = MagicMock()
    driver.is_in_transaction.return_value = failed

    async def execute(script):
        events.append(script)
        if failed and script != "ROLLBACK":
            raise RuntimeError("synthetic script failure")

    driver.execute = AsyncMock(side_effect=execute)
    connection = AsyncMock()
    connection.get_raw_connection.return_value.driver_connection = driver
    context = AsyncMock()
    context.__aenter__.return_value = connection
    context.__aexit__.side_effect = lambda *args: events.append("returned")
    engine = MagicMock()
    engine.connect.return_value = context
    engine.dispose = AsyncMock(side_effect=lambda: events.append("disposed"))

    if failed:
        with pytest.raises(RuntimeError, match="synthetic script failure"):
            await execute_script(engine, "DDL")
    else:
        await execute_script(engine, "DDL")

    assert events == (["DDL", "ROLLBACK", "returned", "disposed"] if failed
                      else ["DDL", "returned", "disposed"])
    engine.dispose.assert_awaited_once()
