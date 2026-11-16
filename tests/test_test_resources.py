"""Unit checks for test infrastructure; no PostgreSQL connection is opened."""
from unittest.mock import AsyncMock, MagicMock

import pytest

from conftest import cleanup_engine


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
