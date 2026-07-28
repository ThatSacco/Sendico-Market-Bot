# v5.2 update manifest

- `config.yaml` — 125,000-token budget and expanded bounded limits.
- `.github/workflows/scan.yml` — manual plus Thursday-midnight Sydney schedule; runs `main` directly.
- `src/pokemon_deal_bot/__init__.py` — installs runtime support before scanner imports.
- `src/pokemon_deal_bot/tier2_vision.py` — two-pass methods, token enforcement, target-before-pricing guard, single-card suppression and held-count correction.
- `src/pokemon_deal_bot/updated_main.py` — self-contained backwards-compatible helper module.
- `tests/test_config.py` — expectations aligned to the v5 limits.
- `tests/test_repository_integrity.py` — expectations aligned to manual plus scheduled execution and direct `main` runtime.
- `tests/test_v5_token_pipeline.py` — validates installed methods, token guard and runtime safety controls.
