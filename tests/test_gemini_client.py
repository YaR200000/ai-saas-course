"""Real pinned SDK, synthetic HTTP transport: no provider/network calls."""
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient
from google import genai
from google.genai import types

from app.api import app
from app.gemini_client import GeminiClient, GeminiFailure, GeminiSettings, SYSTEM_INSTRUCTION
from app.schemas import GeminiAnalysis

PROSE = {"summary": "Підсумок записаних операцій.", "risks": [], "advice": ["Перевірте облік витрат."]}


def sdk_response(text=None, *, finish="STOP", feedback=None):
    data = {"candidates": [{"finishReason": finish, "content": {
        "role": "model", "parts": [{"text": text if text is not None else json.dumps(PROSE)}]}}]}
    if feedback:
        data["promptFeedback"] = feedback
    return data


@pytest.fixture
def transport_factory(monkeypatch):
    original = genai.Client
    def factory(handler, *, timeout=1):
        async_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        def construct(**kwargs):
            options = kwargs["http_options"]
            assert kwargs["api_key"] == "synthetic-key"
            assert kwargs["vertexai"] is False
            assert options.retry_options.attempts == 1
            assert options.timeout == timeout * 1000
            assert options.base_url == "https://generativelanguage.googleapis.com"
            options.httpx_async_client = async_client
            return original(**kwargs)
        monkeypatch.setattr("app.gemini_client.genai.Client", construct)
        client = GeminiClient("synthetic-key", GeminiSettings("gemini-3.8-flash", timeout, 20))
        close = client.aclose
        async def close_all():
            try:
                await close()
            finally:
                await async_client.aclose()
        client.aclose = close_all
        return client
    return factory


@pytest.mark.asyncio
async def test_real_sdk_structured_config_and_no_private_schema(transport_factory):
    requests = []
    def handler(request):
        requests.append(request)
        body = json.loads(request.content)
        assert request.headers["x-goog-api-key"] == "synthetic-key"
        assert body["generationConfig"]["maxOutputTokens"] == 2048
        assert body["generationConfig"]["candidateCount"] == 1
        assert body["generationConfig"]["thinkingConfig"]["thinking_level"] == "LOW"
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        schema = body["generationConfig"]["responseJsonSchema"]
        assert set(schema["properties"]) == {"summary", "risks", "advice"}
        assert schema["additionalProperties"] is False
        assert "tools" not in body
        assert body["systemInstruction"]["parts"][0]["text"] == SYSTEM_INSTRUCTION
        return httpx.Response(200, json=sdk_response())
    client = transport_factory(handler)
    try:
        result = await client.analyze({"currency": "UAH", "total_income": "100.00"})
        assert result == GeminiAnalysis(**PROSE)
        assert len(requests) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    sdk_response("not-json-private"), sdk_response(json.dumps({**PROSE, "amount": "999.99"})),
    sdk_response("{}"), sdk_response(json.dumps({**PROSE, "risks": ["a"] * 6})),
    sdk_response(json.dumps({**PROSE, "summary": "a" * 1201})),
    sdk_response(finish="MAX_TOKENS"), sdk_response(finish="SAFETY"),
    {"promptFeedback": {"blockReason": "SAFETY"}}, {"candidates": []},
    sdk_response(feedback={"blockReason": "SAFETY"}),
    {"candidates": sdk_response()["candidates"] * 2},
    {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"functionCall": {"name": "test", "args": {}}}]}}]},
])
async def test_invalid_partial_or_blocked_response_rejected_once(transport_factory, body, caplog):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=body)
    client = transport_factory(handler)
    try:
        with pytest.raises(GeminiFailure) as error:
            await client.analyze({"currency": "UAH"})
        assert error.value.status == 502
        assert len(calls) == 1
        assert "not-json-private" not in caplog.text
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_unspecified_feedback_is_not_a_block(transport_factory):
    client = transport_factory(lambda request: httpx.Response(200, json=sdk_response(
        feedback={"blockReason": "BLOCKED_REASON_UNSPECIFIED"})))
    try:
        assert await client.analyze({}) == GeminiAnalysis(**PROSE)
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("code,expected", [(400, 503), (401, 503), (403, 503), (404, 503),
                                          (429, 429), (500, 503), (503, 503), (504, 504), (408, 504)])
async def test_http_errors_never_retry_or_expose_sdk_details(transport_factory, code, expected, caplog):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(code, json={"error": {"code": code, "message": "private-provider-secret", "status": "UNAVAILABLE"}})
    client = transport_factory(handler)
    try:
        with pytest.raises(GeminiFailure) as error:
            await client.analyze({"currency": "UAH"})
        assert error.value.status == expected
        assert len(calls) == 1
        assert "private-provider-secret" not in str(error.value) + caplog.text
    finally:
        await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["timeout", "connection"])
async def test_network_errors_sanitized_without_retry(transport_factory, kind):
    calls = []
    def handler(request):
        calls.append(request)
        if kind == "timeout":
            raise httpx.ReadTimeout("private-timeout", request=request)
        raise httpx.ConnectError("private-network", request=request)
    client = transport_factory(handler)
    try:
        with pytest.raises(GeminiFailure) as error:
            await client.analyze({})
        assert error.value.status == (504 if kind == "timeout" else 503)
        assert len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_total_deadline_cancels_stalled_sdk(transport_factory):
    calls = []
    async def handler(request):
        calls.append(request)
        await asyncio.sleep(10)
        return httpx.Response(200, json=sdk_response())
    client = transport_factory(handler)
    try:
        with pytest.raises(GeminiFailure) as error:
            await client.analyze({})
        assert error.value.status == 504 and len(calls) == 1
    finally:
        await client.aclose()


@pytest.mark.parametrize("name,value", [("GEMINI_TIMEOUT_SECONDS", "0"), ("GEMINI_TIMEOUT_SECONDS", "121"),
                                       ("GEMINI_TIMEOUT_SECONDS", "nan"), ("GEMINI_DAILY_LIMIT", "0"),
                                       ("GEMINI_DAILY_LIMIT", "1001"), ("GEMINI_MODEL", "private/bad")])
def test_configuration_validation(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(ValueError):
        GeminiSettings.from_environment()


def test_settings_defaults(monkeypatch):
    for name in ["GEMINI_MODEL", "GEMINI_TIMEOUT_SECONDS", "GEMINI_DAILY_LIMIT"]:
        monkeypatch.delenv(name, raising=False)
    assert GeminiSettings.from_environment() == GeminiSettings("gemini-3.8-flash", 30, 20)


@pytest.mark.parametrize("mode", ["configured", "invalid-config", "constructor-failure", "close-failure", "missing-key"])
def test_lifecycle_and_configuration_failure_leave_get_working(monkeypatch, mode, caplog):
    engine = SimpleNamespace(dispose=AsyncMock())
    provider = SimpleNamespace(aclose=AsyncMock())
    calls = []
    def construct(key, settings):
        calls.append((key, settings))
        if mode == "constructor-failure":
            raise RuntimeError("private-constructor-key")
        return provider
    monkeypatch.setenv("API_ALLOWED_USER_ID", "1")
    monkeypatch.setenv("ADMIN_PASSWORD", "synthetic-admin")
    monkeypatch.setenv("GEMINI_API_KEY", "synthetic-key")
    for name in ["GEMINI_MODEL", "GEMINI_TIMEOUT_SECONDS", "GEMINI_DAILY_LIMIT"]:
        monkeypatch.delenv(name, raising=False)
    if mode == "invalid-config":
        monkeypatch.setenv("GEMINI_TIMEOUT_SECONDS", "private-invalid")
    if mode == "close-failure":
        provider.aclose.side_effect = RuntimeError("private-close-key")
    if mode == "missing-key":
        monkeypatch.delenv("GEMINI_API_KEY")
        # Neither a legacy key nor GOOGLE_API_KEY can enable this endpoint.
        monkeypatch.setenv("GOOGLE_API_KEY", "private-google-key")
        monkeypatch.setenv("AI_API_KEY", "private-legacy-key")
    monkeypatch.setattr("app.api.create_database_engine", lambda: engine)
    monkeypatch.setattr("app.api.check_schema_ready", AsyncMock())
    monkeypatch.setattr("app.api.create_session_factory", lambda _: None)
    monkeypatch.setattr("app.api.GeminiClient", construct)
    with TestClient(app, base_url="http://127.0.0.1:8000", client=("127.0.0.1", 40000)) as client:
        # Validation of existing GET still works without opening a DB session.
        assert client.get("/api/transactions?limit=0").status_code == 422
        if mode in {"missing-key", "invalid-config", "constructor-failure"}:
            assert client.post("/api/ai/analyze-transactions", headers={"Authorization": "Bearer synthetic-admin"}).status_code == 503
        else:
            assert app.state.gemini is provider
    engine.dispose.assert_awaited_once()
    if mode in {"configured", "close-failure"}:
        provider.aclose.assert_awaited_once()
    assert "private-" not in caplog.text
