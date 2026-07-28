from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent

required = [
    ROOT / ".github/workflows/scan.yml",
    ROOT / "src/pokemon_deal_bot/manual_main.py",
    ROOT / "tests/test_manual_main.py",
    ROOT / "tests/test_config.py",
    ROOT / "data/watchlist.yaml",
]
missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
if missing:
    raise SystemExit("Missing required files: " + ", ".join(missing))

workflow = (ROOT / ".github/workflows/scan.yml").read_text(encoding="utf-8")
assert "watchlist_id:" in workflow
assert "SENDICO_WATCHLIST_ID" in workflow
assert "SENDICO_SEARCH_TERMS" not in workflow
assert "target_name:" not in workflow

watchlist = yaml.safe_load((ROOT / "data/watchlist.yaml").read_text(encoding="utf-8"))
active_exact = [
    item
    for item in watchlist.get("cards", [])
    if item.get("active", True) and item.get("match_mode", "exact_card") == "exact_card"
]
if not active_exact:
    raise SystemExit("No active exact_card entries found in data/watchlist.yaml")
for item in active_exact:
    terms = [str(value).strip() for value in item.get("era_lot_search_terms", [])]
    if not terms:
        raise SystemExit(f"{item.get('id')} has no era_lot_search_terms")
    if len(terms) > 4:
        raise SystemExit(f"{item.get('id')} has more than four era_lot_search_terms")

print("Watchlist-only bounded search update is correctly installed.")
