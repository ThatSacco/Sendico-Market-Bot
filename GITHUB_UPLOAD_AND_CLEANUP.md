# GitHub web upload and cleanup

This update is a coherent replacement, not a patch over the v5-v7 runtime.
Use the GitHub website only; no PowerShell or local update script is required.

## Phase 1 — upload or replace

Upload every repository file in this package using the same path. In particular,
replace the complete contents of:

- `.github/workflows/scan.yml`
- `.github/workflows/tests.yml`
- `config.yaml`
- `requirements.txt`
- `pyproject.toml`
- `.gitignore`
- `README.md`
- `data/watchlist.yaml`
- `data/run_limits.yaml`
- `data/search_criteria.yaml`
- `data/seen.json`
- `data/reference_cache.json`
- `reports/latest.json`
- `reports/latest.csv`
- all replacement files under `src/pokemon_deal_bot/`
- all replacement files under `tests/`

The `data/reference_images/.gitkeep` file creates the cache directory. Actual
reference JPG files are ignored by Git and stored by the Actions cache.

Suggested first commit:

`Add PriceCharting reference-image matching v8`

Run the **Test Sendico Market Bot** workflow before deleting anything.

## Phase 2 — remove root update artefacts

Delete these files currently visible at the repository root:

- `FRESH_UPLOAD_INSTRUCTIONS.md`
- `GEMINI_MIGRATION_NOTES.md`
- `GITHUB_FILE_UPLOAD_INSTRUCTIONS.md`
- `README_UPDATE.md`
- `RUN_LIMITS_GUIDE.md`
- `SHA256SUMS.txt`
- `UPDATE_INSTRUCTIONS.md`
- `UPDATE_MANIFEST.md`
- `UPDATE_NOTES.md`
- `UPLOAD_MANIFEST.md`
- `WATCHLIST_GUIDE.md`
- `WORKING_BACKUP_NOTES.md`
- `apply_v5_update.py`
- `verify_v5_update.py`
- `verify_watchlist_update.py`

`GITHUB_UPLOAD_AND_CLEANUP.md` may also be deleted after the migration is
finished; the operating instructions remain in `README.md`.

## Phase 3 — remove superseded source modules

Delete these old modules after the replacement tests pass:

- `src/pokemon_deal_bot/deal.py`
- `src/pokemon_deal_bot/fx.py`
- `src/pokemon_deal_bot/gemini_vision.py`
- `src/pokemon_deal_bot/groq_model_pool.py`
- `src/pokemon_deal_bot/pricecharting.py`
- `src/pokemon_deal_bot/vision.py`
- `src/pokemon_deal_bot/updated_main.py` if present
- `src/pokemon_deal_bot/tier2_vision.py` if present

The v8 source folder should contain only:

- `__init__.py`
- `config.py`
- `discord.py`
- `gemini.py`
- `image_processing.py`
- `main.py`
- `models.py`
- `reference.py`
- `reporting.py`
- `sendico.py`
- `state.py`

## Phase 4 — remove old tests

Keep only these v8 test files:

- `tests/test_config.py`
- `tests/test_gemini.py`
- `tests/test_image_processing.py`
- `tests/test_main_helpers.py`
- `tests/test_reference.py`
- `tests/test_repository.py`
- `tests/test_sendico.py`
- `tests/test_state.py`

Delete all other old tests and `tests/fixtures/`. The old tests enforce the
superseded metadata-based matching and v5-v7 configuration structures.

## Phase 5 — clean generated data

Delete:

- `data/price_overrides.csv`
- `data/price_cache.json`

Keep:

- `data/watchlist.yaml`
- `data/run_limits.yaml`
- `data/search_criteria.yaml`
- `data/seen.json`
- `data/reference_cache.json`
- `data/reference_images/.gitkeep`

The two report files are intentionally retained and overwritten each run, so
they do not accumulate.

Suggested cleanup commit:

`Remove superseded scanner files`

Run the Tests workflow again, then start the Scan workflow manually.

## Final minimal root

After cleanup, the root should contain only:

- `.github/`
- `data/`
- `reports/`
- `src/`
- `tests/`
- `.gitignore`
- `config.yaml`
- `pyproject.toml`
- `requirements.txt`
- `README.md`

Deleting files removes them from the current working tree. It does not rewrite
the repository's historical commits, which is normally preferable and safer.
