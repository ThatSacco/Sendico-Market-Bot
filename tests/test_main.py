from pokemon_deal_bot.main import (
    _candidate_relevance_score,
    _has_strong_lot_evidence,
    _merge_listing,
    _rank_candidate_pool,
)
from pokemon_deal_bot.models import SendicoListing, WatchCard


def _target() -> WatchCard:
    return WatchCard(
        id="ampharos",
        match_mode="exact_card",
        english_name="Ampharos EX",
        japanese_name="デンリュウEX",
        set_name="Bandit Ring",
        set_code="XY7",
        card_number="027/081",
        search_terms=["デンリュウEX 027/081"],
        lot_search_terms=["デンリュウ まとめ"],
    )


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
    target = _target()
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


def test_candidate_relevance_boosts_pokemon_name_plus_lot_marker():
    target = _target()
    name_only = SendicoListing(
        code="m1",
        url="https://example.test/m1",
        title="デンリュウ ポケモンカード",
        price_yen=1000,
    )
    named_lot = SendicoListing(
        code="m2",
        url="https://example.test/m2",
        title="デンリュウ ポケモンカード まとめ",
        price_yen=1000,
    )
    assert _candidate_relevance_score(named_lot, [target]) > _candidate_relevance_score(
        name_only,
        [target],
    )


def test_candidate_relevance_keeps_generic_lot_as_low_priority():
    lot = SendicoListing(
        code="m3",
        url="https://example.test/m3",
        title="Japanese Pokemon collection lot",
        price_yen=1000,
    )
    assert _candidate_relevance_score(lot, [_target()]) == 5


def test_rank_candidate_pool_places_tier2_after_exact_results():
    exact = SendicoListing(
        code="exact",
        url="https://example.test/exact",
        title="デンリュウEX 027/081 XY7",
        price_yen=1000,
    )
    named_lot = SendicoListing(
        code="named-lot",
        url="https://example.test/named-lot",
        title="デンリュウ まとめ",
        price_yen=2000,
    )
    query_only = SendicoListing(
        code="query-only",
        url="https://example.test/query-only",
        title="Pokemon cards assorted sale",
        price_yen=3000,
    )
    selected, filtered, era_selected, generic_selected = _rank_candidate_pool(
        {
            exact.code: exact,
            named_lot.code: named_lot,
            query_only.code: query_only,
        },
        {
            exact.code: {"watchlist"},
            named_lot.code: {"tier2_generic"},
            query_only.code: {"tier2_generic"},
        },
        [_target()],
        direct_codes=set(),
        prefilter_enabled=True,
        allow_tier2_query_only=True,
    )

    assert [listing.code for listing in selected] == [
        "exact",
        "named-lot",
        "query-only",
    ]
    assert filtered == 0
    assert era_selected == 0
    assert generic_selected == 2


def test_rank_candidate_pool_can_reject_query_only_tier2_results():
    query_only = SendicoListing(
        code="query-only",
        url="https://example.test/query-only",
        title="Pikachu card sleeves",
        price_yen=1000,
    )
    selected, filtered, era_selected, generic_selected = _rank_candidate_pool(
        {query_only.code: query_only},
        {query_only.code: {"tier2_generic"}},
        [_target()],
        direct_codes=set(),
        prefilter_enabled=True,
        allow_tier2_query_only=False,
    )

    assert selected == []
    assert filtered == 1
    assert era_selected == 0
    assert generic_selected == 0


def test_listing_found_by_exact_and_tier2_is_not_tier2_only():
    listing = SendicoListing(
        code="duplicate",
        url="https://example.test/duplicate",
        title="デンリュウEX 027/081 まとめ",
        price_yen=1000,
    )
    selected, filtered, era_selected, generic_selected = _rank_candidate_pool(
        {listing.code: listing},
        {listing.code: {"watchlist", "tier2_era"}},
        [_target()],
        direct_codes=set(),
        prefilter_enabled=True,
        allow_tier2_query_only=True,
    )

    assert [item.code for item in selected] == ["duplicate"]
    assert filtered == 0
    assert era_selected == 0
    assert generic_selected == 0


def test_rank_candidate_pool_places_era_lots_before_generic_lots():
    era = SendicoListing(
        code="era",
        url="https://example.test/era",
        title="XY7 Pokemon cards まとめ売り",
        price_yen=2000,
    )
    generic = SendicoListing(
        code="generic",
        url="https://example.test/generic",
        title="Pokemon cards まとめ売り",
        price_yen=2000,
    )
    selected, filtered, era_selected, generic_selected = _rank_candidate_pool(
        {era.code: era, generic.code: generic},
        {era.code: {"tier2_era"}, generic.code: {"tier2_generic"}},
        [_target()],
        direct_codes=set(),
        prefilter_enabled=True,
        allow_tier2_query_only=True,
    )
    assert [item.code for item in selected] == ["era", "generic"]
    assert filtered == 0
    assert era_selected == 1
    assert generic_selected == 1


def test_strong_lot_evidence_accepts_multi_card_language():
    listing = SendicoListing(
        code="lot",
        url="https://example.test/lot",
        title="ポケモンカード XY まとめ売り",
        price_yen=5000,
    )
    assert _has_strong_lot_evidence(listing)


def test_strong_lot_evidence_accepts_explicit_card_count():
    listing = SendicoListing(
        code="counted",
        url="https://example.test/counted",
        title="Pokemon cards 25 cards",
        price_yen=5000,
    )
    assert _has_strong_lot_evidence(listing)


def test_strong_lot_evidence_rejects_single_card_set_wording():
    listing = SendicoListing(
        code="single",
        url="https://example.test/single",
        title="デンリュウEX XY7 セット",
        description="カード1枚です",
        price_yen=1500,
    )
    assert not _has_strong_lot_evidence(listing)
