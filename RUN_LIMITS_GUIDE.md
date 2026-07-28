# Central run limits guide

The bot now has two user-editable control files:

- `data/watchlist.yaml` — what cards to find, PriceCharting links, and Sendico search terms.
- `data/run_limits.yaml` — how much searching and Gemini processing one run may perform.

Do not add run caps back into `config.yaml`. The loader deliberately rejects duplicated limits so there is only one source of truth.

## Most commonly adjusted values

```yaml
search:
  results_per_term: 25
  total_listings_per_run: 50
  raw_links_per_term: 60

screening:
  max_listings_per_run: 100
  focused_lot_limit: 100
  generic_lot_limit: 10

detailed_analysis:
  max_listings_per_run: 30

token_budget:
  max_total_tokens_per_run: 125000
  reserve_per_request: 5000
  max_requests_per_run: 120
```

`detailed_analysis.max_listings_per_run` automatically controls both of the old detailed-analysis settings. You no longer need to keep a Tier 2 cap and a global vision cap aligned manually.

## Recommended profiles

### Balanced — supplied default

```yaml
screening:
  max_listings_per_run: 100
  focused_lot_limit: 100
  generic_lot_limit: 10

detailed_analysis:
  max_listings_per_run: 30

token_budget:
  max_total_tokens_per_run: 125000
  reserve_per_request: 5000
  max_requests_per_run: 120
```

### Larger run

```yaml
screening:
  max_listings_per_run: 150
  focused_lot_limit: 150
  generic_lot_limit: 15

detailed_analysis:
  max_listings_per_run: 45

token_budget:
  max_total_tokens_per_run: 150000
  reserve_per_request: 5000
  max_requests_per_run: 180
```

### Token-budget-only detailed processing

Count-based screening, detailed-analysis, and request caps may be set to `0` for unlimited. Keep the token ceiling enabled:

```yaml
screening:
  max_listings_per_run: 0
  focused_lot_limit: 0
  generic_lot_limit: 0

detailed_analysis:
  max_listings_per_run: 0

token_budget:
  max_total_tokens_per_run: 125000
  reserve_per_request: 5000
  max_requests_per_run: 0
```

Do not set the search collection controls to zero. `results_per_term`, `total_listings_per_run`, `raw_links_per_term`, and `max_scroll_rounds` must remain positive so Sendico cannot load its complete marketplace result set.

## Validation rules

The tests no longer require fixed values such as `40` or `100`. They check only that:

- search collection remains bounded;
- raw-link limits are not lower than retained-result limits;
- focused and generic screening caps do not exceed the overall screening cap;
- the single detailed-analysis setting is applied consistently to both runtime paths;
- the token reserve is lower than the total token budget;
- confidence thresholds and JPEG quality values are valid.

A valid change to `data/run_limits.yaml` therefore does not require any test-file change.
