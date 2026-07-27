# Gemini Test Mode Patch

This patch temporarily removes the normal deal restrictions so the full pipeline can be tested.

## What it does

- Uses `GEMINI_API_KEY` instead of `OPENAI_API_KEY`.
- Uses `gemini-2.5-flash` for listing-image analysis.
- Sends a **TEST MODE STARTED** Discord message as soon as the workflow reaches Discord.
- Processes up to three Sendico listings.
- Ignores seller rating, Victini detection, saving percentage, and previous scan history for diagnostic alerts.
- Sends a blue Discord result after a listing reaches the analysis stage.
- Sends a red Discord error message when a listing fails after being found.
- Keeps the production filters intact for when test mode is disabled.

## Upload

1. Extract the ZIP.
2. Open the extracted folder.
3. Upload the contents to the root of the GitHub repository.
4. Confirm the files replace existing files in `.github/workflows`, `src/pokemon_deal_bot`, and the repository root.
5. Commit directly to `main`.
6. Confirm the GitHub Actions repository secret is named exactly `GEMINI_API_KEY`.
7. Run the workflow manually.

## Expected Discord messages

- `TEST MODE STARTED`: GitHub Actions and the Discord webhook are working.
- `TEST MODE - Listing analysed`: Sendico, Gemini, pricing and Discord reached the result stage.
- `TEST MODE - Listing processing error`: Sendico found a listing, but a later component failed. The error is included in the message.

## Disable after testing

Change this in `config.yaml`:

```yaml
test_mode:
  enabled: false
```

Also change `sendico.max_listings_per_run` back to `12` when returning to normal operation.
