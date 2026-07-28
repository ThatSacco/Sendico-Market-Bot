# Sendico Runtime Wiring Hotfix v3.3

This package restores the three runtime files omitted from the watchlist-only update:

- `src/pokemon_deal_bot/updated_main.py`
- `src/pokemon_deal_bot/tier2_vision.py`
- `src/pokemon_deal_bot/__init__.py`

Copy the ZIP contents into the repository root and replace matching files.

Then run:

```powershell
python -m compileall -q src
python -m pytest -q
python .\verify_runtime_wiring.py
```

Commit with:

```powershell
git add src/pokemon_deal_bot/__init__.py src/pokemon_deal_bot/updated_main.py src/pokemon_deal_bot/tier2_vision.py tests/test_runtime_wiring.py verify_runtime_wiring.py
git commit -m "Restore manual scanner runtime modules"
git push
```
