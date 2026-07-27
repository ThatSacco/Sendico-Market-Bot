# Fresh GitHub Upload

This package is a complete repository replacement, not an incremental patch.

## Before uploading

Do not delete the GitHub repository itself. Repository secrets are stored in GitHub settings and are not included in this ZIP.

Confirm these repository secrets still exist:

- `GROQ_API_KEY`
- `DISCORD_WEBHOOK_URL`

## Upload

1. Delete the existing repository files and folders from the `main` branch, or replace them all in one commit.
2. Extract this ZIP locally.
3. Upload every extracted item to the repository root, including the `.github` folder.
4. Commit the upload to `main`.
5. Open **Actions** and confirm **Test Sendico Market Bot** passes.
6. Manually run **Scan Sendico Pokemon Deals** once.

## Clean state included

The package contains fresh files:

- `data/seen.json` = `{}`
- `data/price_cache.json` = `{}`
- `reports/latest.json` = `[]`

The first run will therefore treat all Ampharos listings as unseen and fetch pricing again.

## Current watchlist

`data/watchlist.yaml` has Ampharos EX 027/081 active and the Tyranitar Neo-era example inactive.

## Normal schedule

The production workflow runs once per week at midnight at the start of Thursday in `Australia/Sydney`, with daylight-saving handling. Manual workflow runs are allowed at any time.
