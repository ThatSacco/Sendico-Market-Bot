# GitHub file-only update v5.2

This package contains only complete replacement files. No PowerShell, local clone,
or updater script is required.

Replace these files in GitHub using the pencil icon (Edit this file), or upload each
file while browsing to its matching repository folder:

1. `config.yaml`
2. `.github/workflows/scan.yml`
3. `src/pokemon_deal_bot/__init__.py`
4. `src/pokemon_deal_bot/tier2_vision.py`
5. `src/pokemon_deal_bot/updated_main.py`
6. `tests/test_config.py`
7. `tests/test_repository_integrity.py`
8. `tests/test_v5_token_pipeline.py`

Commit all eight replacements, then open **Actions** and re-run the failed test
workflow. The scanner workflow should be run only after the test workflow passes.

## Why all eight files must be replaced together

The failed run mixed old bounded-search tests (15 screenings, manual-only workflow)
with the newer 125,000-token configuration (25 results, 40 screenings, 12 detailed
analyses, scheduled and manual workflow). It also had a Gemini analyser without the
runtime methods and token-budget constructor arguments expected by the v5 tests.

The v5.2 files align those versions and install the runtime support during package
import, before `main.py` imports Gemini, PriceCharting and Discord functions.
