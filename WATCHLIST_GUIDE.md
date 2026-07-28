# Watchlist-only Sendico searches

`data/watchlist.yaml` is now the only place that controls what the bot searches.

## Change a card

Edit or copy a card block under `cards:`. For an exact card, set:

```yaml
- id: unique_card_id
  active: true
  match_mode: exact_card
  english_name: "Card name"
  japanese_name: "Japanese name"
  set_name: "Set name"
  set_code: "Set code"
  card_number: "000/000"
  language: "Japanese"
  pricecharting_url: "https://www.pricecharting.com/game/..."
  searches:
    - term: "focused Japanese search wording"
      mode: focused_lot
      active: true
```

## Search modes

- `exact`: individual listings that name the exact card.
- `focused_lot`: set- or era-specific multi-card lots. This is the recommended default.
- `generic_lot`: broad collection searches. These are disabled in the example because they can produce high volumes.

Each active card must have between one and four active searches. The scanner stops before opening Sendico when the watchlist is invalid.

## Enable or disable a card/search

Set `active: false` on a card to ignore the entire card. Set `active: false` on one search to retain it as a template without running it.

## Run the scanner

The scan workflow is manual-only:

1. Commit the updated `data/watchlist.yaml`.
2. Open **Actions** in GitHub.
3. Select **Scan Sendico Pokemon Deals**.
4. Select **Run workflow**.

The GitHub form contains no card names or search terms, so it cannot drift away from the watchlist.

## Default safety limits

- 15 returned results per search.
- 40 raw links loaded before scrolling stops.
- 30 total listings per run.
- 15 Gemini screening calls.
- 3 detailed Gemini analyses.
- 30 total Gemini requests.

`config.yaml` controls these operational limits only. It does not contain search wording.
