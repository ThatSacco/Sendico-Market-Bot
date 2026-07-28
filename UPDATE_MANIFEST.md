# Update Manifest

Prepared against the public `main` branch of `ThatSacco/Sendico-Market-Bot` on 28 July 2026.

## Replacement files

### `config.yaml`

- Adds `vision.pipeline_state_version: gemini-tier2-multi-overview-v3`.
- Increases Tier 2 screening overview coverage from 4 to 6 photos.
- Increases Tier 2 detailed overview coverage from 4 to 12 photos.
- Retains the current watchlist, Gemini models, API version, safety caps, pricing settings and Sendico fee settings.

### `.github/workflows/scan.yml`

- Retains the current Sydney schedule guard, dependencies, tests and state persistence.
- Changes only the scanner command from:

```text
python -m pokemon_deal_bot.main --config config.yaml
```

  to:

```text
python -m pokemon_deal_bot.updated_main --config config.yaml
```

### `src/pokemon_deal_bot/__init__.py`

- Keeps the existing package import path.
- Installs the Tier 2 methods on `GeminiLotVisionAnalyzer` when they are absent.
- Updates the package version to `0.2.0`.

## New runtime files

### `src/pokemon_deal_bot/tier2_vision.py`

Adds the methods already referenced by the current `main.py` and existing Gemini tests:

- `screen_listing()`
- `analyze_with_overviews()`
- `_extract_multi_overview_crops()`

The implementation:

- Sends multiple overview photos during the low-cost screening stage.
- Prioritises screening-positive photos during detailed analysis.
- Detects card regions locally in each selected photo.
- Removes perceptual duplicates.
- Allocates the crop budget across photos in round-robin order.
- Reuses the existing card identification, matching, grading and quantity-merging functions.

### `src/pokemon_deal_bot/updated_main.py`

Runs the existing `main.py` with compatibility-safe reliability instrumentation:

- Versions scan state by provider, model pool, API version and pipeline version.
- Counts search, hydration, screening and detailed-analysis failures.
- Returns a non-zero exit code for systemic failures.
- Preserves expected `PAUSED` behavior for request budget and rate-limit stops.
- Labels partial runs `COMPLETED WITH ERRORS` in Discord.
- Displays the configured Sendico fee instead of relying on the literal `¥800` wording.
- Does not change the current `main.run(config_path, dry_run)` API or existing source files.

## New tests and verification

### `tests/test_complete_update.py`

Covers:

- Tier 2 method availability on the existing import path.
- Pipeline-version scan signatures.
- Systemic search and vision failures.
- Paused-run handling.
- Partial-error and failed Discord summaries.
- Configured Sendico fee wording.

### `verify_complete_update.py`

Read-only repository verification and test runner.

## Files intentionally not replaced

The package deliberately leaves these existing files untouched:

- `src/pokemon_deal_bot/main.py`
- `src/pokemon_deal_bot/gemini_vision.py`
- `src/pokemon_deal_bot/vision.py`
- `src/pokemon_deal_bot/models.py`
- `src/pokemon_deal_bot/deal.py`
- `src/pokemon_deal_bot/discord.py`
- `data/watchlist.yaml`
- `data/seen.json`
- `data/price_cache.json`
- Reports and all unrelated tests

This minimises merge risk while preserving all existing imports and configuration references.
