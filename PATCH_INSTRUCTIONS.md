# Exact PriceCharting reference update

Upload the contents of this folder to the root of the GitHub repository and replace matching files.

## What this update adds

- Optional `pricecharting_url` support for `match_mode: exact_card` entries.
- The watchlist product page is checked before a normal PriceCharting search.
- The page identity is still verified against the identified name, number, set and variant.
- Automatic fallback to the normal PriceCharting search if the direct page is unavailable or does not match.
- Direct references are restricted to PriceCharting `/game/` product pages.
- Direct references are rejected for `pokemon_general` rules because those can match many cards.
- Discord pricing lines now include a clickable PriceCharting source link.
- All previous multi-watchlist, deduplication, retry and Thursday-midnight Sydney behaviour remains in place.

## Included example

The active Ampharos EX entry in `data/watchlist.yaml` now contains:

```yaml
pricecharting_url: "https://www.pricecharting.com/game/pokemon-japanese-bandit-ring/ampharos-ex-27"
```

For future exact-card searches, copy the full PriceCharting product page URL into the relevant watchlist entry. The field is optional; if omitted, the bot performs its normal PriceCharting search.

## Important files

Replace all included files, especially:

```text
data/watchlist.yaml
src/pokemon_deal_bot/models.py
src/pokemon_deal_bot/pricecharting.py
src/pokemon_deal_bot/discord.py
README.md
```

The package is a full replacement based on the latest exact/general multi-watchlist version, so uploading all included files is recommended.

## Preserve scan history

Do not delete your existing:

```text
data/seen.json
data/price_cache.json
reports/
```

Those files are not included in this package. Editing a watchlist URL changes the active watchlist signature, allowing existing listings to be reassessed under the new pricing reference.

## Upload process

1. Extract this ZIP.
2. Upload all extracted contents to the repository root.
3. Allow GitHub to replace matching files.
4. Keep the existing `data/seen.json`, `data/price_cache.json`, and `reports/` files.
5. Commit to `main`.
6. Open **Actions** and run the scanner manually once.

The weekly schedule remains Thursday at 12:00 AM Sydney time, with daylight-saving handling.
