"""HTTP tests execute the real SELECT against isolated in-memory SQLite.

No environment files, network, Neon, or existing database are used.
"""
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient
from starlette.requests import Request
import pytest
from sqlalchemy import create_engine, insert
from sqlalchemy.pool import StaticPool

from app.api import app, is_local_request
from app.models import Base, Category, Transaction, User


@pytest.fixture
def client(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool,
                           connect_args={"check_same_thread": False})
    # SQLite contract tests do not verify PostgreSQL timezone semantics.
    # Let the new server default execute; real Kyiv dates are tested in PostgreSQL.
    with engine.connect() as connection:
        connection.connection.driver_connection.create_function(
            "timezone", 2, lambda zone, timestamp: timestamp,
        )
    Base.metadata.create_all(engine)
    now = datetime(2026, 11, 17, 9, tzinfo=timezone.utc)
    with engine.begin() as connection:
        connection.execute(insert(User), [
            {"id": 1, "telegram_id": 101}, {"id": 2, "telegram_id": 202}])
        connection.execute(insert(Category), [{"id": 1, "name": "Інше"}])
        connection.execute(insert(Transaction), [
            dict(id=1, user_id=1, category_id=1, amount=Decimal("0.10"),
                 description="older", created_at=now.replace(day=16)),
            dict(id=2, user_id=1, category_id=1, amount=Decimal("9999999999.99"),
                 description="large", created_at=now),
            dict(id=3, user_id=1, category_id=1, amount=Decimal("125.50"),
                 description="кава", created_at=now),
            dict(id=4, user_id=2, category_id=1, amount=Decimal("9.99"),
                 description="other-user-private", created_at=now),
        ])

    class Session:
        async def __aenter__(self):
            self.connection = engine.connect()
            return self

        async def __aexit__(self, *args):
            self.connection.close()

        async def execute(self, statement):
            return self.connection.execute(statement)

    fake_engine = AsyncMock()
    monkeypatch.setenv("API_ALLOWED_USER_ID", "1")
    monkeypatch.setattr("app.api.create_database_engine", lambda: fake_engine)
    monkeypatch.setattr("app.api.check_schema_ready", AsyncMock())
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr("app.api.create_session_factory", lambda _: Session)
    try:
        with TestClient(app, base_url="http://127.0.0.1:8000",
                        client=("127.0.0.1", 40000)) as http:
            yield http
        fake_engine.dispose.assert_awaited_once()
    finally:
        engine.dispose()


def test_contract_order_money_and_owner(client):
    response = client.get("/api/transactions")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    rows = response.json()
    assert [row["id"] for row in rows] == ["3", "2", "1"]
    assert [row["amount"] for row in rows] == ["125.50", "9999999999.99", "0.10"]
    assert set(rows[0]) == {"id", "created_at", "date", "type", "amount", "category",
                            "description", "currency"}
    assert rows[0]["type"] == "expense"
    assert rows[0]["category"] == "Інше"
    assert rows[0]["description"] == "кава"
    assert rows[0]["currency"] == "UAH"
    assert datetime.fromisoformat(rows[0]["created_at"]).day == 17
    assert "other-user-private" not in response.text


def test_pagination(client):
    assert [r["id"] for r in client.get(
        "/api/transactions?limit=1&offset=1").json()] == ["2"]


def test_empty_page_and_user(client):
    assert client.get("/api/transactions?offset=50").json() == []
    app.state.allowed_user_id = 999
    assert client.get("/api/transactions").json() == []


def test_browser_cannot_choose_owner(client):
    response = client.get("/api/transactions?user_id=2&telegram_id=202")
    assert [row["id"] for row in response.json()] == ["3", "2", "1"]


@pytest.mark.parametrize("query", ["limit=0", "limit=101", "offset=-1",
                                         "offset=9223372036854775808", "limit=abc"])
def test_invalid_pagination(client, query):
    response = client.get("/api/transactions?" + query)
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"


def test_database_failure_is_safe(client, caplog):
    marker = "private-database-password-and-description"

    def fail():
        raise RuntimeError(marker)

    app.state.session_factory = fail
    response = client.get("/api/transactions")
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable."}
    assert response.headers["cache-control"] == "no-store"
    assert marker not in response.text + caplog.text
    assert all(record.exc_info is None for record in caplog.records)


@pytest.mark.parametrize("headers", [
    {"host": "attacker.example"},
    {"origin": "https://attacker.example"},
    {"origin": "null"},
    {"sec-fetch-site": "cross-site"},
    {"sec-fetch-site": "same-site"},
])
def test_browser_access_restrictions(client, headers):
    response = client.get("/api/transactions", headers=headers)
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_non_loopback_peer_rejected():
    request = Request({"type": "http", "client": ("192.0.2.1", 12345),
                       "headers": [(b"host", b"127.0.0.1:8000")]})
    assert not is_local_request(request)


@pytest.mark.parametrize("value", ["", "0", "-1", "abc", "9223372036854775808"])
def test_configuration_fails_closed(monkeypatch, value):
    monkeypatch.setenv("API_ALLOWED_USER_ID", value)
    engine_factory = AsyncMock()
    monkeypatch.setattr("app.api.create_database_engine", engine_factory)
    with pytest.raises(RuntimeError, match="API_ALLOWED_USER_ID"):
        with TestClient(app):
            pass
    engine_factory.assert_not_called()


def test_configuration_error_hides_details(monkeypatch):
    monkeypatch.setenv("API_ALLOWED_USER_ID", "1")

    def fail():
        raise ValueError("private-connection-string")

    monkeypatch.setattr("app.api.create_database_engine", fail)
    with pytest.raises(RuntimeError, match="API database configuration is invalid") as error:
        with TestClient(app):
            pass
    assert "private-connection-string" not in str(error.value)
    assert error.value.__suppress_context__


def test_summary_contract_multiple_expenses_and_owner(client):
    response = client.get("/api/summary?user_id=2&telegram_id=202")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "total_income": "0.00", "total_expense": "10000000125.59",
        "balance": "-10000000125.59",
    }


def test_summary_without_transactions(client):
    app.state.allowed_user_id = 999
    response = client.get("/api/summary")
    assert response.status_code == 200
    assert response.json() == {
        "total_income": "0.00", "total_expense": "0.00", "balance": "0.00",
    }


def test_summary_one_expense(client):
    app.state.allowed_user_id = 2
    assert client.get("/api/summary").json() == {
        "total_income": "0.00", "total_expense": "9.99", "balance": "-9.99",
    }


def test_summary_independent_of_transactions_pagination(client):
    before = client.get("/api/summary").json()
    assert len(client.get("/api/transactions?limit=1&offset=1").json()) == 1
    assert client.get("/api/summary?limit=1&offset=999").json() == before


def test_summary_decimal_arithmetic(client):
    # SQLite SUM uses floating point internally. Supply PostgreSQL-like NUMERIC
    # results here to independently verify exact Decimal handling by the API.
    from unittest.mock import MagicMock

    result = MagicMock()
    result.one.return_value = (Decimal("0.00"), Decimal("0.30"))
    session = AsyncMock()
    session.execute.return_value = result
    session.__aenter__.return_value = session
    app.state.session_factory = lambda: session
    assert client.get("/api/summary").json() == {
        "total_income": "0.00", "total_expense": "0.30", "balance": "-0.30",
    }
    statement = session.execute.call_args.args[0]
    assert "sum(transactions.amount)" in str(statement)
    assert "transactions.user_id =" in str(statement)
    assert "LIMIT" not in str(statement)


@pytest.mark.parametrize("stage", ["open", "execute"])
def test_summary_database_failure_is_safe(client, caplog, stage):
    marker = "private-connection-string SQL parameters user_id=123"
    if stage == "open":
        def fail():
            raise RuntimeError(marker)
        app.state.session_factory = fail
    else:
        session = AsyncMock()
        session.__aenter__.return_value = session
        session.execute.side_effect = RuntimeError(marker)
        app.state.session_factory = lambda: session
    response = client.get("/api/summary")
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable."}
    assert response.headers["cache-control"] == "no-store"
    assert marker not in response.text + caplog.text
    assert all(record.exc_info is None for record in caplog.records)


def test_summary_reuses_local_access_restrictions(client):
    response = client.get("/api/summary", headers={"origin": "https://attacker.example"})
    assert response.status_code == 403
    assert response.headers["cache-control"] == "no-store"


def test_summary_large_mixed_totals_remain_exact(client):
    from unittest.mock import MagicMock
    result = MagicMock()
    result.one.return_value = (Decimal("10000000000000000000000000000.30"), Decimal("0.10"))
    session = AsyncMock()
    session.execute.return_value = result
    session.__aenter__.return_value = session
    app.state.session_factory = lambda: session
    assert client.get("/api/summary").json() == {
        "total_income": "10000000000000000000000000000.30",
        "total_expense": "0.10", "balance": "10000000000000000000000000000.20"}
