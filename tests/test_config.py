from pathlib import Path

import pytest
import yaml

from pokemon_deal_bot.config import (
    AppConfig,
    load_watchlist,
    watchlist_lot_search_terms,
    watchlist_search_terms,
    watchlist_signature,
)
from pokemon_deal_bot.models import WatchCard


def test_watchlist_supports_multiple_active_modes(tmp_path: Path):
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
                        "search_terms": ["Ampharos EX 027/081"],
                        "lot_search_terms": [
                            "デンリュウ まとめ",
                            "Ampharos Pokemon card lot",
                        ],
                    },
                    {
                        "id": "tyranitar",
                        "active": True,
                        "match_mode": "pokemon_general",
                        "english_names": ["Tyranitar"],
                        "search_terms": ["Tyranitar Neo Japanese"],
                    },
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    cards = load_watchlist(AppConfig(raw={}, root=tmp_path))
    assert [card.match_mode for card in cards] == ["exact_card", "pokemon_general"]
    assert watchlist_search_terms(cards) == [
        "Ampharos EX 027/081",
        "Tyranitar Neo Japanese",
    ]
    assert watchlist_lot_search_terms(cards) == [
        "デンリュウ まとめ",
        "Ampharos Pokemon card lot",
    ]


def test_lot_search_terms_are_cleaned_and_deduplicated():
    card = WatchCard(
        id="ampharos",
        match_mode="exact_card",
        english_name="Ampharos EX",
        card_number="027/081",
        lot_search_terms=[
            " デンリュウ まとめ ",
            "デンリュウ まとめ",
            "Ampharos Pokemon card lot",
        ],
    )
    assert watchlist_lot_search_terms([card]) == [
        "デンリュウ まとめ",
        "Ampharos Pokemon card lot",
    ]


def test_general_search_terms_can_be_generated_from_names():
    card = WatchCard(
        id="tyranitar",
        match_mode="pokemon_general",
        english_names=["Tyranitar"],
        japanese_names=["バンギラス"],
    )
    assert watchlist_search_terms([card]) == [
        "バンギラス",
        "Tyranitar Japanese",
    ]


def test_exact_card_requires_a_card_number():
    with pytest.raises(ValueError, match="requires card_number"):
        WatchCard(
            id="invalid",
            match_mode="exact_card",
            english_name="Ampharos EX",
        )


def test_watchlist_signature_changes_when_rule_changes():
    first = WatchCard(
        id="a",
        match_mode="exact_card",
        english_name="Ampharos EX",
        card_number="027/081",
    )
    second = WatchCard(
        id="a",
        match_mode="exact_card",
        english_name="Ampharos EX",
        card_number="028/081",
    )
    assert watchlist_signature([first]) != watchlist_signature([second])


def test_exact_card_accepts_pricecharting_product_url():
    url = (
        "https://www.pricecharting.com/game/"
        "pokemon-japanese-bandit-ring/ampharos-ex-27"
    )
    card = WatchCard(
        id="ampharos",
        match_mode="exact_card",
        english_name="Ampharos EX",
        card_number="027/081",
        pricecharting_url=f"  {url}  ",
    )
    assert card.pricecharting_url == url


def test_general_rule_rejects_direct_pricecharting_url():
    with pytest.raises(ValueError, match="only with match_mode 'exact_card'"):
        WatchCard(
            id="tyranitar",
            match_mode="pokemon_general",
            english_name="Tyranitar",
            pricecharting_url=(
                "https://www.pricecharting.com/game/"
                "pokemon-japanese-neo-discovery/tyranitar-12"
            ),
        )


def test_watchlist_rejects_non_pricecharting_reference_url():
    with pytest.raises(ValueError, match="invalid pricecharting_url"):
        WatchCard(
            id="ampharos",
            match_mode="exact_card",
            english_name="Ampharos EX",
            card_number="027/081",
            pricecharting_url="https://example.com/game/ampharos-ex-27",
        )


def test_watchlist_rejects_pricecharting_search_page_as_direct_reference():
    with pytest.raises(ValueError, match="must point to a PriceCharting /game/"):
        WatchCard(
            id="ampharos",
            match_mode="exact_card",
            english_name="Ampharos EX",
            card_number="027/081",
            pricecharting_url=(
                "https://www.pricecharting.com/search-products?q=ampharos"
            ),
        )


def test_repository_watchlist_uses_generic_tier2_lot_queries():
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "data" / "watchlist.yaml").read_text(encoding="utf-8"))
    ampharos = next(card for card in data["cards"] if card["id"] == "ampharos_ex_xy7_027")
    terms = ampharos["lot_search_terms"]
    assert "ポケカ まとめ売り" in terms
    assert "ポケカ XY まとめ売り" in terms
    assert all("デンリュウ" not in term and "Ampharos" not in term for term in terms)


def test_repository_config_runs_tier2_only_and_requires_lot_evidence():
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    tier2 = data["sendico"]["tier2_lot_search"]
    assert tier2["enabled"] is True
    assert tier2["run_standard_watchlist_searches"] is False
    assert tier2["require_strong_lot_evidence"] is True
    assert tier2["max_analyses_per_run"] == 20
