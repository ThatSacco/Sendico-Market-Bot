# Quantity and graded-slab correction

Upload the contents of this folder to the root of the GitHub repository and replace matching files.

## What this update fixes

- Alternate photos of the same physical card no longer multiply the quantity.
- Quantity is based on the greatest number of identical cards visible together in one source photo.
- Card backs and unreadable slab backs are explicitly excluded from Groq identification.
- Professionally graded cards now retain their grading company and grade.
- Explicit title claims such as `PSA10` are used as a fallback when the card identity matches but the cropped image misses the slab label.
- Title-derived grades are marked `claimed` in Discord and require manual verification.
- PriceCharting now uses the matching guide tier instead of always using Ungraded.
- A PSA 10 card uses the `PSA 10` value; Grade 7, 8, 9 and 9.5 use their corresponding guide values.
- Another company's grade 10 is not automatically valued as PSA 10.
- Front, back and close-up views of one slab are merged into one physical card.

## Existing features retained

- Multiple exact-card and general-Pokemon watchlist entries.
- Optional `pricecharting_url` for exact-card entries.
- 95% PriceCharting identity matching and safe fallback search.
- Three total attempts for retryable listing failures.
- `data/seen.json` listing deduplication.
- Thursday midnight Sydney schedule with daylight-saving handling.
- Groq request-size and rate-limit protection.

## Important files

This is a complete replacement package. Upload all included files. The main changes are in:

```text
src/pokemon_deal_bot/models.py
src/pokemon_deal_bot/vision.py
src/pokemon_deal_bot/pricecharting.py
src/pokemon_deal_bot/discord.py
tests/test_grading.py
```

## Preserve your data

Do not delete your existing:

```text
data/seen.json
data/price_cache.json
reports/
```

The previous one-price cache format is migrated automatically. When a graded tier is required, the bot refreshes the relevant PriceCharting page and stores all available guide tiers.

## Upload process

1. Extract this ZIP.
2. Upload all extracted contents to the repository root.
3. Allow GitHub to replace matching files.
4. Preserve `data/seen.json`, `data/price_cache.json`, and `reports/`.
5. Commit to `main`.
6. Open **Actions** and run the scanner manually once.

## Retest the PSA 10 listing

A successfully processed listing is normally skipped. To retest this listing without deleting scan history, temporarily set:

```yaml
test_mode:
  enabled: true
  max_alerts_per_run: 1
  ignore_seen_state: true
  skip_search_when_direct_urls: true
  direct_listing_urls:
    - "https://sendico.com/shop/mercari/catalog/m24075102942"
```

The corrected result should show one Ampharos card and a `PSA 10` PriceCharting tier. When the grade came from the title fallback, Discord will display `PSA 10 claimed`.

After the test, restore:

```yaml
test_mode:
  enabled: false
  ignore_seen_state: false
  direct_listing_urls: []
```
