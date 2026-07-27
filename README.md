# Sendico Japanese Pokémon Market Bot — Victini MVP

A GitHub Actions bot that:

1. Searches **Sendico Mercari only** for Japanese **Victini AR 097/086, SV11B Black Bolt** listings and lots.
2. Rejects a verified seller below **301 positive ratings**. Listings whose rating cannot be extracted can generate a clearly labelled provisional alert.
3. Uses Gemini image analysis to identify Japanese Pokémon cards in listing photographs.
4. Includes cards identified by Gemini at **95% confidence or higher**.
5. Accepts PriceCharting candidates at **95% price-match confidence or higher**, based on card name, printed number and Japanese set.
6. Converts all values to **AUD** and calculates:

   `PriceCharting lot value - (Mercari listing price + ¥800 Sendico fee)`

7. Sends a Discord alert whenever the requested target card is confirmed and priced. There is **no minimum saving or variance requirement**.
8. Runs automatically **twice per week**, on Monday and Thursday at 00:00 UTC.

Shipping, Japanese domestic freight, GST and condition adjustments remain excluded.

## Important limitations

- This is an unofficial scraper. Sendico or PriceCharting can change their pages and break collection.
- Gemini and PriceCharting matching can still be wrong. Review the original photographs, title and description before buying.
- The 95% PriceCharting rule still requires an exact English Pokémon name and printed card-number numerator plus a strong Japanese-set match.
- Cards that cannot reach 95% price-match confidence receive **A$0 value**.
- Seller ratings may remain unavailable through Sendico and must then be checked manually.

## Repository setup

### Secrets

Under **Settings → Secrets and variables → Actions**, add:

- `DISCORD_WEBHOOK_URL`
- `GEMINI_API_KEY`

### Workflow permissions

Under **Settings → Actions → General → Workflow permissions**, select **Read and write permissions** so the workflow can save scan state and reports.

### Manual run

Open **Actions → Scan Sendico Pokemon Deals → Run workflow**.

## Scheduled runs

The workflow runs:

```yaml
cron: "0 0 * * 1,4"
```

That is Monday and Thursday at 00:00 UTC, approximately 10:00 AEST or 11:00 AEDT in Sydney.

## Current watchlist

`data/watchlist.yaml` currently contains one active card:

- Victini AR
- Japanese
- SV11B Black Bolt
- 097/086

The current MVP still expects exactly one active target. The next development step is to make the watchlist fully self-service so cards can be added or removed in `data/watchlist.yaml`, with Japanese search phrases generated automatically.

## Discord valuation fields

Each target alert shows:

- Mercari listing price in JPY and AUD
- ¥800 Sendico fee in AUD
- Total Sendico cost in AUD
- Total PriceCharting lot value in AUD
- Price variance in AUD
- Price variance percentage relative to Sendico cost
- Cards priced at 95% confidence or higher
- Seller verification status

A positive variance means the PriceCharting value is above the Sendico cost. A negative variance means the PriceCharting value is below the Sendico cost.

## Reports

Each workflow writes:

- `reports/latest.csv`
- `reports/latest.json`

The reports include the total PriceCharting lot value, Sendico acquisition cost, AUD variance and percentage variance.

## Cost controls

`config.yaml` currently limits scans to six listings per run. A lot requires at most two Gemini calls: one overview request and one request containing the enlarged card crops. At two scheduled runs per week, the configured maximum is roughly 24 Gemini calls per week if all six listings require two-pass analysis.

To reduce usage:

```yaml
sendico:
  max_listings_per_run: 3
```

To disable two-pass lot analysis:

```yaml
vision:
  two_pass_enabled: false
```
