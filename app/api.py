"""Local, single-user, read-only HTTP API. Run separately from the bot."""

from contextlib import asynccontextmanager
from datetime import datetime
from ipaddress import ip_address
import logging
import os
from typing import Literal

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select

from app.database import create_database_engine, create_session_factory
from app.models import Category, Transaction

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Never load .env on import, start polling, create tables or run migrations.
    raw = os.getenv("API_ALLOWED_USER_ID", "").strip()
    if not raw.isascii() or not raw.isdecimal() or not 0 < int(raw) <= 2**63 - 1:
        raise RuntimeError("API_ALLOWED_USER_ID must be a positive internal users.id.")
    application.state.allowed_user_id = int(raw)
    try:
        engine = create_database_engine()
    except Exception:
        raise RuntimeError("API database configuration is invalid.") from None
    try:
        application.state.session_factory = create_session_factory(engine)
        yield
    finally:
        await engine.dispose()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def is_local_request(request: Request) -> bool:
    try:
        if request.client is None or not ip_address(request.client.host).is_loopback:
            return False
    except ValueError:
        return False
    # Host validation prevents DNS rebinding. Do not trust forwarded headers.
    host = request.headers.get("host", "").lower()
    hostname, separator, port = host.partition(":")
    if hostname not in {"localhost", "127.0.0.1"}:
        return False
    if separator and (not port.isdecimal() or not 0 < int(port) <= 65535):
        return False
    # Reject foreign browser origins, including sandboxed/null origins.
    origin = request.headers.get("origin")
    if origin is not None and origin != f"http://{host}":
        return False
    return request.headers.get("sec-fetch-site") not in {"cross-site", "same-site"}


@app.middleware("http")
async def local_access(request: Request, call_next):
    if not is_local_request(request):
        response = JSONResponse({"detail": "Local access only."}, status_code=403)
    else:
        try:
            response = await call_next(request)
        except Exception:
            logger.error("transactions_api_failed")
            response = JSONResponse({"detail": "Service unavailable."}, status_code=503)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


class TransactionResponse(BaseModel):
    id: str
    created_at: datetime
    type: Literal["expense"] = "expense"
    amount: str
    category: str
    description: str
    currency: Literal["UAH"] = "UAH"


@app.get("/api/transactions", response_model=list[TransactionResponse])
async def transactions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=2**63 - 1),
):
    # Identity comes exclusively from server configuration, never query parameters.
    statement = (
        select(Transaction.id, Transaction.created_at, Transaction.amount,
               Category.name.label("category"), Transaction.description)
        .join(Category, Transaction.category_id == Category.id)
        .where(Transaction.user_id == request.app.state.allowed_user_id)
        .order_by(Transaction.created_at.desc(), Transaction.id.desc())
        .limit(limit).offset(offset)
    )
    try:
        async with request.app.state.session_factory() as session:
            rows = (await session.execute(statement)).mappings().all()
        return [TransactionResponse(
            id=str(row["id"]), created_at=row["created_at"],
            amount=format(row["amount"], ".2f"), category=row["category"],
            description=row["description"],
        ) for row in rows]
    except Exception:
        logger.error("transactions_read_failed")
        return JSONResponse({"detail": "Service unavailable."}, status_code=503)
