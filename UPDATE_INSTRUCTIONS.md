# Upload instructions — genuine Tier 2 lots

Upload the package contents to the root of the GitHub repository and replace the
matching files while preserving folder paths.

## Files changed

- `config.yaml`
- `data/watchlist.yaml`
- `src/pokemon_deal_bot/main.py`
- `src/pokemon_deal_bot/discord.py`
- `tests/test_config.py`
- `tests/test_main.py`
- `tests/test_discord.py`

## Secrets

No GitHub secret changes are required. Keep:

- `GEMINI_API_KEY`
- `DISCORD_WEBHOOK_URL`

## Expected next run

The normal exact-card marketplace searches are disabled for this test, so the
previous single-card alert list should not dominate the run. The completion
summary will include:

- Tier 2 candidates
- Tier 2 analysed
- Tier 2 rejected as non-lot
- Tier 2 held after cap
- Tier 2 lot matches

Run the GitHub Actions test workflow first, then manually run the scanner.
Expected local validation for this package: `90 passed`.
