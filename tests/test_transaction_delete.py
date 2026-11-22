"""HTTP and transaction-boundary tests, without a database connection."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.api import app
from app.transactions import delete_transaction
from test_transactions_api import client

AUTH = {"Authorization": "Bearer synthetic-admin"}


@pytest.mark.parametrize("found,status", [(True, 204), (False, 404)])
def test_delete_contract_and_server_owner(client, monkeypatch, found, status):
    app.state.admin_password = b"synthetic-admin"
    service = AsyncMock(return_value=found)
    monkeypatch.setattr("app.api.delete_transaction", service)
    response = client.delete("/api/transactions/9223372036854775807?user_id=2",
                             headers={**AUTH, "X-User-Id": "2"})
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    if found:
        assert response.content == b""
        assert "content-type" not in response.headers
    else:
        assert response.json() == {"detail": "Transaction not found."}
    assert service.call_args.args[1:] == (1, 9223372036854775807)


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer wrong"}])
@pytest.mark.parametrize("target", ["1", "bad"])
def test_auth_precedes_validation_and_service(client, monkeypatch, headers, target):
    app.state.admin_password = b"synthetic-admin"
    service = AsyncMock()
    monkeypatch.setattr("app.api.delete_transaction", service)
    response = client.delete(f"/api/transactions/{target}", headers=headers)
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    service.assert_not_called()


def test_disabled_writes(client, monkeypatch):
    service = AsyncMock()
    monkeypatch.setattr("app.api.delete_transaction", service)
    assert client.delete("/api/transactions/1", headers=AUTH).status_code == 503
    service.assert_not_called()


@pytest.mark.parametrize("headers", [
    {"Host": "attacker.example"}, {"Origin": "https://attacker.example"},
    {"Origin": "null"}, {"Sec-Fetch-Site": "cross-site"}, {"Sec-Fetch-Site": "same-site"},
])
def test_middleware_rejects_before_service(client, monkeypatch, headers):
    app.state.admin_password = b"synthetic-admin"
    service = AsyncMock()
    monkeypatch.setattr("app.api.delete_transaction", service)
    assert client.delete("/api/transactions/1", headers={**AUTH, **headers}).status_code == 403
    service.assert_not_called()


@pytest.mark.asyncio
async def test_nonloopback_rejected_without_storage(client, monkeypatch):
    import httpx
    app.state.admin_password = b"synthetic-admin"
    service = AsyncMock()
    monkeypatch.setattr("app.api.delete_transaction", service)
    transport = httpx.ASGITransport(app=app, client=("192.0.2.1", 12345))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8000") as remote:
        assert (await remote.delete("/api/transactions/1", headers=AUTH)).status_code == 403
    service.assert_not_called()


@pytest.mark.parametrize("target", ["0", "-1", "abc", "1.0", "9223372036854775808", "9" * 100, "+1"])
def test_invalid_id(client, monkeypatch, target):
    app.state.admin_password = b"synthetic-admin"
    service = AsyncMock()
    monkeypatch.setattr("app.api.delete_transaction", service)
    assert client.delete(f"/api/transactions/{target}", headers=AUTH).status_code == 422
    service.assert_not_called()


def test_service_failure_safe_no_retry(client, monkeypatch, caplog):
    app.state.admin_password = b"synthetic-admin"
    service = AsyncMock(side_effect=RuntimeError("private-password SQL description"))
    monkeypatch.setattr("app.api.delete_transaction", service)
    response = client.delete("/api/transactions/1", headers=AUTH)
    assert response.status_code == 503
    assert response.json() == {"detail": "Deletion could not be confirmed; refresh before retrying."}
    assert "private-password" not in response.text + caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    service.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["success", "missing", "execute", "commit"])
async def test_transaction_boundary_and_atomic_statement(stage):
    events = []
    session = AsyncMock()
    session.scalar.return_value = None if stage == "missing" else 7
    if stage == "execute":
        session.scalar.side_effect = RuntimeError("execution failure")
    transaction = AsyncMock()

    async def finish(exc_type, exc, traceback):
        events.append("rollback" if exc_type else "commit")
        if stage == "commit":
            raise RuntimeError("commit failure")

    transaction.__aexit__.side_effect = finish
    session.begin = MagicMock(return_value=transaction)
    context = AsyncMock()
    context.__aenter__.return_value = session
    factory = MagicMock(return_value=context)
    if stage in {"execute", "commit"}:
        with pytest.raises(RuntimeError):
            await delete_transaction(factory, 3, 7)
    else:
        assert await delete_transaction(factory, 3, 7) is (stage == "success")
    assert events == (["rollback"] if stage == "execute" else ["commit"])
    factory.assert_called_once()
    session.scalar.assert_awaited_once()
    statement = session.scalar.call_args.args[0].compile(dialect=postgresql.dialect())
    assert str(statement).startswith("DELETE FROM transactions WHERE")
    assert "transactions.id =" in str(statement) and "transactions.user_id =" in str(statement)
    assert "RETURNING transactions.id" in str(statement)
    assert set(statement.params.values()) == {3, 7}
    session.flush.assert_not_called()
