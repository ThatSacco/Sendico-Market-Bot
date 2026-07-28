from pathlib import Path

from pokemon_deal_bot.discord import build_embed
from pokemon_deal_bot.fx import FxRates
from pokemon_deal_bot.models import (
    CardPrice,
    DealAssessment,
    IdentifiedCard,
    SendicoListing,
    VisionResult,
    WatchCard,
)
from pokemon_deal_bot.pricecharting import (
    PriceChartingClient,
    parse_price_guide_usd,
    price_tier_for_card,
)
from pokemon_deal_bot.vision import (
    _apply_listing_grading_hint,
    _merge_cards,
    _propagate_visible_grading,
    parse_vision_result,
)


DIRECT_URL = (
    "https://www.pricecharting.com/game/"
    "pokemon-japanese-bandit-ring/ampharos-ex-27"
)
MATCHING_TITLE = "Ampharos EX #27 Prices | Pokemon Japanese Bandit Ring"


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


def _card(**changes) -> IdentifiedCard:
    values = dict(
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
    values.update(changes)
    return IdentifiedCard(**values)


def test_price_guide_parses_ungraded_grade_9_and_psa_10():
    html = """
    <html><body>
      <table id="price_data">
        <tr><th>Ungraded</th><th>Grade 9</th><th>PSA 10</th></tr>
        <tr><td>$7.44</td><td>$24.48</td><td>$62.39</td></tr>
      </table>
    </body></html>
    """
    assert parse_price_guide_usd(html) == {
        "Ungraded": 7.44,
        "Grade 9": 24.48,
        "PSA 10": 62.39,
    }


def test_vision_retains_image_confirmed_psa_grade():
    result = parse_vision_result(
        {
            "cards": [
                {
                    "name_en": "Ampharos EX",
                    "name_jp": "デンリュウEX",
                    "set_name": "Bandit Ring",
                    "set_code": "XY7",
                    "card_number": "027/081",
                    "language": "Japanese",
                    "confidence": 0.99,
                    "grading_company": "PSA",
                    "grade": "10",
                    "grading_confidence": 0.98,
                }
            ]
        },
        [_target()],
    )
    card = result.cards[0]
    assert card.is_graded
    assert card.grade_label == "PSA 10"
    assert card.grading_source == "image"
    assert price_tier_for_card(card) == "PSA 10"


def test_explicit_listing_title_applies_claimed_psa10_to_matching_card():
    listing = SendicoListing(
        code="m24075102942",
        url="https://sendico.com/shop/mercari/catalog/m24075102942",
        title="Ampharos EX RR PSA10 XY7 Bandit Ring 027/081 1ED",
        price_yen=15000,
    )
    updated, changed = _apply_listing_grading_hint([_card()], listing)
    assert changed
    assert updated[0].grade_label == "PSA 10"
    assert updated[0].grading_source == "listing_title"


def test_image_confirmed_grade_propagates_to_alternate_raw_crop_and_merges_once():
    slab = _card(
        grading_company="PSA",
        grade="10",
        grading_confidence=0.99,
        grading_source="image",
        evidence_image_indexes=[1],
    )
    inner_card = _card(evidence_image_indexes=[2])
    propagated = _propagate_visible_grading([slab, inner_card])
    merged = _merge_cards(propagated)
    assert len(merged) == 1
    assert merged[0].quantity == 1
    assert merged[0].grade_label == "PSA 10"


def test_psa10_card_requests_psa10_price_tier(tmp_path: Path, monkeypatch):
    (tmp_path / "data").mkdir()
    client = PriceChartingClient(
        root=tmp_path,
        fx=FxRates(usd_to_aud=1.5, jpy_to_aud=0.01, source="test"),
        request_delay_seconds=0,
        cache_hours=12,
        minimum_match_confidence=0.95,
    )
    calls: list[tuple[str, str]] = []

    def fetch(url: str, tier: str = "Ungraded"):
        calls.append((url, tier))
        return 62.39, MATCHING_TITLE, tier

    monkeypatch.setattr(client, "_fetch_product", fetch)
    card = _card(
        grading_company="PSA",
        grade="10",
        grading_confidence=0.9,
        grading_source="listing_title",
    )
    result = client.price_card(card, _target())
    client.client.close()

    assert result is not None
    assert calls == [(DIRECT_URL, "PSA 10")]
    assert result.price_tier == "PSA 10"
    assert result.unit_price_aud == 62.39 * 1.5


def test_non_psa_grade_10_is_not_valued_as_psa10(tmp_path: Path, monkeypatch):
    (tmp_path / "data").mkdir()
    client = PriceChartingClient(
        root=tmp_path,
        fx=FxRates(usd_to_aud=1.5, jpy_to_aud=0.01, source="test"),
        request_delay_seconds=0,
        cache_hours=12,
        minimum_match_confidence=0.95,
    )
    monkeypatch.setattr(
        client,
        "_find_product_url",
        lambda card: (_ for _ in ()).throw(AssertionError("search not expected")),
    )
    card = _card(grading_company="CGC", grade="10", grading_source="image")
    assert client.price_card(card, _target()) is None
    client.client.close()


def test_discord_shows_claimed_grade_and_price_tier():
    listing = SendicoListing(
        code="m24075102942",
        url="https://sendico.com/shop/mercari/catalog/m24075102942",
        title="Ampharos EX RR PSA10 XY7 Bandit Ring 027/081",
        price_yen=15000,
        seller_positive_ratings=None,
    )
    card = _card(
        grading_company="PSA",
        grade="10",
        grading_confidence=0.9,
        grading_source="listing_title",
    )
    priced = CardPrice(
        card=card,
        unit_price_usd=62.39,
        unit_price_aud=93.59,
        source_url=DIRECT_URL,
        source_title=MATCHING_TITLE,
        match_confidence=1.0,
        price_tier="PSA 10",
    )
    assessment = DealAssessment(
        listing=listing,
        vision=VisionResult(
            "single",
            True,
            0.99,
            [card],
            0,
            matched_watchlist_ids=["ampharos"],
        ),
        priced_cards=[priced],
        acquisition_cost_aud=161.16,
        listing_price_aud=153.0,
        sendico_fee_aud=8.16,
        total_identified_value_aud=93.59,
        price_variance_aud=-67.57,
        price_variance_percent=-41.9,
        qualifies=False,
        rejection_reasons=["seller positive rating could not be verified"],
    )
    embed = build_embed(assessment)
    prices = next(
        field for field in embed["fields"]
        if field["name"] == "Cards priced at ≥95% match"
    )
    assert "PSA 10 claimed" in prices["value"]
    assert "; PSA 10)" in prices["value"]
