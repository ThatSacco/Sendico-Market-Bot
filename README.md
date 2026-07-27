# Sendico Japanese Pokemon Deal Bot

This bot searches Sendico's Mercari Pokemon listings, identifies Japanese raw cards, checks PriceCharting values, and posts qualifying watchlist matches to Discord.

## Watchlist modes

The scanner now supports any number of active entries in `data/watchlist.yaml`.

### Exact card

Use `match_mode: exact_card` when the precise printed card is required.

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
```

The Pokemon name and printed card number must match. Set information is also checked when Groq can identify it.

### Optional exact PriceCharting reference

An `exact_card` entry may include a direct PriceCharting product page:

```yaml
pricecharting_url: "https://www.pricecharting.com/game/pokemon-japanese-bandit-ring/ampharos-ex-27"
```

The bot checks this page before doing a general PriceCharting search. It still verifies the page title and URL against the identified Pokemon name, printed number, set and finish variant. If the page is unavailable or does not meet the normal 95% identity threshold, the bot falls back to the regular PriceCharting search.

For safety, the field accepts only PriceCharting `/game/` product pages and may only be used with `match_mode: exact_card`. General Pokemon searches can match many different products, so they continue to discover the precise PriceCharting page after Groq identifies each card.

Discord pricing lines include a clickable PriceCharting source link.

### General Pokemon

Use `match_mode: pokemon_general` to accept any identified card for a Pokemon.

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

`accepted_sets` and `accepted_set_codes` are optional. Remove both fields to allow the Pokemon from every set. A base-name rule such as `Tyranitar` also recognizes prefixed forms such as Dark Tyranitar and Shining Tyranitar, subject to any set restrictions.

## Using exact and general searches together

Set `active: true` on multiple entries. The scanner combines and de-duplicates all of their `search_terms`, searches Sendico, and checks every identified card against every active rule.

The included starter watchlist has:

- Ampharos EX 027/081 active;
- a Tyranitar Neo-era general-search example inactive.

Change the Tyranitar entry to `active: true` to run both searches together.

## Watchlist-only editing

Normal search changes now require editing only:

```text
data/watchlist.yaml
```

The legacy `sendico.search_terms` list in `config.yaml` is disabled by default. Search terms are taken from each active watchlist entry. If `search_terms` is omitted, the bot creates basic terms from the configured Pokemon names and card number.

Whenever the active watchlist changes, its signature changes. This allows previously scanned listings to be checked again under the new rules without deleting `data/seen.json`.

## Vision pipeline

The scanner uses Groq vision with locally prepared card crops:

```text
Sendico listing photos
    -> local OpenCV rectangle/grid detection
    -> perspective-corrected card crops
    -> perceptual-hash alternate-photo deduplication
    -> small JPEG contact-sheet batches
    -> Groq card identification
    -> local watchlist matching
    -> PriceCharting
    -> Discord
```

Target names and watchlist details are not included in the Groq prompt. Groq identifies the visible card, and the program applies exact/general matching locally. This avoids biasing identification and keeps prompts small.

## TPM protection

The default configuration is conservative for a limited Groq token-per-minute allowance:

```yaml
vision:
  crop_batch_size: 4
  request_spacing_seconds: 65
  contact_sheet_max_dimension_px: 1100
  max_completion_tokens: 1600
```

If Groq returns HTTP 413 because one request is too large, the batch is automatically divided. A one-card batch is retried once with a smaller compressed image. A normal HTTP 429 quota response stops the run cleanly so unprocessed listings can resume later.

## Listing deduplication and retry limit

The scanner stores listing state in `data/seen.json`.

- Successfully processed unchanged listings are skipped.
- Already-alerted unchanged listings are not alerted again.
- Retryable failures receive no more than three total attempts for the same listing and watchlist signature.
- The counter resets when the listing price, title, seller rating, images, or active watchlist changes.

## Discord alerts

Alerts now include a **Matched watchlist** field containing the IDs of the exact/general rules that matched the listing.

## Required GitHub secrets

Create these repository secrets under:

```text
Settings -> Secrets and variables -> Actions
```

```text
GROQ_API_KEY
DISCORD_WEBHOOK_URL
```

## Schedule

The workflow runs once each week at midnight at the start of Thursday in the `Australia/Sydney` time zone. Manual runs through **Actions -> Run workflow** are also allowed.

## Dependencies

GitHub Actions installs all dependencies from `requirements.txt`, including:

```text
numpy
opencv-python-headless
```
