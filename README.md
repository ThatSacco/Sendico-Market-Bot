# Sendico Japanese Pokemon Deal Bot

This bot searches Sendico's Mercari Pokemon listings, identifies Japanese raw or graded cards, checks PriceCharting values, and posts qualifying watchlist matches to Discord.

## Vision provider

Production scans use the paid Gemini API. The local image pipeline remains unchanged:

```text
Sendico listing photos
    -> verified listing-image filtering
    -> local OpenCV card detection and perspective correction
    -> alternate-photo and quantity reconciliation
    -> compact JPEG contact sheets
    -> Gemini card identification
    -> local watchlist matching
    -> PriceCharting
    -> Discord
```

Only the compact contact sheet is sent to Gemini. Watchlist target names and card details are not added to the model prompt, so identification is performed from the visible card rather than being biased toward a desired result.

### Gemini model order

`config.yaml` uses two stable paid models:

```yaml
vision:
  provider: "gemini"
  models:
    - "gemini-3.6-flash"
    - "gemini-3.5-flash-lite"
  thinking_level: "low"
```

The scanner first uses Gemini 3.6 Flash. If it is temporarily rate-limited or unavailable, the same request is retried and then moved to Gemini 3.5 Flash-Lite. The successful model is preferred for the remainder of the run.

Requests use the Gemini Interactions REST API in stateless mode (`store: false`). The response is requested with a JSON schema; if structured output is rejected or repeatedly returns unusable JSON, the client retries with the prompt-only JSON instructions.

### Paid-capacity safeguards

The default configuration allows a substantially larger scan than the previous Groq free-tier setup while retaining hard limits:

```yaml
vision:
  max_listing_analyses_per_run: 100
  max_vision_requests_per_run: 150
  request_spacing_seconds: 1.0
  max_retries_per_model: 2
```

HTTP 429 and temporary server errors are retried with bounded backoff. The client honours `Retry-After` and Google's retry-delay metadata when present. Requests remain stateless and are not stored as Interaction history. The Discord completion summary reports requests, models used, and Gemini token usage.

## Required GitHub secrets

Create these repository secrets under:

```text
Settings -> Secrets and variables -> Actions
```

```text
GEMINI_API_KEY
DISCORD_WEBHOOK_URL
```

`GROQ_API_KEY` is no longer used by the production workflow and can be removed after a successful Gemini test run.

## Watchlist

Normal search changes require editing only:

```text
data/watchlist.yaml
```

### Exact card

Use `match_mode: exact_card` when the precise printed card is required:

```yaml
cards:
  - id: ampharos_ex_xy7_027
    active: true
    match_mode: exact_card
    english_name: "Ampharos EX"
    japanese_name: "デンリュウEX"
    set_name: "Bandit Ring"
    set_code: "XY7"
    card_number: "027/081"
    language: "Japanese"
    pricecharting_url: "https://www.pricecharting.com/game/pokemon-japanese-bandit-ring/ampharos-ex-27"
    search_terms:
      - "デンリュウEX 027/081"
      - "Ampharos EX 027/081 Japanese"
    lot_search_terms:
      - "デンリュウ まとめ"
      - "デンリュウ セット"
      - "デンリュウ ポケカ まとめ"
      - "デンリュウ コレクション"
      - "Ampharos Pokemon card lot"
```

The Pokemon name and printed card number must match. Set information is checked when Gemini can read it.

### Tier 2 Pokemon lot search

`lot_search_terms` are optional, broader marketplace searches intended to find multi-card listings that mention the desired Pokemon without naming the exact printed card. Exact `search_terms` always run first. Tier 2-only results are ranked after normal watchlist results and are capped separately so they cannot consume the entire Gemini allowance.

```yaml
sendico:
  tier2_lot_search:
    enabled: true
    max_results_per_search: 30
    max_analyses_per_run: 20
    allow_query_only_candidates: true
```

With `allow_query_only_candidates: true`, a result returned by a Tier 2 query may reach Gemini even when the abbreviated search-result text does not repeat the Pokemon name. Gemini must still identify the exact watchlist card before the listing can qualify for an alert. Duplicate listings returned by both exact and Tier 2 searches are merged and treated as normal higher-priority watchlist results.

For the initial Ampharos test, the scanner retains at most 30 results from each Tier 2 term and performs at most 20 Tier 2-only Gemini analyses in the full run. The analysis cap is applied after unchanged listings are skipped, allowing later candidates to rotate into subsequent scans. Adjust `max_analyses_per_run` after reviewing token usage and match quality.

### General Pokemon search

Use `match_mode: pokemon_general` to accept any identified card for a Pokemon:

```yaml
cards:
  - id: tyranitar_neo_era
    active: true
    match_mode: pokemon_general
    english_names:
      - "Tyranitar"
    japanese_names:
      - "バンギラス"
    language: "Japanese"
    accepted_sets:
      - "Neo Discovery"
      - "Neo Destiny"
    search_terms:
      - "バンギラス 旧裏"
      - "Tyranitar Neo Japanese"
```

`accepted_sets` and `accepted_set_codes` are optional. Remove both fields to allow the Pokemon from every set.

## Quantity across listing photos

Sendico sellers often photograph one physical card several times. Quantity is anchored to the greatest number of identical cards visible together in a single source photo rather than summing alternate views. Five photos of one card are valued as `1x`; two identical cards visible together in an overview photo are valued as `2x`.

## Listing deduplication and retries

The scanner stores listing state in `data/seen.json`.

- Successfully processed unchanged listings are skipped.
- Already-alerted unchanged listings are not alerted again.
- Retryable failures receive no more than three attempts for the same listing and watchlist signature.
- The counter resets when the listing price, title, seller rating, images, or active watchlist changes.

## Schedule

The workflow runs weekly at midnight at the start of Thursday in the `Australia/Sydney` time zone. Manual runs through **Actions -> Run workflow** are also supported.

## Local verification

```bash
python -m compileall -q src
pytest -q
```
