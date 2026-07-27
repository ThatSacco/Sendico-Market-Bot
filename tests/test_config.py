from pathlib import Path

import pytest
import yaml

from pokemon_deal_bot.config import (
    AppConfig,
    load_watchlist,
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
