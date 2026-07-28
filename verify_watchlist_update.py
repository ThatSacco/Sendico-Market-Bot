from __future__ import annotations

import ast
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent

required = [
    ROOT / "config.yaml",
    ROOT / "data/watchlist.yaml",
    ROOT / "src/pokemon_deal_bot/models.py",
    ROOT / "src/pokemon_deal_bot/config.py",
    ROOT / "src/pokemon_deal_bot/updated_main.py",
    ROOT / "src/pokemon_deal_bot/tier2_vision.py",
    ROOT / ".github/workflows/scan.yml",
    ROOT / ".github/workflows/tests.yml",
]
for path in required:
    if not path.exists():
        raise SystemExit(f"Missing required file: {path.relative_to(ROOT)}")

for path in (ROOT / "src").rglob("*.py"):
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
watchlist = yaml.safe_load((ROOT / "data/watchlist.yaml").read_text(encoding="utf-8"))

sendico = config["sendico"]
tier2 = sendico["tier2_lot_search"]
assert sendico["max_results_per_search"] == 15
assert sendico["max_listings_per_run"] == 30
assert sendico["maximum_scroll_rounds"] == 5
assert sendico["search_terms"] == []
assert sendico["use_legacy_config_search_terms"] is False
assert tier2["allow_query_only_candidates"] is False
assert tier2["max_screenings_per_run"] == 15
assert tier2["max_detailed_analyses_per_run"] == 3

active_cards = [card for card in watchlist["cards"] if card.get("active", True)]
assert active_cards
for card in watchlist["cards"]:
    legacy = {
        "search_terms",
        "lot_search_terms",
        "era_lot_search_terms",
        "generic_lot_search_terms",
    }
    assert not legacy.intersection(card), f"Legacy search keys remain in {card['id']}"
for card in active_cards:
    searches = [s for s in card["searches"] if s.get("active", True)]
    assert 1 <= len(searches) <= 4

workflow = (ROOT / ".github/workflows/scan.yml").read_text(encoding="utf-8")
assert "schedule:" not in workflow
assert "pokemon_deal_bot.updated_main" in workflow
assert "SENDICO_SEARCH_TERMS" not in workflow

print("Watchlist-only bounded-search update is correctly installed.")
