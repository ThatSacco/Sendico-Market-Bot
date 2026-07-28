from pathlib import Path

import pytest
import yaml

from pokemon_deal_bot.config import (
    AppConfig,
    load_config,
    load_run_limits,
    load_watchlist,
    validate_run_limits,
    validate_watchlist_for_run,
    watchlist_era_lot_search_terms,
    watchlist_generic_lot_search_terms,
    watchlist_lot_search_terms,
    watchlist_search_terms,
    watchlist_signature,
)
from pokemon_deal_bot.models import WatchCard, WatchSearch, normalize_card_number


def _exact_card(**overrides):
    values = {
        "id": "ampharos",
        "match_mode": "exact_card",
        "english_name": "Ampharos EX",
        "card_number": "027/081",
        "pricecharting_url": (
            "https://www.pricecharting.com/game/"
            "pokemon-japanese-bandit-ring/ampharos-ex-27"
        ),
        "searches": [
            {"term": "XY7 まとめ売り", "mode": "focused_lot", "active": True}
        ],
    }
    values.update(overrides)
    return WatchCard(**values)


def test_unified_searches_split_by_mode():
    card = _exact_card(
        searches=[
            {"term": "デンリュウEX 027/081", "mode": "exact", "active": True},
            {"term": "XY7 まとめ売り", "mode": "focused_lot", "active": True},
            {"term": "ポケカ まとめ売り", "mode": "generic_lot", "active": False},
        ]
    )
    assert watchlist_search_terms([card]) == ["デンリュウEX 027/081"]
    assert watchlist_era_lot_search_terms([card]) == ["XY7 まとめ売り"]
    assert watchlist_generic_lot_search_terms([card]) == []
    assert watchlist_lot_search_terms([card]) == ["XY7 まとめ売り"]


def test_search_terms_are_never_generated_from_names():
    card = WatchCard(
        id="tyranitar",
        match_mode="pokemon_general",
        english_names=["Tyranitar"],
        japanese_names=["バンギラス"],
    )
    assert watchlist_search_terms([card]) == []
    assert watchlist_lot_search_terms([card]) == []


def test_legacy_constructor_fields_remain_compatible():
    card = WatchCard(
        id="legacy",
        match_mode="exact_card",
        english_name="Ampharos EX",
        card_number="027/081",
        search_terms=["デンリュウEX 027/081"],
        era_lot_search_terms=["XY7 まとめ売り"],
    )
    assert [(item.term, item.mode) for item in card.active_searches] == [
        ("デンリュウEX 027/081", "exact"),
        ("XY7 まとめ売り", "focused_lot"),
    ]


def test_watch_search_rejects_unknown_mode():
    with pytest.raises(ValueError, match="Unsupported watchlist search mode"):
        WatchSearch(term="anything", mode="wide")


def test_run_validation_requires_searches_and_pricecharting():
    no_search = _exact_card(searches=[])
    with pytest.raises(ValueError, match="no active searches"):
        validate_watchlist_for_run([no_search])

    no_price = _exact_card(pricecharting_url=None)
    with pytest.raises(ValueError, match="requires pricecharting_url"):
        validate_watchlist_for_run([no_price])


def test_run_validation_limits_each_card_to_four_active_searches():
    card = _exact_card(
        searches=[
            {"term": f"focused {index}", "mode": "focused_lot", "active": True}
            for index in range(5)
        ]
    )
    with pytest.raises(ValueError, match="maximum is 4"):
        validate_watchlist_for_run([card])


def test_exact_card_requires_a_card_number():
    with pytest.raises(ValueError, match="requires card_number"):
        WatchCard(id="invalid", match_mode="exact_card", english_name="Ampharos EX")


def test_card_number_normalisation_ignores_leading_zeroes():
    assert normalize_card_number("027/081") == "27/81"
    assert normalize_card_number("27 / 81") == "27/81"


def test_watchlist_signature_changes_when_search_changes():
    first = _exact_card(searches=[{"term": "XY7 まとめ売り", "mode": "focused_lot"}])
    second = _exact_card(searches=[{"term": "バンデットリング まとめ売り", "mode": "focused_lot"}])
    assert watchlist_signature([first]) != watchlist_signature([second])


def test_pricecharting_reference_validation():
    assert _exact_card().pricecharting_url.endswith("/ampharos-ex-27")
    with pytest.raises(ValueError, match="invalid pricecharting_url"):
        _exact_card(pricecharting_url="https://example.com/game/ampharos")
    with pytest.raises(ValueError, match="must point to a PriceCharting /game/"):
        _exact_card(pricecharting_url="https://www.pricecharting.com/search-products?q=x")


def test_load_watchlist_supports_unified_searches(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "watchlist.yaml").write_text(
        yaml.safe_dump(
            {
                "cards": [
                    {
                        "id": "ampharos",
                        "active": True,
                        "match_mode": "exact_card",
                        "english_name": "Ampharos EX",
                        "card_number": "027/081",
                        "pricecharting_url": (
                            "https://www.pricecharting.com/game/"
                            "pokemon-japanese-bandit-ring/ampharos-ex-27"
                        ),
                        "searches": [
                            {
                                "term": "XY7 まとめ売り",
                                "mode": "focused_lot",
                                "active": True,
                            }
                        ],
                    }
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    cards = load_watchlist(AppConfig(raw={}, root=tmp_path))
    validate_watchlist_for_run(cards)
    assert watchlist_era_lot_search_terms(cards) == ["XY7 まとめ売り"]


def test_repository_watchlist_is_the_only_search_source():
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "data/watchlist.yaml").read_text(encoding="utf-8"))
    active_cards = [card for card in data["cards"] if card.get("active", True)]
    assert active_cards
    for card in data["cards"]:
        assert "search_terms" not in card
        assert "lot_search_terms" not in card
        assert "era_lot_search_terms" not in card
        assert "generic_lot_search_terms" not in card
    for card in active_cards:
        active_searches = [s for s in card["searches"] if s.get("active", True)]
        assert 1 <= len(active_searches) <= 4
        assert all(s["mode"] in {"exact", "focused_lot", "generic_lot"} for s in active_searches)
        if card["match_mode"] == "exact_card":
            assert card["pricecharting_url"].startswith("https://www.pricecharting.com/game/")


def test_repository_uses_central_run_limits_file():
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert base["run_limits_file"] == "data/run_limits.yaml"
    assert base["watchlist_file"] == "data/watchlist.yaml"

    # Tunable caps must not be duplicated in config.yaml.
    assert "max_results_per_search" not in base["sendico"]
    assert "max_listings_per_run" not in base["sendico"]
    assert "max_raw_links_per_search" not in base["sendico"]
    assert "max_screenings_per_run" not in base["sendico"]["tier2_lot_search"]
    assert "max_detailed_analyses_per_run" not in base["sendico"]["tier2_lot_search"]
    assert "max_total_tokens_per_run" not in base["vision"]

    limits = load_run_limits(root / "data/run_limits.yaml")
    validate_run_limits(limits)
    effective = load_config(root / "config.yaml")
    sendico = effective.raw["sendico"]
    tier2 = sendico["tier2_lot_search"]
    vision = effective.raw["vision"]

    assert sendico["max_results_per_search"] == limits["search"]["results_per_term"]
    assert tier2["max_results_per_search"] == limits["search"]["results_per_term"]
    assert sendico["max_listings_per_run"] == limits["search"]["total_listings_per_run"]
    assert tier2["max_screenings_per_run"] == limits["screening"]["max_listings_per_run"]
    assert tier2["max_detailed_analyses_per_run"] == limits["detailed_analysis"]["max_listings_per_run"]
    assert vision["max_listing_analyses_per_run"] == limits["detailed_analysis"]["max_listings_per_run"]
    assert vision["max_total_tokens_per_run"] == limits["token_budget"]["max_total_tokens_per_run"]


def test_changing_central_limit_updates_all_legacy_runtime_paths(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    limits = yaml.safe_load((root / "data/run_limits.yaml").read_text(encoding="utf-8"))
    limits["screening"]["max_listings_per_run"] = 77
    limits["screening"]["focused_lot_limit"] = 77
    limits["detailed_analysis"]["max_listings_per_run"] = 22

    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(base, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (tmp_path / "data/run_limits.yaml").write_text(
        yaml.safe_dump(limits, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    effective = load_config(tmp_path / "config.yaml").raw
    assert effective["sendico"]["tier2_lot_search"]["max_screenings_per_run"] == 77
    assert effective["sendico"]["tier2_lot_search"]["max_detailed_analyses_per_run"] == 22
    assert effective["vision"]["max_listing_analyses_per_run"] == 22


def test_central_limits_validation_rejects_inconsistent_values():
    root = Path(__file__).resolve().parents[1]
    limits = yaml.safe_load((root / "data/run_limits.yaml").read_text(encoding="utf-8"))
    limits["search"]["raw_links_per_term"] = 5
    limits["search"]["results_per_term"] = 25
    with pytest.raises(ValueError, match="raw_links_per_term"):
        validate_run_limits(limits)
