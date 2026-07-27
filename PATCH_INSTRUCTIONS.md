# Variant and multi-photo update

Upload the contents of this folder to the root of the GitHub repository and replace the matching files.

Files replaced:

- `config.yaml`
- `src/pokemon_deal_bot/models.py`
- `src/pokemon_deal_bot/vision.py`
- `src/pokemon_deal_bot/pricecharting.py`
- `src/pokemon_deal_bot/main.py`
- `src/pokemon_deal_bot/discord.py`
- three test files under `tests/`

After committing to `main`, manually run **Scan Sendico Pokemon Deals** once.

## Behaviour changes

- Scans up to 10 listings per run.
- Gemini reviews up to 12 Sendico listing photos.
- Up to 6 full listing photos are supplied with the enlarged crops in pass 2 to help verify foil variant and condition.
- Alternate photos are supporting evidence only and are not counted as extra cards.
- Every identified card defaults to `normal_holo`.
- `poke_ball`, `master_ball`, `reverse_holo`, or `other` is used only when Gemini explicitly confirms the special pattern from the images or listing text.
- PriceCharting premium-variant results are rejected unless the identified card has that same explicit variant.
- An unspecified `other` variant is left unpriced rather than guessed.
- Discord lists the variant beside every identified/priced card.
- Seller ratings may continue to require manual verification.

The twice-weekly Monday/Thursday GitHub Actions schedule is unchanged.
