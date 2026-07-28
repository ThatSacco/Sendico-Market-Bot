# Complete Update Recommendations

## Recommended rollout

Keep the current controlled Ampharos EX `027/081` watchlist configuration for the first two supervised runs.

1. Merge this package into the current repository.
2. Run `python .\verify_complete_update.py` locally.
3. Push the update and confirm the GitHub test step passes.
4. Trigger one manual scan.
5. Confirm the Discord summary shows:
   - Searches attempted and failed.
   - Hydration failures.
   - Screening and detailed-analysis failures.
   - `COMPLETED`, `COMPLETED WITH ERRORS`, `PAUSED`, or `FAILED` accurately.
6. For any positive target result, compare the identified card against every supplied Sendico photo and the printed number `027/081`.
7. Confirm `reports/latest.json` contains the expected assessment and price source.
8. Repeat once before enabling additional cards or standard exact-card searches.

## Why the pipeline version is required

The current state signature is based only on the watchlist. An unchanged listing that exhausted retries under Groq or an earlier Gemini implementation can otherwise remain skipped after the code changes. The new pipeline version is included in state identity, so the existing `data/seen.json` can remain in place while the new scanner receives a clean retry scope.

Change `vision.pipeline_state_version` whenever any of the following materially changes:

- Vision provider.
- Primary/fallback model family.
- Screening prompt or structured response format.
- Image selection/deduplication behavior.
- Card-identification pipeline.

Do not change it for ordinary watchlist edits; watchlist changes are already included separately.

## Multi-image recommendation

The updated settings use six photos for screening and up to 12 for detailed analysis. This matches the current maximum listing-image download setting and is appropriate for genuine multi-photo lots.

Retain the existing limits initially:

- 40 local crops per listing.
- 4 crops per detailed Gemini batch.
- 100 detailed listing analyses per run.
- 150 Gemini requests per run.

Increase the crop cap only when the logs show all listing photos were selected but legitimate card regions were omitted due to the 40-crop ceiling.

## Failure handling recommendation

Treat the status as follows:

- **COMPLETED** — no recorded recoverable failures.
- **COMPLETED WITH ERRORS** — useful work completed, but some searches or listings failed.
- **PAUSED** — expected capacity/rate-limit/request-budget stop; remaining listings can resume later.
- **FAILED** — every search, every hydration attempt, or every Gemini attempt failed, so the workflow result should not be relied on.

GitHub Actions now receives exit code `1` for `FAILED`, while the `always()` state-persistence step still runs.

## Gemini API recommendation

Keep `v1beta` during this rollout because the current tests and response extraction are written against that endpoint and revision. Test stable `v1` separately after the controlled Gemini scans are clean. Do not combine an endpoint migration with the first multi-image production test.

## Discord and fee recommendation

The display now derives the yen fee from the same configuration used by deal assessment. Keep both configured periods correct even when the amount happens to be the same. This avoids a future mismatch between the displayed fee and the acquisition-cost calculation.

## Expansion after validation

After two clean supervised scans:

1. Add one additional exact-card target.
2. Keep the same confidence thresholds.
3. Review false positives and missed-photo cases.
4. Re-enable broader Tyranitar or era searches only after exact-card behavior remains stable.
5. Continue to manually verify seller rating, card condition, slab certification and authenticity before purchase.
