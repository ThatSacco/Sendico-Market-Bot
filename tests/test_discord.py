from pokemon_deal_bot.discord import build_embed
from pokemon_deal_bot.models import CardPrice, DealAssessment, IdentifiedCard, SendicoListing, VisionResult


def test_provisional_embed_is_clearly_marked():
    listing = SendicoListing(
        code="m1",
        url="https://example.test/m1",
        title="Victini lot",
        price_yen=1000,
        seller_positive_ratings=None,
    )
    card = IdentifiedCard(
        name_en="Victini",
        name_jp="ビクティニ",
        set_name="Black Bolt",
        set_code="sv11B",
        card_number="097/086",
        rarity="AR",
        language="Japanese",
        quantity=1,
        confidence=0.99,
        is_target=True,
    )
    assessment = DealAssessment(
        listing=listing,
        vision=VisionResult("lot", True, 0.99, [card], 0),
        priced_cards=[CardPrice(card, 20.0, 30.0, "url", "title", 1.0)],
        acquisition_cost_aud=15.0,
        listing_price_aud=10.0,
        sendico_fee_aud=5.0,
        total_identified_value_aud=30.0,
        saving_aud=15.0,
        saving_percent=50.0,
        qualifies=False,
        provisional_qualifies=True,
        requires_manual_seller_verification=True,
        rejection_reasons=["seller positive rating could not be verified"],
    )
    embed = build_embed(assessment)
    assert embed["title"].startswith("MANUAL SELLER CHECK")
    assert embed["color"] == 0xF1C40F
    seller_field = next(field for field in embed["fields"] if field["name"] == "Seller positives")
    assert "301" in seller_field["value"]
