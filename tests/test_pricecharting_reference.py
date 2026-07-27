from pathlib import Path

from pokemon_deal_bot.fx import FxRates
from pokemon_deal_bot.models import IdentifiedCard, WatchCard
from pokemon_deal_bot.pricecharting import PriceChartingClient


DIRECT_URL = (
    "https://www.pricecharting.com/game/"
    "pokemon-japanese-bandit-ring/ampharos-ex-27"
)
FALLBACK_URL = (
    "https://www.pricecharting.com/game/"
    "pokemon-japanese-bandit-ring/ampharos-ex-27?fallback=1"
)
MATCHING_TITLE = "Ampharos EX #27 Prices | Pokemon Japanese Bandit Ring"


def _client(tmp_path: Path) -> PriceChartingClient:
    (tmp_path / "data").mkdir()
    return PriceChartingClient(
        root=tmp_path,
        fx=FxRates(usd_to_aud=1.5, jpy_to_aud=0.01, source="test"),
        request_delay_seconds=0,
        cache_hours=12,
        minimum_match_confidence=0.95,
    )


def _card() -> IdentifiedCard:
    return IdentifiedCard(
        name_en="Ampharos EX",
        name_jp="デンリュウEX",
        set_name="Bandit Ring",
        set_code="XY7",
        card_number="027/081",
        rarity="RR",
        language="Japanese",
        quantity=1,
        confidence=0.99,
        is_target=True,
        matched_watchlist_ids=["ampharos"],
    )


def _target() -> WatchCard:
    return WatchCard(
        id="ampharos",
        match_mode="exact_card",
        english_name="Ampharos EX",
        japanese_name="デンリュウEX",
        set_name="Bandit Ring",
        set_code="XY7",
        card_number="027/081",
        pricecharting_url=DIRECT_URL,
    )


def test_direct_watchlist_reference_is_used_before_search(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls: list[str] = []

    def fetch(url: str, price_tier: str = "Ungraded"):
        calls.append(url)
        return 12.0, MATCHING_TITLE, price_tier

    monkeypatch.setattr(client, "_fetch_product", fetch)
    monkeypatch.setattr(
        client,
        "_find_product_url",
        lambda card: (_ for _ in ()).throw(AssertionError("search not expected")),
    )

    result = client.price_card(_card(), _target())
    client.client.close()

    assert result is not None
    assert calls == [DIRECT_URL]
    assert result.source_url == DIRECT_URL
    assert result.unit_price_aud == 18.0
    assert result.match_confidence == 1.0


def test_invalid_direct_page_identity_falls_back_to_search(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls: list[str] = []

    def fetch(url: str, price_tier: str = "Ungraded"):
        calls.append(url)
        if url == DIRECT_URL:
            return 50.0, "Victini #97 Prices | Pokemon Japanese Black Bolt", price_tier
        return 12.0, MATCHING_TITLE, price_tier

    monkeypatch.setattr(client, "_fetch_product", fetch)
    monkeypatch.setattr(client, "_find_product_url", lambda card: (FALLBACK_URL, 1.0))

    result = client.price_card(_card(), _target())
    client.client.close()

    assert result is not None
    assert calls == [DIRECT_URL, FALLBACK_URL]
    assert result.source_url == FALLBACK_URL
    assert result.unit_price_aud == 18.0


def test_unavailable_direct_page_falls_back_to_search(tmp_path, monkeypatch):
    client = _client(tmp_path)
    calls: list[str] = []

    def fetch(url: str, price_tier: str = "Ungraded"):
        calls.append(url)
        if url == DIRECT_URL:
            return None
        return 12.0, MATCHING_TITLE, price_tier

    monkeypatch.setattr(client, "_fetch_product", fetch)
    monkeypatch.setattr(client, "_find_product_url", lambda card: (FALLBACK_URL, 1.0))

    result = client.price_card(_card(), _target())
    client.client.close()

    assert result is not None
    assert calls == [DIRECT_URL, FALLBACK_URL]
    assert result.source_url == FALLBACK_URL


def test_reference_is_not_used_for_unmatched_card(tmp_path, monkeypatch):
    client = _client(tmp_path)
    card = _card()
    card.matched_watchlist_ids = []
    calls: list[str] = []

    def fetch(url: str, price_tier: str = "Ungraded"):
        calls.append(url)
        return 12.0, MATCHING_TITLE, price_tier

    monkeypatch.setattr(client, "_fetch_product", fetch)
    monkeypatch.setattr(client, "_find_product_url", lambda card: (FALLBACK_URL, 1.0))

    result = client.price_card(card, _target())
    client.client.close()

    assert result is not None
    assert calls == [FALLBACK_URL]
    assert result.source_url == FALLBACK_URL
