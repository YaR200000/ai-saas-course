"""Integration tests require an explicitly enabled disposable local PostgreSQL."""
import os
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models import Base


@pytest_asyncio.fixture
async def local_engine():
    # Do not fall back to DATABASE_URL; never load .env.
    if os.environ.get("EXPENSE_TEST_DB_DISPOSABLE") != "yes":
        pytest.skip("Disposable local PostgreSQL not explicitly enabled")
    raw = os.environ.get("EXPENSE_TEST_DATABASE_URL")
    if not raw:
        pytest.fail("Explicit test database URL required")
    url = make_url(raw)
    if (url.drivername != "postgresql+asyncpg"
            or url.host not in {"127.0.0.1", "localhost", "::1"}
            or url.database != "expense_test" or url.query):
        pytest.fail("Only local expense_test PostgreSQL without URL options is allowed")
    schema = "expense_test_" + uuid4().hex
    engine = create_async_engine(
        url, echo=False, hide_parameters=True, isolation_level="READ COMMITTED",
        connect_args={"server_settings": {
            "search_path": schema, "statement_timeout": "10000", "lock_timeout": "10000",
        }},
    )
    created = False
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        created = True
        yield engine
    finally:
        await cleanup_engine(engine, schema if created else None)


async def cleanup_engine(engine, schema):
    """Attempt disposal even when schema cleanup raises an exception."""
    try:
        if schema is not None:
            async with engine.begin() as conn:
                await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
    finally:
        await engine.dispose()


@pytest_asyncio.fixture
async def db(local_engine):
    async with local_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return async_sessionmaker(local_engine, expire_on_commit=False)
