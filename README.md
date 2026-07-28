# Sendico watchlist-only search update

Copy this package into the root of the existing Sendico Market Bot repository and
replace matching files.

The update does not contain `data/watchlist.yaml`, so it will not overwrite the
user's card entries or current search terms.

Before running GitHub Actions, edit the selected card in `data/watchlist.yaml`:

```yaml
era_lot_search_terms:
  - "バンデットリング まとめ売り"
  - "XY7 まとめ売り"
```

Use one to four focused terms. The manual workflow ignores
`generic_lot_search_terms` to prevent broad searches from increasing token use.

Validate locally:

```powershell
python .\verify_watchlist_search_update.py
python -m pytest -q
```

Commit and push:

```powershell
git add .
git commit -m "Read manual Sendico search terms from watchlist"
git push
```

In GitHub Actions, enter the selected watchlist `id`, the direct PriceCharting
product URL, and the conservative limits. There is no search-term input field.
