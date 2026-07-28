# Update manifest

The updater preserves and migrates the current `data/watchlist.yaml` rather
than blindly replacing it.

Payload files copied directly:

- `.github/workflows/scan.yml`
- `config.yaml`
- `src/pokemon_deal_bot/__init__.py`
- `src/pokemon_deal_bot/config.py`
- `src/pokemon_deal_bot/models.py`
- `src/pokemon_deal_bot/tier2_vision.py`
- `src/pokemon_deal_bot/updated_main.py`
- `tests/test_v5_token_pipeline.py`

Existing repository files updated safely by `apply_v5_update.py`:

- `data/watchlist.yaml`
- `src/pokemon_deal_bot/main.py`
- `src/pokemon_deal_bot/gemini_vision.py`
- `src/pokemon_deal_bot/sendico.py`
- `src/pokemon_deal_bot/vision.py`
- `tests/test_config.py`
- `tests/test_repository_integrity.py`
