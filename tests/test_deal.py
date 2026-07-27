from datetime import date

from pokemon_deal_bot.deal import assess_deal, sendico_fee_jpy
from pokemon_deal_bot.fx import FxRates
from pokemon_deal_bot.models import CardPrice, IdentifiedCard, SendicoListing, VisionResult


def test_effective_fee():
    cfg = {"before_2026_08_01_jpy": 500, "from_2026_08_01_jpy": 800}
    assert sendico_fee_jpy(cfg, date(2026, 7, 31)) == 500
    assert sendico_fee_jpy(cfg, date(2026, 8, 1)) == 800


def test_qualifying_deal():
    listing = SendicoListing(
        code="m1",
        url="https://example.test/m1",
        title="Victini lot",
        price_yen=1000,
        seller_positive_ratings=500,
    )
    card = IdentifiedCard(
        name_en="Victini",
        name_jp="ビクティニ",
        set_name="Pokemon Japanese Black Bolt",
        set_code="sv11B",
        card_number="097/086",
        rarity="AR",
        language="Japanese",
        quantity=1,
        confidence=0.99,
        is_target=True,
    )
    price = CardPrice(card, 20.0, 30.0, "https://example.test", "Victini #97", 1.0)
    vision = VisionResult("lot", True, 0.99, [card], 0)
    assessment = assess_deal(
        listing,
        vision,
        [price],
        FxRates(1.5, 0.01, "test"),
        {"before_2026_08_01_jpy": 500, "from_2026_08_01_jpy": 800},
        20.0,
        301,
        0.85,
    )
    assert assessment.qualifies
    assert assessment.total_identified_value_aud == 30.0


def test_unverified_seller_is_provisional_only():
    listing = SendicoListing(
        code="m2",
        url="https://example.test/m2",
        title="Victini collection",
        price_yen=1000,
        seller_positive_ratings=None,
    )
    card = IdentifiedCard(
        name_en="Victini",
        name_jp="ビクティニ",
        set_name="Pokemon Japanese Black Bolt",
        set_code="sv11B",
        card_number="097/086",
        rarity="AR",
        language="Japanese",
        quantity=1,
        confidence=0.99,
        is_target=True,
    )
    price = CardPrice(card, 20.0, 30.0, "https://example.test", "Victini #97", 1.0)
    vision = VisionResult("lot", True, 0.99, [card], 0)
    assessment = assess_deal(
        listing,
        vision,
        [price],
        FxRates(1.5, 0.01, "test"),
        {"before_2026_08_01_jpy": 500, "from_2026_08_01_jpy": 800},
        20.0,
        301,
        0.85,
    )
    assert not assessment.qualifies
    assert assessment.provisional_qualifies
    assert assessment.requires_manual_seller_verification
    assert assessment.rejection_reasons == ["seller positive rating could not be verified"]


def test_verified_seller_below_threshold_is_not_provisional():
    listing = SendicoListing(
        code="m3",
        url="https://example.test/m3",
        title="Victini collection",
        price_yen=1000,
        seller_positive_ratings=300,
    )
    card = IdentifiedCard(
        name_en="Victini",
        name_jp="ビクティニ",
        set_name="Pokemon Japanese Black Bolt",
        set_code="sv11B",
        card_number="097/086",
        rarity="AR",
        language="Japanese",
        quantity=1,
        confidence=0.99,
        is_target=True,
    )
    price = CardPrice(card, 20.0, 30.0, "https://example.test", "Victini #97", 1.0)
    vision = VisionResult("lot", True, 0.99, [card], 0)
    assessment = assess_deal(
        listing,
        vision,
        [price],
        FxRates(1.5, 0.01, "test"),
        {"before_2026_08_01_jpy": 500, "from_2026_08_01_jpy": 800},
        20.0,
        301,
        0.85,
    )
    assert not assessment.qualifies
    assert not assessment.provisional_qualifies
