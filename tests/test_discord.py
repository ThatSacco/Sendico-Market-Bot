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
