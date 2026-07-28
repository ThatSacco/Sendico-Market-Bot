# Sendico Market Bot - Manual Bounded Search Update

## Why this update is required

The previous Tier 2 workflow generated several broad Japanese searches automatically. Although `max_results_per_search` limited how many parsed results were retained, the browser still scrolled until the Sendico page stopped producing links. A single term could therefore load more than 1,500 raw links before only a small subset was retained.

The scan log then selected 284 listings, allowed up to 100 Gemini screening requests and exceeded 350,000 cumulative tokens before completion.

## New operating model

The scheduled search has been removed. Every scan is started manually from GitHub Actions and requires:

- exact English card name;
- optional Japanese card name;
- printed card number;
- set name and optional set code;
- one to four search terms chosen by the user;
- a direct PriceCharting `/game/` product URL;
- explicit result, screening and detailed-analysis limits.

The workflow sends a Discord **scan started** message immediately, including the terms and hard caps. Existing deal alerts and the end-of-run summary remain enabled.

## Default limits

- Search terms: maximum 4
- Retained results per term: 15
- Raw links loaded per term: approximately 30, hard maximum 40
- Scroll rounds: maximum 5
- Total candidate listings: terms multiplied by results per term
- Gemini screenings: 15
- Detailed analyses: 3
- Screening photos: 3
- Detailed photos: 8
- Vision requests: bounded to 40 or fewer

These values can be reduced in the GitHub run form. The UI does not offer values above the hard limits.

## Recommended search terms

Use focused Japanese lot terms rather than broad generic searches. For Ampharos EX 027/081, examples are:

- `バンデットリング まとめ売り`
- `XY7 まとめ売り`
- `デンリュウEX まとめ売り`

Avoid terms such as `ポケカ まとめ売り`, `ポケカ 大量` or `ポケカ 引退品` unless you deliberately want a wide and expensive search.

## How to run

1. Open the repository in GitHub.
2. Select **Actions**.
3. Select **Manual Sendico Pokemon Deal Search**.
4. Select **Run workflow**.
5. Complete every required field.
6. Start with 10 or 15 results per term, 10 or 15 screenings, and 3 detailed analyses.

## PriceCharting input

The URL must be a direct product page such as:

`https://www.pricecharting.com/game/pokemon-japanese-bandit-ring/ampharos-ex-27`

Search-result URLs and category URLs are rejected before the scanner starts.

## Files changed

- `.github/workflows/scan.yml`
- `config.yaml`
- `src/pokemon_deal_bot/manual_main.py`
- `tests/test_manual_main.py`
- `tests/test_repository_integrity.py`

The package also retains the prior reliability and Tier 2 files so it can be applied as one complete overlay.
