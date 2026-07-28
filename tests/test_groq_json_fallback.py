from __future__ import annotations

from pokemon_deal_bot.vision import LotVisionAnalyzer


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.is_error = status_code >= 400
        self.text = str(payload)

    def json(self) -> dict:
        return self._payload


def _parts(analyzer: LotVisionAnalyzer) -> list[dict]:
    return [
        {"text": "Return JSON only"},
        analyzer._inline_part("image/jpeg", b"test-image"),
    ]


def test_failed_generation_retries_without_json_mode_and_caches_fallback(
    monkeypatch,
):
    analyzer = LotVisionAnalyzer(
        api_key="secret-key",
        model="qwen/qwen3.6-27b",
        max_images=1,
        auto_discover_models=False,
        request_spacing_seconds=0,
    )
    payloads: list[dict] = []

    def fake_post(url, **kwargs):
        payload = kwargs["json"]
        payloads.append(payload)
        if len(payloads) == 1:
            return _FakeResponse(
                400,
                {
                    "error": {
                        "message": (
                            "Failed to validate JSON. Please adjust your prompt. "
                            "See 'failed_generation' for more details."
                        ),
                        "code": "invalid_request_error",
                        "failed_generation": "{not-valid-json}",
                    }
                },
            )
        return _FakeResponse(
            200,
            {
                "choices": [
                    {"message": {"content": '```json\n{"cards":[]}\n```'}}
                ]
            },
        )

    monkeypatch.setattr("pokemon_deal_bot.vision.httpx.post", fake_post)

    first = analyzer._generate(_parts(analyzer))
    second = analyzer._generate(_parts(analyzer))

    assert first == {"cards": []}
    assert second == {"cards": []}
    assert payloads[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in payloads[1]
    # The failure is remembered for the remainder of the run, so the next
    # request skips the response_format attempt rather than repeating the 400.
    assert "response_format" not in payloads[2]
    assert "qwen/qwen3.6-27b" in analyzer._json_mode_disabled_models


def test_failed_to_validate_json_is_classified_as_json_mode_error():
    assert LotVisionAnalyzer._is_json_mode_error(
        400,
        "Failed to validate JSON. See 'failed_generation' for more details.",
    )
