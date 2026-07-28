from __future__ import annotations

from pokemon_deal_bot.manual_main import (
    ManualScanRequest,
    build_runtime_config,
    build_watch_card,
    parse_search_terms,
    validate_pricecharting_url,
)


def request(**overrides):
    values = {
        "target_name": "Ampharos EX",
        "japanese_name": "デンリュウEX",
        "card_number": "027/081",
        "set_name": "Bandit Ring",
        "set_code": "XY7",
        "pricecharting_url": (
            "https://www.pricecharting.com/game/"
            "pokemon-japanese-bandit-ring/ampharos-ex-27"
        ),
        "search_terms": (
            "バンデットリング まとめ売り",
            "XY7 まとめ売り",
        ),
        "results_per_term": 15,
        "screening_limit": 15,
        "detailed_limit": 3,
    }
    values.update(overrides)
    return ManualScanRequest(**values).validated()


def test_parse_search_terms_accepts_commas_newlines_and_deduplicates() -> None:
    assert parse_search_terms(
        "XY7 まとめ売り, バンデットリング まとめ売り\nXY7 まとめ売り"
    ) == ["XY7 まとめ売り", "バンデットリング まとめ売り"]


def test_pricecharting_requires_direct_product_page() -> None:
    validate_pricecharting_url(
        "https://www.pricecharting.com/game/"
        "pokemon-japanese-bandit-ring/ampharos-ex-27"
    )


def test_watch_card_contains_exact_target_and_price_reference() -> None:
    target = build_watch_card(request())
    assert target.search_terms == []
    assert target.display_name == "Ampharos EX 027/081"
    assert target.pricecharting_url.endswith("/ampharos-ex-27")


def test_runtime_config_has_conservative_hard_limits() -> None:
    config = build_runtime_config(
        {
            "sendico": {"tier2_lot_search": {}},
            "vision": {},
            "discord": {},
            "test_mode": {},
        },
        request(),
    )
    sendico = config["sendico"]
    tier2 = sendico["tier2_lot_search"]
    vision = config["vision"]

    assert sendico["maximum_scroll_rounds"] == 5
    assert sendico["search_link_stop_limit"] == 30
    assert sendico["max_listings_per_run"] == 30
    assert tier2["max_results_per_search"] == 15
    assert tier2["max_screenings_per_run"] == 15
    assert tier2["generic_screening_limit"] == 0
    assert tier2["max_detailed_analyses_per_run"] == 3
    assert tier2["screening_max_overview_images"] == 3
    assert vision["max_vision_requests_per_run"] <= 40
    assert vision["max_images_per_listing"] == 8
