# Tier 2 Pokemon Lot Search Update

## Purpose

This update keeps the existing exact-card searches and adds a controlled Tier 2 search for multi-card listings that mention the desired Pokemon.

The current Ampharos test adds these marketplace terms:

- `デンリュウ まとめ`
- `デンリュウ セット`
- `デンリュウ ポケカ まとめ`
- `デンリュウ コレクション`
- `Ampharos Pokemon card lot`

Gemini must still identify **Ampharos EX 027/081** before the existing exact-card watchlist rule can match.

## Test limits

The initial configuration uses:

```yaml
sendico:
  tier2_lot_search:
    enabled: true
    max_results_per_search: 30
    max_analyses_per_run: 20
    allow_query_only_candidates: true
```

Normal watchlist results are processed first. At most 20 listings found only through Tier 2 searches are sent to Gemini in one run. The cap is applied after unchanged listings are skipped, so additional lot candidates rotate into later runs instead of the same previously processed candidates occupying the cap. Duplicate listings found by both normal and Tier 2 searches are merged and treated as normal watchlist results.

`allow_query_only_candidates: true` permits Gemini to inspect a Tier 2 result even when Sendico's shortened result text does not repeat the Pokemon name. The separate 20-listing cap limits the additional paid vision usage.

## Upload

Upload the contents of this package to the repository root, preserving all folder paths and replacing matching files.

The package does not contain or replace:

- `data/seen.json`
- reports
- PriceCharting cache files
- GitHub secrets

No new secret is required. Continue using `GEMINI_API_KEY` and `DISCORD_WEBHOOK_URL`.

## Expected log output

A run should include lines similar to:

```text
Searching Sendico Mercari [watchlist]: デンリュウEX 027/081
Searching Sendico Mercari [Tier 2 lot]: デンリュウ まとめ
Search found ... including ... Tier 2 lot candidate(s)
```

The Discord completion summary will also show:

```text
Tier 2 candidates
Tier 2 analysed
Tier 2 held after cap
```

## Validation

The packaged code was checked with:

```text
python -m compileall -q src
pytest -q
```

Result: **81 tests passed**.
