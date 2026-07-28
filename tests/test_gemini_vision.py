from __future__ import annotations

import httpx
import pytest

from pokemon_deal_bot.gemini_vision import GeminiLotVisionAnalyzer
from pokemon_deal_bot.vision import VisionRunBudgetReached


def _success_response(*, total_tokens: int = 125) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "test-interaction",
            "status": "completed",
            "usage": {
                "total_input_tokens": 100,
                "total_output_tokens": 20,
                "total_tokens": total_tokens,
            },
            "steps": [
                {"type": "thought", "signature": "encrypted"},
                {
                    "type": "model_output",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                '{"cards":[],"unrecognized_crop_indexes":[]}'
                            ),
                        }
                    ],
                },
            ],
            "object": "interaction",
            "model": "gemini-3.6-flash",
        },
    )


def _parts(analyzer: GeminiLotVisionAnalyzer) -> list[dict]:
    return [
        {"text": "Identify this card and return JSON only."},
        analyzer._inline_part("image/jpeg", b"jpeg-data"),
    ]


def _analyzer(**overrides) -> GeminiLotVisionAnalyzer:
    values = {
        "api_key": "test-key",
        "model": "gemini-3.6-flash",
        "models": ["gemini-3.6-flash", "gemini-3.5-flash-lite"],
        "max_images": 4,
        "request_spacing_seconds": 0,
        "max_retries_per_model": 0,
        "max_requests_per_run": 20,
    }
    values.update(overrides)
    return GeminiLotVisionAnalyzer(**values)


def test_gemini_interactions_request_uses_inline_image_schema_and_api_key(monkeypatch):
    analyzer = _analyzer(models=["gemini-3.6-flash"])
    captured: dict = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return _success_response()

    monkeypatch.setattr(httpx, "post", fake_post)

    result = analyzer._generate(_parts(analyzer))

    assert result == {"cards": [], "unrecognized_crop_indexes": []}
    assert captured["url"].endswith("/v1beta/interactions")
    assert captured["headers"]["x-goog-api-key"] == "test-key"
    assert captured["headers"]["Api-Revision"] == "2026-05-20"
    assert "Authorization" not in captured["headers"]

    payload = captured["json"]
    assert payload["model"] == "gemini-3.6-flash"
    assert payload["store"] is False
    assert payload["input"][0] == {
        "type": "text",
        "text": "Identify this card and return JSON only.",
    }
    assert payload["input"][1]["type"] == "image"
    assert payload["input"][1]["mime_type"] == "image/jpeg"
    assert payload["input"][1]["data"]
    assert payload["generation_config"]["thinking_level"] == "low"
    assert payload["generation_config"]["max_output_tokens"] == 1600
    assert payload["response_format"]["mime_type"] == "application/json"
    assert payload["response_format"]["schema"]["required"] == [
        "cards",
        "unrecognized_crop_indexes",
    ]
    assert analyzer.usage_summary == (
        "input 100; output 20; thinking 5; total 125 tokens"
    )


def test_gemini_falls_back_to_flash_lite_after_primary_rate_limit(monkeypatch):
    analyzer = _analyzer()
    models: list[str] = []

    def fake_post(url, **kwargs):
        model = kwargs["json"]["model"]
        models.append(model)
        if model == "gemini-3.6-flash":
            return httpx.Response(
                429,
                json={
                    "error": {
                        "code": 429,
                        "status": "RESOURCE_EXHAUSTED",
                        "message": "Quota exceeded",
                    }
                },
            )
        return _success_response()

    monkeypatch.setattr(httpx, "post", fake_post)

    result = analyzer._generate(_parts(analyzer))

    assert result["cards"] == []
    assert models == ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    assert analyzer.model == "gemini-3.5-flash-lite"


def test_gemini_retries_429_using_retry_after(monkeypatch):
    analyzer = _analyzer(
        models=["gemini-3.6-flash"],
        max_retries_per_model=1,
    )
    calls = 0
    sleeps: list[float] = []

    def fake_post(url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                429,
                headers={"Retry-After": "3"},
                json={
                    "error": {
                        "code": 429,
                        "status": "RESOURCE_EXHAUSTED",
                        "message": "Please retry",
                    }
                },
            )
        return _success_response()

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr("pokemon_deal_bot.gemini_vision.time.sleep", sleeps.append)

    analyzer._generate(_parts(analyzer))

    assert calls == 2
    assert sleeps == [3.0]


def test_gemini_falls_back_from_schema_to_prompt_only_json(monkeypatch):
    analyzer = _analyzer(models=["gemini-3.6-flash"])
    payloads: list[dict] = []

    def fake_post(url, **kwargs):
        payloads.append(kwargs["json"])
        if len(payloads) == 1:
            return httpx.Response(
                400,
                json={
                    "error": {
                        "code": 400,
                        "status": "INVALID_ARGUMENT",
                        "message": 'Unknown name "response_format"',
                    }
                },
            )
        return _success_response()

    monkeypatch.setattr(httpx, "post", fake_post)

    analyzer._generate(_parts(analyzer))

    assert "response_format" in payloads[0]
    assert "response_format" not in payloads[1]
    assert analyzer._output_mode_by_model["gemini-3.6-flash"] == "prompt"


def test_gemini_records_usage_for_successful_http_with_invalid_json(monkeypatch):
    analyzer = _analyzer(
        models=["gemini-3.6-flash"],
        max_retries_per_model=0,
    )
    calls = 0

    def fake_post(url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            response = _success_response()
            data = response.json()
            data["steps"][1]["content"][0]["text"] = "not-json"
            return httpx.Response(200, json=data)
        return _success_response()

    monkeypatch.setattr(httpx, "post", fake_post)

    analyzer._generate(_parts(analyzer))

    assert calls == 2
    assert analyzer.total_tokens == 250


def test_gemini_request_budget_is_enforced(monkeypatch):
    analyzer = _analyzer(
        models=["gemini-3.6-flash"],
        max_requests_per_run=1,
    )
    monkeypatch.setattr(httpx, "post", lambda *args, **kwargs: _success_response())

    analyzer._generate(_parts(analyzer))

    with pytest.raises(VisionRunBudgetReached):
        analyzer._generate(_parts(analyzer))
