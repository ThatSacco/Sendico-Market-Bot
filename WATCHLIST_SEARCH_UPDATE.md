# Watchlist-only manual search update

The manual GitHub workflow no longer accepts card names or Sendico search terms.
It asks for:

- the active `id` of the card in `data/watchlist.yaml`;
- a direct PriceCharting `/game/` product URL;
- the conservative result, screening and detailed-analysis limits.

The scanner reads the card name, Japanese name, printed number, set and Sendico
queries from the selected watchlist entry.

## Editing search terms

Edit only the selected card's `era_lot_search_terms` list:

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

    era_lot_search_terms:
      - "バンデットリング まとめ売り"
      - "XY7 まとめ売り"
```

Use one to four focused terms. The bounded manual workflow deliberately ignores
`generic_lot_search_terms`, preventing broad searches from silently increasing
token use.

## GitHub Actions input

Enter the exact watchlist id, for example:

```text
ampharos_ex_xy7_027
```

The workflow validates the id and search terms before opening Sendico.
