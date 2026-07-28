# Update manifest

Replacement files:

- `.github/workflows/scan.yml`
- `src/pokemon_deal_bot/manual_main.py`
- `tests/test_manual_main.py`
- `tests/test_config.py`

Documentation:

- `WATCHLIST_SEARCH_UPDATE.md`
- `verify_watchlist_search_update.py`

No `data/watchlist.yaml` file is included, so the update will not overwrite the
user's existing card entries or search terms.
