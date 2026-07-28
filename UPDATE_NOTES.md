# Consolidated watchlist and search-quality update

This package applies the requested watchlist-only design and the preceding search-quality recommendations.

## Included

- One unified `searches` list per watchlist card.
- No automatic search-term generation.
- PriceCharting product links stored with exact-card entries.
- Manual-only GitHub scan workflow with no duplicated search inputs.
- Bounded Sendico scrolling and result limits.
- Query-only candidates disabled.
- Title-confirmed lots ranked ahead of obvious single-card listings.
- Lot evidence restricted to the listing title and isolated seller description.
- Gemini-confirmed single-card results prevented from reaching pricing/alerts.
- `27/81` and `027/081` treated as the same printed number.
- Watchlist changes included in the retry-state signature.
- Truthful Discord summary status and configured fee display.
- Current Tier 2 multi-image methods installed on the existing Gemini analyser path.

## Why `generic_screening_limit` is 3 rather than 0

In the existing `main.py`, zero means unlimited. Generic searches are disabled by default in the watchlist. If one is deliberately enabled, the value `3` provides a real safety cap.
