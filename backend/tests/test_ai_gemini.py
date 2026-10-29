import json
import json as _json

import httpx
import pytest

from app.core.config import Settings
from app.services import ai_insights
from app.services.ai_insights import AIUnavailable, GeminiProvider, get_provider

VALID = {
    "summary": "Ringkasan.",
    "strengths": ["NPM 22,0% (terukur)."],
    "risks": [],
    "valuation_observations": [],
    "missing_information": [],
    "conclusion": "Kesimpulan bersyarat.",
    "limitations": ["Data satu periode."],
}


def fake_post(status=200, body=None, capture=None):
    def _post(url, headers=None, json=None, timeout=None):
        if capture is not None:
            capture.update(url=url, headers=headers, json=json)
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))

    return _post


def ok_body(text, finish="STOP"):
    return {"candidates": [{"content": {"parts": [{"text": "berpikir", "thought": True}, {"text": text}]},
                            "finishReason": finish}], "modelVersion": "gemini-3.8-flash"}


def test_success_uses_schema_and_skips_thought_parts(monkeypatch):
    cap = {}
    monkeypatch.setattr(ai_insights.httpx, "post", fake_post(body=ok_body(json.dumps(VALID)), capture=cap))
    content, model = GeminiProvider("k", "gemini-flash-latest", 30).generate({"metrics": {}})
    assert content.summary == "Ringkasan." and model == "gemini-3.8-flash"
    assert cap["url"].endswith("/gemini-flash-latest:generateContent")
    assert cap["headers"]["x-goog-api-key"] == "k"  # key in header, not URL
    assert "key=" not in cap["url"]
    gc = cap["json"]["generationConfig"]
    assert gc["responseMimeType"] == "application/json" and gc["responseJsonSchema"]["required"]
    assert "<financial_data>" in cap["json"]["contents"][0]["parts"][0]["text"]


@pytest.mark.parametrize("status,err,expect", [
    (400, {"error": {"status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}}, "tidak valid"),
    (429, {"error": {"status": "RESOURCE_EXHAUSTED"}}, "Batas penggunaan"),
    (404, {"error": {"status": "NOT_FOUND"}}, "tidak tersedia"),
    (500, {"error": {"status": "INTERNAL"}}, "galat (500)"),
])
def test_http_errors(monkeypatch, status, err, expect):
    monkeypatch.setattr(ai_insights.httpx, "post", fake_post(status, err))
    with pytest.raises(AIUnavailable) as e:
        GeminiProvider("secret", "m", 30).generate({})
    assert expect in str(e.value) and "secret" not in str(e.value)


def test_blocked_prompt(monkeypatch):
    monkeypatch.setattr(ai_insights.httpx, "post", fake_post(body={"promptFeedback": {"blockReason": "SAFETY"}}))
    with pytest.raises(AIUnavailable, match="menolak"):
        GeminiProvider("k", "m", 30).generate({})


@pytest.mark.parametrize("finish,match", [("MAX_TOKENS", "terpotong"), ("SAFETY", "menolak")])
def test_bad_finish_reason(monkeypatch, finish, match):
    monkeypatch.setattr(ai_insights.httpx, "post", fake_post(body=ok_body(json.dumps(VALID), finish)))
    with pytest.raises(AIUnavailable, match=match):
        GeminiProvider("k", "m", 30).generate({})


def test_invalid_json_output(monkeypatch):
    monkeypatch.setattr(ai_insights.httpx, "post", fake_post(body=ok_body('{"summary": "x"}')))
    with pytest.raises(AIUnavailable, match="format"):
        GeminiProvider("k", "m", 30).generate({})


def test_network_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(ai_insights.httpx, "post", boom)
    with pytest.raises(AIUnavailable, match="dihubungi"):
        GeminiProvider("k", "m", 30).generate({})


def test_provider_selection():
    s = Settings(_env_file=None, ai_provider="gemini", gemini_api_key="g", ai_model="")
    p = get_provider(s)
    assert isinstance(p, GeminiProvider) and p.model == "gemini-3.5-flash"
    assert get_provider(Settings(_env_file=None, ai_provider="gemini", gemini_api_key="")) is None
    assert Settings(_env_file=None, ai_provider="anthropic", anthropic_api_key="a").ai_model_name == "claude-opus-5-5"


def test_retries_once_on_503(monkeypatch):
    calls = []

    def _post(url, headers=None, json=None, timeout=None):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {"status": "UNAVAILABLE"}}, request=httpx.Request("POST", url))
        return httpx.Response(200, json=ok_body(_json.dumps(VALID)), request=httpx.Request("POST", url))

    monkeypatch.setattr(ai_insights.httpx, "post", _post)
    monkeypatch.setattr(GeminiProvider, "RETRY_DELAY", 0)
    content, _ = GeminiProvider("k", "m", 30).generate({})
    assert content.summary == "Ringkasan." and len(calls) == 2


def test_gives_up_after_second_503(monkeypatch):
    monkeypatch.setattr(GeminiProvider, "RETRY_DELAY", 0)
    monkeypatch.setattr(ai_insights.httpx, "post", fake_post(503, {"error": {"status": "UNAVAILABLE"}}))
    with pytest.raises(AIUnavailable, match="503"):
        GeminiProvider("k", "m", 30).generate({})
