# Sendico Market Bot v5 update

This package consolidates the scanner into `pokemon_deal_bot.main`, keeps
`data/watchlist.yaml` as the only source of card/search information, restores
true two-pass Gemini processing, and raises the per-run Gemini target to
approximately 100,000-150,000 tokens.

## Apply

1. Extract all files into the root of the existing GitHub repository.
2. From the repository root, run:

```powershell
python .\apply_v5_update.py
```

The updater creates timestamped backups under `.update_backups/`, migrates the
existing watchlist without replacing your cards, compiles the source, and runs
the full test suite.

Afterwards, verify explicitly:

```powershell
python .\verify_v5_update.py
python -m pytest -q
```

Then review and push:

```powershell
git status --short
git diff --check
git diff
git add .
git commit -m "Consolidate watchlist search and 125k token pipeline"
git push
```

## Token behaviour

`125,000` is a hard target ceiling, not a forced minimum. The scanner stops
before another Gemini request when the current usage plus a 5,000-token reserve
would exceed the target. A run can finish below 100,000 tokens if it runs out of
eligible candidates, no listings pass screening, or another operational limit
is reached.
