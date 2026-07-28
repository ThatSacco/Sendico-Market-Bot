# Upload repair before running

The current GitHub repository contains the new Tier 2 configuration, watchlist fields, Discord summary, and tests, but it still has older versions of these two production files:

- `src/pokemon_deal_bot/main.py`
- `src/pokemon_deal_bot/gemini_vision.py`

Upload the two files in this package to the matching repository paths and replace the existing files.

After committing, run the GitHub Actions test step. The scanner workflow already runs `pytest -q` before the live scan, so do not bypass the tests.

Expected checks after upload:

- `main.py` imports `watchlist_era_lot_search_terms` and `watchlist_generic_lot_search_terms`.
- `main.py` calls `vision.screen_listing(...)`.
- `gemini_vision.py` contains `def screen_listing(...)`.
- `gemini_vision.py` contains `def _extract_multi_overview_crops(...)`.
