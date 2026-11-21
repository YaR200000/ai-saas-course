"""Validation/auth HTTP tests do not write to any database."""
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.api import app
from app.schemas import TransactionCreate
from test_transactions_api import client

PAYLOAD = dict(type="income", amount="300.00", category=" Зарплата ",
               description=" Виплата ", date="2026-11-21")


@pytest.mark.parametrize("field,value", [
    ("type", "other"), ("type", None),
    *[("amount", v) for v in [0, 1, 1.25, True, None, "0", "-1", "NaN", "Infinity", "1e2", "1,20", "0.001", "10000000000", "1.000", " 1"]],
    *[("category", v) for v in ["", " ", "a" * 101, 12, None, "a\x00"]],
    *[("description", v) for v in ["", " ", "a" * 2001, 12, None]],
    *[("date", v) for v in ["2026-02-30", "2026-2-01", "2026-01-01T00:00:00Z", 123, None]],
    ("user_id", 2), ("telegram_id", 2),
])
def test_schema_rejects_invalid(field, value):
    with pytest.raises(ValidationError):
        TransactionCreate.model_validate({**PAYLOAD, field: value})


@pytest.mark.parametrize("field", list(PAYLOAD))
def test_required_fields(field):
    with pytest.raises(ValidationError):
        TransactionCreate.model_validate({k: v for k, v in PAYLOAD.items() if k != field})


def test_valid_boundaries_and_trim():
    data = TransactionCreate.model_validate({**PAYLOAD, "amount": "9999999999.99"})
    assert str(data.amount) == "9999999999.99"
    assert data.category == "Зарплата" and data.description == "Виплата"
    assert TransactionCreate.model_validate({**PAYLOAD, "date": "2024-02-29"}).date.day == 29


@pytest.mark.parametrize("header", [None, "Bearer wrong", "Basic test", "Bearer"])
@pytest.mark.parametrize("body", ['{"invalid":', '{"amount":"secret-input"}'])
def test_auth_precedes_body_and_storage(client, monkeypatch, header, body):
    app.state.admin_password = b"synthetic-admin"
    storage = AsyncMock()
    monkeypatch.setattr("app.api.create_transaction", storage)
    response = client.post("/api/transactions", content=body,
                           headers={"Authorization": header} if header else {})
    assert response.status_code == 401
    assert "secret-input" not in response.text
    assert response.headers["cache-control"] == "no-store"
    storage.assert_not_called()


def test_disabled_password_leaves_get_available(client, monkeypatch):
    storage = AsyncMock()
    monkeypatch.setattr("app.api.create_transaction", storage)
    assert client.post("/api/transactions", json=PAYLOAD).status_code == 503
    assert client.get("/api/summary").status_code == 200
    storage.assert_not_called()


def test_validation_safe_and_owner_not_accepted(client, monkeypatch):
    app.state.admin_password = b"synthetic-admin"
    storage = AsyncMock()
    monkeypatch.setattr("app.api.create_transaction", storage)
    for change in ({"user_id": "sensitive-owner"}, {"amount": "sensitive-amount"}, {"date": "secret"}):
        response = client.post("/api/transactions", json={**PAYLOAD, **change},
                               headers={"Authorization": "Bearer synthetic-admin"})
        assert response.status_code == 422
        assert not any(str(v) in response.text for v in change.values())
    storage.assert_not_called()


def test_storage_failure_safe(client, monkeypatch, caplog):
    app.state.admin_password = b"synthetic-admin"
    storage = AsyncMock(side_effect=RuntimeError("private-sql-and-password"))
    monkeypatch.setattr("app.api.create_transaction", storage)
    response = client.post("/api/transactions?user_id=2", json=PAYLOAD,
                           headers={"Authorization": "Bearer synthetic-admin", "X-User-Id": "2"})
    assert response.status_code == 503
    assert "private-sql-and-password" not in response.text + caplog.text
    assert storage.call_args.args[1] == 1
    storage.assert_awaited_once()


def test_post_201_contract_and_server_owner(client, monkeypatch):
    from datetime import datetime, timezone
    from app.schemas import TransactionResponse

    app.state.admin_password = b"synthetic-admin"
    data = TransactionCreate.model_validate(PAYLOAD)
    storage = AsyncMock(return_value=TransactionResponse(
        id="9007199254740993", created_at=datetime(2026, 11, 21, tzinfo=timezone.utc),
        **{**data.model_dump(), "amount": "300.00"},
    ))
    monkeypatch.setattr("app.api.create_transaction", storage)
    response = client.post("/api/transactions?user_id=2", json=PAYLOAD,
                           headers={"Authorization": "Bearer synthetic-admin", "X-User-Id": "2"})
    assert response.status_code == 201
    row = response.json()
    assert row["id"] == "9007199254740993" and row["amount"] == "300.00"
    assert row["type"] == "income" and row["date"] == "2026-11-21"
    assert row["category"] == "Зарплата" and row["currency"] == "UAH"
    assert "user_id" not in row and "telegram_chat_id" not in row
    assert storage.call_args.args[1] == 1


def test_startup_schema_failure_is_safe(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("API_ALLOWED_USER_ID", "1")
    engine = AsyncMock()
    monkeypatch.setattr("app.api.create_database_engine", lambda: engine)
    monkeypatch.setattr("app.api.check_schema_ready", AsyncMock(side_effect=RuntimeError("migration 002 is required")))
    with pytest.raises(RuntimeError, match="migration 002"):
        with TestClient(app):
            pass
    engine.dispose.assert_awaited_once()


def test_authorized_bad_json_and_foreign_origin(client, monkeypatch):
    app.state.admin_password = b"synthetic-admin"
    storage = AsyncMock()
    monkeypatch.setattr("app.api.create_transaction", storage)
    headers = {"Authorization": "Bearer synthetic-admin"}
    assert client.post("/api/transactions", content="{", headers=headers).status_code == 422
    assert client.post("/api/transactions", json=PAYLOAD,
                       headers={**headers, "Origin": "https://attacker.example"}).status_code == 403
    storage.assert_not_called()


def test_lifespan_loads_password_without_echo(monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("API_ALLOWED_USER_ID", "1")
    monkeypatch.setenv("ADMIN_PASSWORD", "synthetic-пароль")
    monkeypatch.setattr("app.api.create_database_engine", lambda: AsyncMock())
    monkeypatch.setattr("app.api.check_schema_ready", AsyncMock())
    with TestClient(app):
        assert app.state.admin_password == "synthetic-пароль".encode("utf-8")


@pytest.mark.asyncio
async def test_commit_failure_propagates_without_retry():
    from datetime import datetime, timezone
    from unittest.mock import MagicMock
    from app.transactions import create_transaction

    session = AsyncMock()
    session.scalar.side_effect = [1, 3]
    result = MagicMock()
    result.one.return_value = type("Row", (), {"id": 7, "created_at": datetime.now(timezone.utc)})()
    session.execute.return_value = result
    transaction = AsyncMock()
    transaction.__aexit__.side_effect = RuntimeError("synthetic commit failure")
    session.begin = MagicMock(return_value=transaction)
    context = AsyncMock()
    context.__aenter__.return_value = session
    factory = MagicMock(return_value=context)
    with pytest.raises(RuntimeError, match="synthetic commit failure"):
        await create_transaction(factory, 1, TransactionCreate.model_validate(PAYLOAD))
    factory.assert_called_once()
    assert session.execute.await_count == 2
