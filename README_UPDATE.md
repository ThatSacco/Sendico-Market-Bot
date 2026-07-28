# Apply this update

Copy the contents of this package into the root of the existing `Sendico-Market-Bot` repository and replace matching files. Do not delete the existing repository first; unchanged source, data, cache and report files must remain.

Then run:

```powershell
python .\verify_watchlist_update.py
python -m compileall -q src
python -m pytest -q
```

Review and push:

```powershell
git status --short
git diff --check
git diff
git add .
git commit -m "Use watchlist-only bounded Sendico searches"
git push
```

After GitHub tests pass, edit only `data/watchlist.yaml` when changing cards or search wording. Start scans manually from GitHub Actions.
