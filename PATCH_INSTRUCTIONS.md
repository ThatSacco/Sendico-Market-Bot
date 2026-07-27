# Audited repository update

This package is a complete replacement based on the latest Groq, multi-watchlist,
PriceCharting-reference, alternate-photo quantity, and graded-slab version.

## Critical correction

The public repository's scanner workflow was still configured for the old frequent
schedule and supplied `OPENAI_API_KEY`. The current Python code requires
`GROQ_API_KEY`. This package restores the intended workflow:

- Thursday at 12:00 AM in `Australia/Sydney`
- daylight-saving aware UTC triggers
- `GROQ_API_KEY`
- current GitHub Actions major versions
- 180-minute scanner timeout

## Additional safeguards

- Adds `.github/workflows/tests.yml` to compile and test the project on every push
  and pull request.
- Restores the full regression test suite.
- Repairs `data/price_overrides.csv` so it is valid CSV.
- Adds repository-integrity tests that detect a future workflow regression.

## Upload process

1. Extract this ZIP.
2. Upload every extracted file and folder to the repository root.
3. Replace matching files.
4. Preserve the existing `data/seen.json`, `data/price_cache.json`, and `reports/`
   files; they are not included here.
5. Commit the upload to `main`.
6. Confirm the new **Test Sendico Market Bot** workflow passes.
7. Confirm repository secrets include `GROQ_API_KEY` and `DISCORD_WEBHOOK_URL`.
8. Run **Scan Sendico Pokemon Deals** manually once.

## Expected validation

The local package passes source compilation and the full automated test suite.
