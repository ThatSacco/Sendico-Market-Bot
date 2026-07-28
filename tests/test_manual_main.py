from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pokemon_deal_bot.manual_main import (
    ManualScanRequest,
    build_runtime_config,
    build_watch_card,
    parse_search_terms,
    select_watchlist_target,
    validate_pricecharting_url,
)
from pokemon_deal_bot.models import WatchCard


def target(**overrides) -> WatchCard:
    values = {
        "id": "ampharos_ex_xy7_027",
        "active": True,
        "match_mode": "exact_card",
        "english_name": "Ampharos EX",
        "japanese_name": "デンリュウEX",
        "card_number": "027/081",
        "set_name": "Bandit Ring",
        "set_code": "XY7",
        "era_lot_search_terms": [
            "バンデットリング まとめ売り",
            "XY7 まとめ売り",
        ],
    }
    values.update(overrides)
    return WatchCard(**values)


def request(**overrides) -> ManualScanRequest:
    values = {
        "target": target(),
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


def write_watchlist(tmp_path: Path) -> Path:
    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text("{}\n", encoding="utf-8")
    (tmp_path / "data" / "watchlist.yaml").write_text(
        yaml.safe_dump(
            {
                "cards": [
                    {
                        "id": "ampharos_ex_xy7_027",
                        "active": True,
                        "match_mode": "exact_card",
                        "english_name": "Ampharos EX",
                        "japanese_name": "デンリュウEX",
                        "card_number": "027/081",
                        "set_name": "Bandit Ring",
                        "set_code": "XY7",
                        "era_lot_search_terms": [
                            "バンデットリング まとめ売り",
                            "XY7 まとめ売り",
                        ],
                    }
                ]
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return tmp_path / "config.yaml"


def test_parse_search_terms_accepts_lists_and_deduplicates() -> None:
    assert parse_search_terms(
        [
            "XY7 まとめ売り",
            " バンデットリング まとめ売り ",
            "XY7 まとめ売り",
        ]
    ) == ["XY7 まとめ売り", "バンデットリング まとめ売り"]


def test_pricecharting_requires_direct_product_page() -> None:
    validate_pricecharting_url(
        "https://www.pricecharting.com/game/"
        "pokemon-japanese-bandit-ring/ampharos-ex-27"
    )


def test_select_watchlist_target_uses_active_id(tmp_path: Path) -> None:
    config_path = write_watchlist(tmp_path)
    selected = select_watchlist_target(config_path, "ampharos_ex_xy7_027")
    assert selected.display_name == "Ampharos EX 027/081"
    assert selected.era_lot_search_terms == [
        "バンデットリング まとめ売り",
        "XY7 まとめ売り",
    ]


def test_missing_watchlist_id_lists_available_ids(tmp_path: Path) -> None:
    config_path = write_watchlist(tmp_path)
    with pytest.raises(ValueError, match="Available ids: ampharos_ex_xy7_027"):
        select_watchlist_target(config_path, "missing")


def test_watch_card_uses_selected_target_and_price_reference() -> None:
    selected = build_watch_card(request())
    assert selected.id == "ampharos_ex_xy7_027"
    assert selected.display_name == "Ampharos EX 027/081"
    assert selected.pricecharting_url.endswith("/ampharos-ex-27")


def test_request_rejects_missing_watchlist_search_terms() -> None:
    with pytest.raises(ValueError, match="has no era_lot_search_terms"):
        request(target=target(era_lot_search_terms=[]), search_terms=())


def test_request_rejects_more_than_four_watchlist_terms() -> None:
    terms = tuple(f"focused term {index}" for index in range(5))
    with pytest.raises(ValueError, match="use no more than 4"):
        request(search_terms=terms)


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
