"""Local single-owner HTTP API. Run separately from the bot."""

from contextlib import asynccontextmanager
from decimal import Decimal, localcontext
from ipaddress import ip_address
import logging
import os

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select

from app.database import create_database_engine, create_session_factory
from app.models import Category, Transaction
from app.schemas import SummaryResponse, TransactionCreate, TransactionResponse
from app.schema_readiness import check_schema_ready
from app.security import require_admin
from app.transactions import create_transaction

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Never load .env on import, start polling, create tables or run migrations.
    raw = os.getenv("API_ALLOWED_USER_ID", "").strip()
    if not raw.isascii() or not raw.isdecimal() or not 0 < int(raw) <= 2**63 - 1:
        raise RuntimeError("API_ALLOWED_USER_ID must be a positive internal users.id.")
    application.state.allowed_user_id = int(raw)
    password = os.getenv("ADMIN_PASSWORD", "")
    application.state.admin_password = password.encode("utf-8") if password.strip() else None
    try:
        engine = create_database_engine()
    except Exception:
        raise RuntimeError("API database configuration is invalid.") from None
    try:
        await check_schema_ready(engine)
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


@app.exception_handler(RequestValidationError)
async def safe_validation_error(request, error):
    return JSONResponse({"detail": "Invalid request."}, status_code=422)


async def transaction_payload(request: Request, admin=Depends(require_admin)):
    # Parse only AFTER authentication, including malformed JSON requests.
    try:
        payload = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(422, "Invalid JSON request.") from None
    try:
        return TransactionCreate.model_validate(payload)
    except ValidationError as error:
        fields = {"type", "amount", "category", "description", "date"}
        details = [{"field": str(e["loc"][0]) if e["loc"] and e["loc"][0] in fields else "request",
                    "message": "Invalid or missing value."} for e in error.errors()]
        raise HTTPException(422, details) from None


@app.post("/api/transactions", response_model=TransactionResponse, status_code=201)
async def post_transaction(request: Request, data: TransactionCreate = Depends(transaction_payload)):
    try:
        return await create_transaction(request.app.state.session_factory,
                                        request.app.state.allowed_user_id, data)
    except Exception:
        logger.error("transaction_create_failed")
        return JSONResponse({"detail": "Creation could not be confirmed; refresh before retrying."}, status_code=503)


@app.get("/api/transactions", response_model=list[TransactionResponse])
async def transactions(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=2**63 - 1),
):
    # Identity comes exclusively from server configuration, never query parameters.
    statement = (
        select(Transaction.id, Transaction.created_at, Transaction.type, Transaction.date, Transaction.amount,
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
            type=row["type"], date=row["date"],
            amount=format(row["amount"], ".2f"), category=row["category"],
            description=row["description"],
        ) for row in rows]
    except Exception:
        logger.error("transactions_read_failed")
        return JSONResponse({"detail": "Service unavailable."}, status_code=503)


@app.get("/api/summary", response_model=SummaryResponse)
async def summary(request: Request):
    # One snapshot, exact NUMERIC aggregates, independent of pagination.
    statement = select(
        func.sum(Transaction.amount).filter(Transaction.type == "income"),
        func.sum(Transaction.amount).filter(Transaction.type == "expense"),
    ).where(
        Transaction.user_id == request.app.state.allowed_user_id
    )
    try:
        async with request.app.state.session_factory() as session:
            income, expense = (await session.execute(statement)).one()
        total_expense = expense if expense is not None else Decimal("0.00")
        total_income = income if income is not None else Decimal("0.00")
        # SUM(NUMERIC) can outgrow a single row's precision and Decimal's default
        # context; keep subtraction exact even for very large aggregate totals.
        with localcontext() as context:
            context.prec = max(len(format(total_income, "f")), len(format(total_expense, "f")), 28) + 2
            balance = total_income - total_expense
        return SummaryResponse(
            total_income=format(total_income, ".2f"),
            total_expense=format(total_expense, ".2f"),
            balance=format(balance, ".2f"),
        )
    except Exception:
        logger.error("summary_read_failed")
        return JSONResponse({"detail": "Service unavailable."}, status_code=503)
