from types import SimpleNamespace

from pokemon_deal_bot.models import WatchCard
from pokemon_deal_bot.updated_main import (
    candidate_relevance_score,
    extract_seller_description,
    strong_lot_evidence,
)


def test_description_extraction_excludes_recommendations():
    body = """
    Ampharos listing
    Item Description
    XY7 cards sold together, 20 cards
    Seller
    Great seller
    Recommended
    Pokemon card bulk collection
    """
    assert extract_seller_description(body, "Ampharos listing") == (
        "XY7 cards sold together, 20 cards"
    )


def test_lot_evidence_does_not_use_raw_page_boilerplate():
    listing = SimpleNamespace(
        title="Ampharos EX 027/081",
        description="",
        raw_text="Recommended Pokemon bundle collection",
    )
    assert strong_lot_evidence(listing) is False


def test_title_confirmed_lot_ranks_above_single_card():
    target = WatchCard(
        id="ampharos",
        match_mode="exact_card",
        english_name="Ampharos EX",
        japanese_name="デンリュウEX",
        set_code="XY7",
        card_number="027/081",
        searches=[{"term": "XY7 まとめ売り", "mode": "focused_lot"}],
    )
    lot = SimpleNamespace(
        title="XY7 まとめ売り 20枚",
        description="20枚セット",
        raw_text="XY7",
    )
    single = SimpleNamespace(
        title="デンリュウEX 027/081 XY7",
        description="",
        raw_text="デンリュウEX 027/081",
    )
    assert candidate_relevance_score(lot, [target]) > candidate_relevance_score(single, [target])
