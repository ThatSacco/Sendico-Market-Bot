# Sendico Japanese Pokémon Deal Bot — Victini MVP

A GitHub Actions bot that:

1. Searches **Sendico Mercari only** for Japanese **Victini AR 097/086, SV11B Black Bolt** listings and lots.
2. Rejects sellers unless at least **301 positive ratings** can be verified on the listing page.
3. Uses image analysis to identify **all legible Japanese Pokémon cards** in the listing photographs.
4. Prices each confidently identified card from PriceCharting, converts values to **AUD**, and multiplies duplicates.
5. Calculates apparent savings using:

   `Sendico/Mercari listing price + Sendico service fee`

   Shipping, Japanese domestic freight, GST and condition discounts are deliberately excluded for this MVP.
6. Sends a Discord webhook alert when the identified lot value is at least **20% above acquisition cost** and the Victini target is confirmed.

## Important limitations

- This is an unofficial scraper. Sendico or PriceCharting can change their HTML and break it.
- The archived `sendibot` repository is not used as a dependency because its owner states Sendico backend changes made it non-functional. This project instead uses a browser-based adapter with broad DOM selectors.
- The PriceCharting module is rate-limited and cached, but automated scraping may be restricted by PriceCharting's terms. The supported long-term option is their official API.
- Image analysis can miss cards or misidentify them. A card is only priced when the model supplies an exact card number at or above the configured confidence threshold.
- Cards not identified exactly are assigned **A$0**. This keeps valuations conservative.
- Always inspect the original listing, seller profile, card condition and authenticity before purchasing.

## Repository setup

### 1. Create a GitHub repository

Create a private repository, upload all files from this folder, and commit them to the default branch.

### 2. Add repository secrets

Go to **Settings → Secrets and variables → Actions → New repository secret** and add:

- `DISCORD_WEBHOOK_URL` — your private Discord channel webhook URL.
- `OPENAI_API_KEY` — required to identify every visible card in lot photographs.

Never place either secret directly in `config.yaml`.

### 3. Enable workflow permissions

Go to **Settings → Actions → General → Workflow permissions** and select **Read and write permissions** so the workflow can persist `seen.json`, the price cache and the latest reports.

### 4. Test manually

Open **Actions → Scan Sendico Pokemon Deals → Run workflow**.

The scheduled workflow runs at minute 17 and 47 of every hour. These off-peak minutes reduce the chance of GitHub schedule delays.

## Local test

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .
playwright install chromium
pytest -q
OPENAI_API_KEY=... DISCORD_WEBHOOK_URL=... python -m pokemon_deal_bot.main --dry-run
```

## Watchlist

The current `data/watchlist.yaml` contains one card:

- Victini AR
- Japanese
- 097/086
- SV11B Black Bolt

The target has a direct PriceCharting URL to avoid ambiguous search matching. Additional cards detected in lots are searched by name, set and exact card number.

## Reports

Each workflow writes:

- `reports/latest.csv`
- `reports/latest.json`

The CSV shows qualifying and rejected listings, seller rating, identified value, apparent saving and rejection reasons.

## Configuration

Key settings in `config.yaml`:

```yaml
minimum_seller_positive_ratings: 301
minimum_saving_percent: 20.0
shipping_allowance_aud: 0.0
```

The Sendico fee is effective-dated:

- ¥500 before 1 August 2026
- ¥800 from 1 August 2026

## How lot valuation works

For each listing image, the image model returns cards with:

- English and Japanese card name
- set name and code
- exact card number
- quantity
- confidence
- broad condition note

Only Japanese cards with exact numbers and confidence of at least `0.78` are sent to PriceCharting. PriceCharting values are converted from USD to AUD using a live FX request, with configured fallback rates if that request fails.

The Discord alert lists up to the 15 highest-value identified card entries and reports the number of visible cards that could not be priced.

## If Sendico search stops working

The browser adapter is in `src/pokemon_deal_bot/sendico.py`. It intentionally uses generic selectors rather than Sendico's old signed API. If the search box or product-card structure changes, adjust `_submit_search` or the product anchor selector.

## Temporary seller-verification test mode

Sendico currently does not expose the Mercari seller's positive-rating count in the page text available to the scanner. The bot therefore supports a temporary provisional mode configured in `config.yaml`:

```yaml
seller_verification:
  analyse_unverified_sellers: true
  alert_provisional_deals: true
```

In this mode:

- A seller with a verified rating below 301 is still rejected immediately.
- A listing with an unavailable seller rating can proceed through image analysis and lot valuation.
- It can never be marked as a fully qualified deal.
- If every other rule passes, Discord receives an amber **MANUAL SELLER CHECK** alert.
- The alert instructs you to confirm at least 301 positive ratings before purchase.

Set both options to `false` once reliable seller-rating extraction is implemented.
