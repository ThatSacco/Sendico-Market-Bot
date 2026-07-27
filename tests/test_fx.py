from pokemon_deal_bot.fx import FxClient


def test_fx_uses_current_frankfurter_endpoint(monkeypatch):
    captured = {}

    class FakeResponse:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"rates": {"AUD": 1.5, "JPY": 150.0}}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("pokemon_deal_bot.fx.httpx.get", fake_get)
    rates = FxClient(1.52, 0.0102).get_rates()

    assert captured["url"] == "https://api.frankfurter.dev/v1/latest"
    assert captured["params"] == {"base": "USD", "symbols": "AUD,JPY"}
    assert captured["follow_redirects"] is True
    assert rates.usd_to_aud == 1.5
    assert rates.jpy_to_aud == 0.01
