# Production pricing and twice-weekly schedule update

Upload the contents of this patch to the root of the GitHub repository and replace the existing files.

This update:

- switches `test_mode` off;
- removes the 20% saving requirement;
- alerts on confirmed target listings regardless of positive or negative variance;
- prices Japanese cards identified by Gemini at 95% confidence or higher;
- accepts PriceCharting matches at 95% confidence or higher;
- shows total PriceCharting lot value, total Sendico cost and AUD/% variance;
- fixes the ¥800 Sendico fee;
- runs Monday and Thursday at 00:00 UTC;
- limits each run to six listings to control Gemini usage;
- preserves the existing Gemini and Discord secrets.

After committing the files, run the workflow manually once to verify the production alert format.

The next planned update is multi-card watchlist support: add or remove cards in `data/watchlist.yaml` without manually editing `config.yaml` search terms.
