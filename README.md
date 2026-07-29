# Sendico Pokemon Reference Matcher

This scanner uses each active PriceCharting product page as the source of truth
for the target card's identity, reference artwork and current market price.
Search wording is used only to discover Sendico/Mercari listings; it is not used
as a card-identification gate.

## User-editable files

| File | Purpose |
|---|---|
| `data/watchlist.yaml` | Active PriceCharting links and Sendico search phrases |
| `data/run_limits.yaml` | Search volume, image batches, Gemini requests and token ceiling |
| `data/search_criteria.yaml` | Image-match and Discord alert thresholds |

A watchlist target needs only an ID, a PriceCharting product link and one or more
search phrases. Names, set codes, card numbers, rarity and language are not
manually duplicated.

## Matching flow

1. Download and cache the PriceCharting page, main card image and price.
2. Search Sendico using the active watchlist phrases.
3. Hydrate each listing and collect only images belonging to that Mercari item.
4. Compare the PriceCharting reference against all listing-image batches using
   Gemini 3.5 Flash-Lite.
5. Send a probable-match Discord alert immediately when the early threshold is
   reached.
6. Compare the reference against enlarged original images and detected card
   crops using Gemini 3.6 Flash.
7. Send a confirmed-match alert immediately when the detailed threshold is met.
8. Overwrite `reports/latest.json` and `reports/latest.csv`, then send the
   completion summary.

By default, every discovered listing is checked against every active target.
The search that found a listing only sets processing priority. This avoids
missing a target merely because the listing was discovered by another card's
search phrase.

## Monitoring frequency

`.github/workflows/scan.yml` runs once per hour and can also be started manually.
Alerts are sent while the run is processing rather than being held until the
completion summary. GitHub-hosted scheduling is near-real-time, not an instant
webhook from Mercari.

## Repository-size controls

- Reference images are stored in the GitHub Actions cache, not committed.
- Reports overwrite the same two `latest` files.
- `data/seen.json` is automatically pruned to the most recent 5,000 listings by
  default; change `state.max_seen_listings` in `data/run_limits.yaml`.
- PriceCharting metadata uses one compact JSON cache record per target.

## Required GitHub secrets

- `GEMINI_API_KEY`
- `DISCORD_WEBHOOK_URL`

## First run

1. Upload the replacement files from the v8 package.
2. Run the **Test Sendico Market Bot** workflow.
3. Remove the superseded files listed in `GITHUB_UPLOAD_AND_CLEANUP.md`.
4. Run the tests again.
5. Manually run **Scan Sendico Pokemon Deals**.
