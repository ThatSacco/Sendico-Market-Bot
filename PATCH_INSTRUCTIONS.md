# Crop identity and strict valuation fix

Upload the **contents of this folder** to the root of the GitHub repository and replace the existing files.

Files replaced:

- `config.yaml`
- `src/pokemon_deal_bot/main.py`
- `src/pokemon_deal_bot/vision.py`
- `src/pokemon_deal_bot/pricecharting.py`
- `src/pokemon_deal_bot/discord.py`
- the included test files

## Changes

- Pass 1 is now used only to locate card regions.
- Pass 1 card identities are discarded when enlarged crop results are available.
- Only one identity is accepted per physical crop.
- Identical cards from separate crops are combined as true duplicate quantities.
- PriceCharting results must match card name, printed card numerator, and Japanese set.
- Wrong-number or wrong-set PriceCharting matches are assigned no value.
- The Discord result includes `Lot value vs Sendico cost` in AUD.
- Sendico cost uses the listing price plus a fixed ¥800 service fee.
- Both pre- and post-1 August fee settings are set to ¥800.

After committing to `main`, manually rerun the workflow.

The current direct test listing should show a Sendico cost of approximately A$15.30 when the fallback JPY/AUD rate is 0.0102:

`(¥700 listing + ¥800 fee) × 0.0102 = A$15.30`
