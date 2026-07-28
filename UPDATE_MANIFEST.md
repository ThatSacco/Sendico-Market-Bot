# Update manifest

Copy the contents of this ZIP into the root of the existing `Sendico-Market-Bot` repository and replace files when prompted.

## Replacement files

- `.github/workflows/scan.yml`
- `.github/workflows/tests.yml`
- `config.yaml`
- `src/pokemon_deal_bot/__init__.py`
- `src/pokemon_deal_bot/tier2_vision.py`
- `src/pokemon_deal_bot/updated_main.py`
- `tests/test_complete_update.py`
- `tests/test_repository_integrity.py`

## New files

- `src/pokemon_deal_bot/manual_main.py`
- `tests/test_manual_main.py`
- `MANUAL_SEARCH_UPDATE.md`
- `UPDATE_MANIFEST.md`
- `verify_manual_update.py`

## Files intentionally preserved

The package does not replace:

- `data/watchlist.yaml`
- `data/seen.json`
- `data/price_cache.json`
- `data/price_overrides.csv`
- reports
- secrets

The manual runner builds the active card rule in memory from GitHub inputs, so the checked-in watchlist is not modified.
