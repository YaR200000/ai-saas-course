"""AI HTTP and aggregation tests: SQLite fixtures and mock provider only."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, insert, update

from app.api import app
from app.ai_analysis import AnalysisLimited, AnalysisLimiter, KYIV, load_financial_snapshot
from app.gemini_client import GeminiFailure
from app.models import Category, Transaction
from app.schemas import AiAnalysisResponse, GeminiAnalysis
from test_transactions_api import client

URL = "/api/ai/analyze-transactions"
AUTH = {"Authorization": "Bearer synthetic-admin"}
TODAY = date(2026, 11, 23)
PROSE = {"summary": "Підсумок записаних фінансових операцій.",
         "risks": ["Можлива концентрація витрат в окремих категоріях."],
         "advice": ["Перегляньте найбільші категорії витрат."]}


@pytest.fixture
def ai_client(client, monkeypatch):
    app.state.admin_password = b"synthetic-admin"
    app.state.gemini = SimpleNamespace(analyze=AsyncMock(return_value=GeminiAnalysis(**PROSE)), aclose=AsyncMock())
    clock = SimpleNamespace(tick=0.0, now=datetime(2026, 11, 23, 12, tzinfo=KYIV))
    app.state.ai_limiter = AnalysisLimiter(20, clock=lambda: clock.tick, now=lambda: clock.now)
    monkeypatch.setattr("app.ai_analysis.kyiv_now", lambda: clock.now)
    return client, app.state.gemini, clock


@pytest.fixture
def seeded(ai_client):
    client, provider, clock = ai_client
    async def seed():
        async with app.state.session_factory() as session:
            connection = session.connection
            connection.execute(delete(Transaction))
            connection.execute(update(Category).where(Category.id == 1).values(name="private-category-1"))
            connection.execute(insert(Category), [dict(id=i, name=f"private-category-{i}") for i in range(2, 8)])
            amounts = [("income", 1, "1000.01", TODAY - timedelta(days=29), 1),
                       ("income", 1, "2000.02", TODAY, 1),
                       ("expense", 1, "100.10", TODAY, 1),
                       ("expense", 1, "0.20", TODAY, 1),
                       *[("expense", i, f"{i * 100}.00", TODAY, 1) for i in range(2, 8)],
                       ("income", 1, "9999.99", TODAY - timedelta(days=30), 1),
                       ("expense", 1, "9999.99", TODAY + timedelta(days=1), 1),
                       ("expense", 1, "9999.99", TODAY, 2)]
            connection.execute(insert(Transaction), [dict(
                id=i, type=kind, user_id=owner, category_id=category,
                amount=Decimal(amount), date=day, description="private-description",
                created_at=datetime(2026, 11, 23, tzinfo=timezone.utc),
                telegram_chat_id=100 + i, telegram_message_id=200 + i,
            ) for i, (kind, category, amount, day, owner) in enumerate(amounts, 1)])
            connection.commit()
    client.portal.call(seed)
    return ai_client


def test_snapshot_endpoint_owner_period_exact_categories_and_private_payload(seeded):
    client, provider, _ = seeded
    response = client.post(URL + "?user_id=2&type=expense&limit=1", headers={**AUTH, "X-User-Id": "2"})
    assert response.status_code == 200
    data = response.json()
    assert data["period_start"] == "2026-10-25" and data["period_end"] == "2026-11-23"
    assert data["total_income"] == "3000.03"
    assert data["total_expense"] == "2800.30"
    assert data["balance"] == "199.73"
    assert data["transaction_count"] == 10
    assert [c["amount"] for c in data["top_expense_categories"]] == ["700.00", "600.00", "500.00", "400.00", "300.00"]
    assert [c["category"] for c in data["top_expense_categories"]] == [f"private-category-{i}" for i in [7, 6, 5, 4, 3]]
    assert data["top_expense_categories"][0]["share_percent"] == "25.00"
    provider.analyze.assert_awaited_once()
    payload = provider.analyze.call_args.args[0]
    assert payload["income_count"] == 2 and payload["expense_count"] == 8
    assert payload["other_expense"] == "300.30"
    assert payload["top_expense_categories"][0]["category"] == "category_1"
    assert set(payload) == {"period_start", "period_end", "currency", "transaction_count", "total_income",
                            "total_expense", "balance", "income_count", "expense_count", "other_expense", "top_expense_categories"}
    assert not any(private in str(payload) for private in ["private-", "telegram", "user_id", "description", "synthetic-admin"])
    AiAnalysisResponse.model_validate_json(response.content)
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"


@pytest.mark.parametrize("authorization", [None, "Bearer wrong", "Basic synthetic-admin", "Bearer"])
def test_auth_before_body_financial_read_or_provider(ai_client, authorization):
    client, provider, _ = ai_client
    database = MagicMock(side_effect=AssertionError("must not read"))
    app.state.session_factory = database
    response = client.post(URL, content="private-broken-json{", headers={"Authorization": authorization} if authorization else {})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    database.assert_not_called()
    provider.analyze.assert_not_called()


@pytest.mark.parametrize("headers", [{"Origin": "https://foreign.example"}, {"Host": "foreign.example"},
                                     {"Sec-Fetch-Site": "cross-site"}])
def test_local_guards(ai_client, headers):
    client, provider, _ = ai_client
    response = client.post(URL, headers={**AUTH, **headers})
    assert response.status_code == 403
    assert app.state.ai_limiter.count == 0
    provider.analyze.assert_not_called()


def test_missing_key_leaves_existing_api_available(client):
    app.state.admin_password = b"synthetic-admin"
    assert app.state.gemini is None
    assert client.post(URL, headers=AUTH).status_code == 503
    assert client.get("/api/transactions?type=expense").status_code == 200
    assert client.get("/api/summary").status_code == 200


def test_disabled_admin_password(ai_client):
    client, provider, _ = ai_client
    app.state.admin_password = None
    assert client.post(URL, headers=AUTH).status_code == 503
    provider.analyze.assert_not_called()


@pytest.mark.parametrize("body", ["{}", "null", "private"])
def test_nonempty_body_rejected_without_read(ai_client, body):
    client, provider, _ = ai_client
    database = MagicMock(side_effect=AssertionError("must not read"))
    app.state.session_factory = database
    assert client.post(URL, headers=AUTH, content=body).status_code == 422
    database.assert_not_called()
    provider.analyze.assert_not_called()


def test_empty_history_no_gemini(ai_client):
    client, provider, _ = ai_client
    app.state.allowed_user_id = 999
    response = client.post(URL, headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    assert data["transaction_count"] == 0
    assert data["total_income"] == data["total_expense"] == data["balance"] == "0.00"
    assert data["top_expense_categories"] == data["risks"] == data["advice"] == []
    assert data["period_start"] == "2026-10-25"
    provider.analyze.assert_not_called()


def test_income_only_no_division_by_zero(seeded):
    client, provider, _ = seeded
    async def remove_expenses():
        async with app.state.session_factory() as session:
            await session.execute(delete(Transaction).where(Transaction.type == "expense"))
            session.connection.commit()
    client.portal.call(remove_expenses)
    response = client.post(URL, headers=AUTH)
    assert response.status_code == 200
    assert response.json()["top_expense_categories"] == []
    assert provider.analyze.call_args.args[0]["other_expense"] == "0.00"


def test_session_closed_before_provider(seeded):
    client, provider, _ = seeded
    factory = app.state.session_factory
    tracking = SimpleNamespace(active=0, statements=0)
    class TrackingSession:
        async def __aenter__(self):
            self.session = factory()
            await self.session.__aenter__()
            tracking.active += 1
            return self
        async def __aexit__(self, *args):
            try:
                return await self.session.__aexit__(*args)
            finally:
                tracking.active -= 1
        async def execute(self, statement):
            tracking.statements += 1
            return await self.session.execute(statement)
    app.state.session_factory = TrackingSession
    async def analyze(payload):
        assert tracking.active == 0 and tracking.statements == 1
        return GeminiAnalysis(**PROSE)
    provider.analyze.side_effect = analyze
    assert client.post(URL, headers=AUTH).status_code == 200


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_provider_errors_safe_no_retries(seeded, status, caplog):
    client, provider, clock = seeded
    provider.analyze.side_effect = GeminiFailure(status)
    response = client.post(URL, headers=AUTH)
    assert response.status_code == status
    provider.analyze.assert_awaited_once()
    if status == 429:
        assert response.headers["retry-after"] == "60"
    assert "private-" not in response.text + caplog.text
    assert client.post(URL, headers=AUTH).status_code == 429
    provider.analyze.assert_awaited_once()
    assert not app.state.ai_limiter.active


def test_database_failure_sanitized(ai_client, caplog):
    client, provider, _ = ai_client
    app.state.session_factory = MagicMock(side_effect=RuntimeError("private-password-sql"))
    response = client.post(URL, headers=AUTH)
    assert response.status_code == 503
    assert "private-password-sql" not in response.text + caplog.text
    assert all(record.exc_info is None for record in caplog.records)
    provider.analyze.assert_not_called()
    assert not app.state.ai_limiter.active


def test_frequency_and_daily_limit(seeded):
    client, provider, clock = seeded
    app.state.ai_limiter.daily_limit = 2
    assert client.post(URL, headers=AUTH).status_code == 200
    assert client.post(URL, headers=AUTH).status_code == 429
    clock.tick = 59.1
    assert client.post(URL, headers=AUTH).headers["retry-after"] == "1"
    clock.tick = 60
    assert client.post(URL, headers=AUTH).status_code == 200
    clock.tick = 120
    assert client.post(URL, headers=AUTH).status_code == 429
    assert provider.analyze.await_count == 2
    clock.now += timedelta(days=1)
    assert client.post(URL, headers=AUTH).status_code == 200
    assert provider.analyze.await_count == 3


def test_concurrent_request_rejected_and_gate_released(seeded):
    client, provider, clock = seeded
    # Entering a second reservation models a second task during an awaited call.
    with app.state.ai_limiter.reserve():
        clock.tick = 120
        assert client.post(URL, headers=AUTH).status_code == 429
        provider.analyze.assert_not_called()
    assert client.post(URL, headers=AUTH).status_code == 200


def test_gate_released_after_cancellation_and_midnight_does_not_bypass_cooldown():
    clock = SimpleNamespace(tick=0, now=datetime(2026, 11, 23, 23, 59, 50, tzinfo=KYIV))
    limiter = AnalysisLimiter(1, clock=lambda: clock.tick, now=lambda: clock.now)
    with pytest.raises(BaseException):
        with limiter.reserve():
            raise BaseException("synthetic cancellation")
    assert not limiter.active
    clock.now += timedelta(seconds=20)
    clock.tick = 20
    with pytest.raises(AnalysisLimited) as error:
        with limiter.reserve():
            pass
    assert error.value.retry_after == 40
    clock.tick = 60
    with limiter.reserve():
        pass


@pytest.mark.asyncio
async def test_decimal_math_beyond_default_context():
    income = Decimal("10000000000000000000000000000.30")
    rows = [dict(income=income, expense=Decimal("0.10"), income_count=1, expense_count=1,
                 category="Тест", amount=Decimal("0.10"))]
    session = AsyncMock()
    session.__aenter__.return_value = session
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    session.execute.return_value = result
    snapshot = await load_financial_snapshot(lambda: session, 1, today=TODAY)
    assert snapshot.facts["balance"] == "10000000000000000000000000000.20"
    assert snapshot.categories[0].share_percent == "100.00"
    session.execute.assert_awaited_once()


@pytest.mark.parametrize("value", ["", " ", "a" * 1201, 42])
def test_prose_summary_constraints(value):
    with pytest.raises(ValidationError):
        GeminiAnalysis(**{**PROSE, "summary": value})


@pytest.mark.parametrize("change", [{"extra": "private"}, {"risks": ["a"] * 6},
                                    {"advice": ["a" * 501]}, {"risks": [""]}, {"advice": "a"}])
def test_prose_shape_constraints(change):
    with pytest.raises(ValidationError):
        GeminiAnalysis(**{**PROSE, **change})


@pytest.mark.asyncio
@pytest.mark.parametrize("utc,end", [
    (datetime(2026, 11, 22, 22, 30, tzinfo=timezone.utc), date(2026, 11, 23)),
    (datetime(2026, 6, 30, 21, 30, tzinfo=timezone.utc), date(2026, 7, 1)),
    (datetime(2024, 2, 29, 22, 30, tzinfo=timezone.utc), date(2024, 3, 1)),
    (datetime(2026, 10, 25, 22, 30, tzinfo=timezone.utc), date(2026, 10, 26)),
])
async def test_period_uses_kyiv_calendar_at_utc_boundary(monkeypatch, utc, end):
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            assert tz is KYIV
            return utc.astimezone(tz)
    monkeypatch.setattr("app.ai_analysis.datetime", FrozenDatetime)
    session = AsyncMock()
    session.__aenter__.return_value = session
    result = MagicMock()
    result.mappings.return_value.all.return_value = [dict(
        income=Decimal("0"), expense=Decimal("0"), income_count=0, expense_count=0,
        category=None, amount=None)]
    session.execute.return_value = result
    snapshot = await load_financial_snapshot(lambda: session, 1)
    assert snapshot.facts["period_end"] == end
    assert snapshot.facts["period_start"] == end - timedelta(days=29)


def test_snapshot_rounding_and_tied_category_order(seeded):
    client, _, _ = seeded
    async def change_amounts():
        async with app.state.session_factory() as session:
            await session.execute(update(Transaction).where(Transaction.type == "expense").values(amount=Decimal("1.00")))
            session.connection.commit()
    client.portal.call(change_amounts)
    response = client.post(URL, headers=AUTH)
    assert response.status_code == 200
    data = response.json()
    # Category 1 has two transactions; remaining ties are ordered by name.
    assert [c["category"] for c in data["top_expense_categories"]] == [f"private-category-{i}" for i in range(1, 6)]
    assert [c["share_percent"] for c in data["top_expense_categories"]] == ["25.00", "12.50", "12.50", "12.50", "12.50"]
