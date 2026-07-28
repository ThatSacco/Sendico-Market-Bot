from pokemon_deal_bot.discord import build_test_embed
from pokemon_deal_bot.models import DealAssessment, SendicoListing, VisionResult


def test_test_embed_shows_lot_value_sendico_cost_and_variance():
    listing = SendicoListing(
        code="m1",
        url="https://example.test/m1",
        title="Test lot",
        price_yen=700,
    )
    assessment = DealAssessment(
        listing=listing,
        vision=VisionResult("lot", False, 0.0, [], 0),
        priced_cards=[],
        acquisition_cost_aud=15.30,
        listing_price_aud=7.14,
        sendico_fee_aud=8.16,
        total_identified_value_aud=42.50,
        price_variance_aud=27.20,
        price_variance_percent=177.78,
        qualifies=False,
    )
    embed = build_test_embed(assessment)
    comparison = next(
        field for field in embed["fields"]
        if field["name"] == "Lot value and variance"
    )
    assert "A$42.50" in comparison["value"]
    assert "A$15.30" in comparison["value"]
    assert "¥800 fee" in comparison["value"]
    assert "+A$27.20" in comparison["value"]


def test_test_embed_shows_normal_holo_variant_label():
    from pokemon_deal_bot.models import CardPrice, IdentifiedCard

    listing = SendicoListing(
        code="m2",
        url="https://example.test/m2",
        title="Variant test",
        price_yen=1000,
    )
    card = IdentifiedCard(
        name_en="Victini",
        name_jp="ビクティニ",
        set_name="Black Bolt",
        set_code="sv11B",
        card_number="012/086",
        rarity="C",
        language="Japanese",
        quantity=1,
        confidence=0.95,
        variant="normal_holo",
    )
    assessment = DealAssessment(
        listing=listing,
        vision=VisionResult("single", False, 0.0, [card], 0),
        priced_cards=[CardPrice(card, 2.0, 3.0, "url", "title", 1.0)],
        acquisition_cost_aud=18.0,
        listing_price_aud=10.0,
        sendico_fee_aud=8.0,
        total_identified_value_aud=3.0,
        price_variance_aud=-15.0,
        price_variance_percent=-83.3,
        qualifies=False,
    )
    embed = build_test_embed(assessment)
    prices = next(field for field in embed["fields"] if field["name"].startswith("Cards matched"))
    assert "Normal/Holo" in prices["value"]


def test_test_embed_lists_matched_watchlist_ids():
    from pokemon_deal_bot.models import IdentifiedCard

    listing = SendicoListing(
        code="m3",
        url="https://example.test/m3",
        title="Tyranitar test",
        price_yen=1000,
    )
    card = IdentifiedCard(
        name_en="Tyranitar",
        name_jp="バンギラス",
        set_name="Neo Discovery",
        set_code=None,
        card_number="12/75",
        rarity="Rare",
        language="Japanese",
        quantity=1,
        confidence=0.98,
        is_target=True,
        matched_watchlist_ids=["tyranitar_neo_era"],
    )
    assessment = DealAssessment(
        listing=listing,
        vision=VisionResult(
            "single",
            True,
            0.98,
            [card],
            0,
            matched_watchlist_ids=["tyranitar_neo_era"],
        ),
        priced_cards=[],
        acquisition_cost_aud=18.0,
        listing_price_aud=10.0,
        sendico_fee_aud=8.0,
        total_identified_value_aud=0.0,
        price_variance_aud=-18.0,
        price_variance_percent=-100.0,
        qualifies=False,
    )
    embed = build_test_embed(assessment)
    field = next(item for item in embed["fields"] if item["name"] == "Matched watchlist")
    assert "tyranitar_neo_era" in field["value"]


def test_priced_card_includes_clickable_pricecharting_source():
    from pokemon_deal_bot.discord import build_embed
    from pokemon_deal_bot.models import CardPrice, IdentifiedCard

    source_url = (
        "https://www.pricecharting.com/game/"
        "pokemon-japanese-bandit-ring/ampharos-ex-27"
    )
    listing = SendicoListing(
        code="m4",
        url="https://example.test/m4",
        title="Ampharos test",
        price_yen=1000,
        seller_positive_ratings=500,
    )
    card = IdentifiedCard(
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
        priced_cards=[CardPrice(card, 12.0, 18.0, source_url, "title", 1.0)],
        acquisition_cost_aud=15.0,
        listing_price_aud=7.0,
        sendico_fee_aud=8.0,
        total_identified_value_aud=18.0,
        price_variance_aud=3.0,
        price_variance_percent=20.0,
        qualifies=True,
    )

    embed = build_embed(assessment)
    prices = next(
        field for field in embed["fields"]
        if field["name"] == "Cards priced at ≥95% match"
    )
    assert f"[PriceCharting]({source_url})" in prices["value"]


def test_scan_summary_reports_zero_alert_completed_run():
    from pokemon_deal_bot.discord import build_scan_summary_embed

    embed = build_scan_summary_embed(
        discovered=68,
        prefiltered_out=58,
        hydrated=10,
        unchanged_skipped=2,
        seller_filtered=1,
        analysed=7,
        assessments=7,
        strict_matches=0,
        provisional_matches=0,
        alerts_sent=0,
        errors=0,
        vision_requests=7,
        vision_models="gemini-3.6-flash (7)",
        vision_usage="input 1,000; output 200; thinking 50; total 1,250 tokens",
        stop_reason=None,
    )

    assert embed["title"] == "SENDICO SCAN COMPLETED"
    results = next(field for field in embed["fields"] if field["name"] == "Results")
    assert "Deal alerts sent: **0**" in results["value"]


def test_scan_summary_marks_gemini_capacity_pause():
    from pokemon_deal_bot.discord import build_scan_summary_embed

    embed = build_scan_summary_embed(
        discovered=10,
        prefiltered_out=0,
        hydrated=1,
        unchanged_skipped=0,
        seller_filtered=0,
        analysed=1,
        assessments=0,
        strict_matches=0,
        provisional_matches=0,
        alerts_sent=0,
        errors=0,
        vision_requests=1,
        vision_models="gemini-3.6-flash (1)",
        vision_usage="input 100; output 20; thinking 5; total 125 tokens",
        stop_reason="Gemini capacity or rate limit reached",
    )
    assert embed["title"] == "SENDICO SCAN PAUSED"
    assert "Gemini capacity" in embed["description"]
