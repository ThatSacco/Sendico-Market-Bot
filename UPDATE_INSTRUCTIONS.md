# Tier 2 two-pass lot-search update

Upload the contents of this folder to the root of the GitHub repository and replace matching files while preserving the folder paths.

No GitHub secret changes are required. Keep:

- `GEMINI_API_KEY`
- `DISCORD_WEBHOOK_URL`

## What changes

1. Tier 2 searches are split into higher-priority XY/EX/XY7/Bandit Ring lots and lower-priority generic Pokemon lots.
2. Up to 100 eligible lots are screened with `gemini-3.5-flash-lite` each run.
3. The screening pass checks up to four overview photos and only probable target listings continue.
4. Up to 20 probable listings receive detailed `gemini-3.6-flash` analysis.
5. Detailed analysis combines crops from several distinct overview photos instead of anchoring all quantity and value to one photo.
6. Negative screening results are saved in `data/seen.json`, allowing later candidates to rotate into subsequent runs.
7. The Discord completion summary reports era/generic candidates, screened listings, probable targets, detailed analyses and confirmed targets separately.

## First run expectations

The watchlist signature changes, so some previously seen listings may be reconsidered once. A normal completion summary should show separate counts for:

- Tier 2 era/set and generic candidates
- screened listings
- probable targets
- detailed analyses
- confirmed Tier 2 targets

## Validation

Run the normal GitHub Actions test workflow before the production scan.
