import ssl
import os
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker


def get_database_url():
    """Read and adapt the Neon connection URL for asyncpg."""
    raw_url = os.getenv("DATABASE_URL", "").strip()

    if not raw_url:
        raise RuntimeError("DATABASE_URL is missing or empty.")

    url = make_url(raw_url)

    if url.drivername not in ("postgresql", "postgresql+asyncpg"):
        raise RuntimeError("Unsupported database URL driver.")

    # Neon uses sslmode=require; asyncpg expects ssl=require.
    query = dict(url.query)
    sslmode = query.pop("sslmode", None)
    query.pop("channel_binding", None)

    if sslmode is not None:
        if sslmode != "require":
            raise RuntimeError("Expected sslmode=require.")
        query["ssl"] = "verify-full"

    return url.set(
        drivername="postgresql+asyncpg",
        query=query,
    )



async def check_database_connection():
    """Verify the database connection with TLS certificate validation."""
    url = get_database_url()

    # Remove the SSL mode from the URL.
    # TLS will be configured through an SSLContext instead.
    query = dict(url.query)
    query.pop("ssl", None)
    url = url.set(query=query)

    # Verify the server certificate and hostname.
    ssl_context = ssl.create_default_context()

    engine = create_async_engine(
        url,
        echo=False,
        hide_parameters=True,
        isolation_level="READ COMMITTED",
        connect_args={"ssl": ssl_context},
    )

    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("SELECT 1"))
            return result.scalar_one() == 1
    finally:
        await engine.dispose()

def create_database_engine():
    """Create an async SQLAlchemy engine with verified TLS."""
    url = get_database_url()

    query = dict(url.query)
    query.pop("ssl", None)
    url = url.set(query=query)

    ssl_context = ssl.create_default_context()

    return create_async_engine(
        url,
        echo=False,
        hide_parameters=True,
        isolation_level="READ COMMITTED",
        connect_args={"ssl": ssl_context},
        pool_pre_ping=True,
    )

def create_session_factory(engine):
    """Create a factory for asynchronous database sessions."""
    return async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        autoflush=False,
    )
