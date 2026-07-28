# v5 changes

- Runs `pokemon_deal_bot.main` directly; `updated_main.py` remains only as a
  backwards-compatible import shim.
- Uses `data/watchlist.yaml` as the sole source of card names, card numbers,
  PriceCharting product URLs, active status and Sendico search terms.
- Supports unified watchlist search modes: `exact`, `focused_lot`, and
  `generic_lot`.
- Stops Sendico scrolling at 60 raw links per search and retains at most 25
  results per term.
- Runs up to 40 Flash-Lite screening calls and up to 12 detailed analyses,
  subject to the 125,000-token hard budget.
- Adds a 5,000-token reserve before starting each new Gemini request.
- Rejects detailed Gemini results confirmed as single-card listings.
- Skips PriceCharting entirely when the requested watchlist target is absent.
- Prices all recognised lot cards only after the target is confirmed.
- Ranks title-confirmed lots ahead of likely single-card listings.
- Uses seller-description/title evidence rather than recommendation-page
  boilerplate for the local lot check.
- Normalises printed numbers such as `027/081` and `27/81` to the same identity.
- Corrects the held-listing count when the listing cap or token budget pauses a
  run.
- Retains both manual GitHub runs and the Thursday-midnight Sydney schedule.
