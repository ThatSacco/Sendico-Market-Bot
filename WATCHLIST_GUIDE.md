# Editing searches

Edit only `data/watchlist.yaml` when changing cards or Sendico queries.

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
    pricecharting_url: >-
      https://www.pricecharting.com/game/pokemon-japanese-bandit-ring/ampharos-ex-27

    searches:
      - term: "XY7 まとめ売り"
        mode: focused_lot
        active: true

      - term: "バンデットリング まとめ売り"
        mode: focused_lot
        active: true
```

Modes:

- `exact`: the listing is expected to name the exact card.
- `focused_lot`: set/era-specific multi-card searches; recommended default.
- `generic_lot`: broad collection searches; use sparingly.

Each active card must have one to four active searches. Changing a search alters
the watchlist signature, allowing previously seen listings to be reconsidered.
