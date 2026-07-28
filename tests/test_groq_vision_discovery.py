from __future__ import annotations

from pokemon_deal_bot.vision import LotVisionAnalyzer, VisionModelPoolExhaustedError


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.is_error = status_code >= 400
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.is_error:
            raise RuntimeError(self.text)


def _parts(analyzer: LotVisionAnalyzer) -> list[dict]:
    return [
        {"text": "Return JSON only"},
        analyzer._inline_part("image/jpeg", b"test-image"),
    ]


def test_account_discovery_keeps_only_likely_vision_models(monkeypatch):
    analyzer = LotVisionAnalyzer(
        api_key="secret-key",
        model="qwen/qwen3.6-27b",
        max_images=1,
        auto_discover_models=True,
        request_spacing_seconds=0,
    )

    def fake_get(*args, **kwargs):
        return _FakeResponse(
            200,
            {
                "data": [
                    {"id": "qwen/qwen3.6-27b", "active": True},
                    {"id": "allam-2-7b", "active": True},
                    {"id": "groq/compound", "active": True},
                    {"id": "llama-3.3-70b-versatile", "active": True},
                    {"id": "openai/gpt-oss-20b", "active": True},
                    {"id": "qwen/qwen3-vl-32b-instruct", "active": True},
                ]
            },
        )

    monkeypatch.setattr("pokemon_deal_bot.vision.httpx.get", fake_get)

    assert analyzer._candidate_models() == [
        "qwen/qwen3.6-27b",
        "qwen/qwen3-vl-32b-instruct",
    ]


def test_rate_limit_does_not_probe_text_only_models(monkeypatch):
    analyzer = LotVisionAnalyzer(
        api_key="secret-key",
        model="qwen/qwen3.6-27b",
        max_images=1,
        auto_discover_models=True,
        request_spacing_seconds=0,
    )
    post_models: list[str] = []

    def fake_get(*args, **kwargs):
        return _FakeResponse(
            200,
            {
                "data": [
                    {"id": "qwen/qwen3.6-27b", "active": True},
                    {"id": "allam-2-7b", "active": True},
                    {"id": "groq/compound", "active": True},
                    {"id": "openai/gpt-oss-20b", "active": True},
                ]
            },
        )

    def fake_post(url, **kwargs):
        post_models.append(kwargs["json"]["model"])
        return _FakeResponse(
            429,
            {
                "error": {
                    "code": "rate_limit_exceeded",
                    "message": "Rate limit reached on tokens per day",
                }
            },
        )

    monkeypatch.setattr("pokemon_deal_bot.vision.httpx.get", fake_get)
    monkeypatch.setattr("pokemon_deal_bot.vision.httpx.post", fake_post)

    try:
        analyzer._generate(_parts(analyzer))
    except VisionModelPoolExhaustedError:
        pass
    else:
        raise AssertionError("Expected the vision pool to be exhausted")

    assert post_models == ["qwen/qwen3.6-27b"]
