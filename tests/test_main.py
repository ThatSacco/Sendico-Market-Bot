from pokemon_deal_bot.main import _merge_listing
from pokemon_deal_bot.models import SendicoListing


def test_merge_listing_enriches_direct_placeholder():
    existing = SendicoListing(
        code="m10381389468",
        url="https://sendico.com/shop/mercari/catalog/m10381389468",
        title="Direct test listing",
        price_yen=0,
    )
    found = SendicoListing(
        code="m10381389468",
        url=existing.url,
        title="Pokemon cards Sun & Moon R rarity bundle sale",
        price_yen=700,
        image_urls=["https://example.test/lot.webp"],
        raw_text="search result text",
    )

    merged = _merge_listing(existing, found)

    assert merged is existing
    assert merged.title == found.title
    assert merged.price_yen == 700
    assert merged.image_urls == found.image_urls
    assert merged.raw_text == found.raw_text


def test_candidate_relevance_prioritises_exact_watchlist_evidence():
    from pokemon_deal_bot.main import _candidate_relevance_score
    from pokemon_deal_bot.models import WatchCard

    target = WatchCard(
        id="ampharos",
        match_mode="exact_card",
        english_name="Ampharos EX",
        japanese_name="デンリュウEX",
        set_name="Bandit Ring",
        set_code="XY7",
        card_number="027/081",
        search_terms=["デンリュウEX 027/081"],
    )
    strong = SendicoListing(
        code="m1",
        url="https://example.test/m1",
        title="デンリュウEX 027/081 XY7",
        price_yen=1000,
    )
    unrelated = SendicoListing(
        code="m2",
        url="https://example.test/m2",
        title="Pikachu card sleeves",
        price_yen=1000,
    )

    assert _candidate_relevance_score(strong, [target]) >= 100
    assert _candidate_relevance_score(unrelated, [target]) == 0


def test_candidate_relevance_keeps_generic_lot_as_low_priority():
    from pokemon_deal_bot.main import _candidate_relevance_score
    from pokemon_deal_bot.models import WatchCard

    target = WatchCard(
        id="ampharos",
        match_mode="exact_card",
        english_name="Ampharos EX",
        card_number="027/081",
    )
    lot = SendicoListing(
        code="m3",
        url="https://example.test/m3",
        title="Japanese Pokemon collection lot",
        price_yen=1000,
    )
    assert _candidate_relevance_score(lot, [target]) == 5
