# Multi-watchlist exact/general update

Upload the contents of this folder to the root of the GitHub repository and replace matching files.

## What this update adds

- Multiple active watchlist entries at the same time.
- `match_mode: exact_card` for a precise card number.
- `match_mode: pokemon_general` for any card of a Pokemon.
- Optional set restrictions for general searches.
- Sendico search terms stored in `data/watchlist.yaml`.
- Local matching after Groq identifies cards.
- Discord displays the matching watchlist IDs.
- A watchlist edit resets deduplication for the new rules without deleting scan history.

## Important files

Replace all included files, especially:

```text
data/watchlist.yaml
config.yaml
src/pokemon_deal_bot/models.py
src/pokemon_deal_bot/config.py
src/pokemon_deal_bot/main.py
src/pokemon_deal_bot/vision.py
src/pokemon_deal_bot/state.py
src/pokemon_deal_bot/deal.py
src/pokemon_deal_bot/discord.py
```

The included `data/watchlist.yaml` has Ampharos EX active and a disabled Tyranitar Neo-era example. Change the Tyranitar entry to:

```yaml
active: true
```

to test both an exact card and a general Pokemon search together.

## Preserve scan history

Do not delete your existing:

```text
data/seen.json
data/price_cache.json
reports/
```

Those files are not included in this package. The new watchlist signature automatically allows old listings to be reassessed when your active rules change.

## Upload process

1. Extract this ZIP.
2. Upload all extracted contents to the repository root.
3. Allow GitHub to replace matching files.
4. Confirm `data/watchlist.yaml` exists.
5. Commit to `main`.
6. Open **Actions** and run the scanner manually once.

The weekly schedule remains Thursday at 12:00 AM Sydney time, with daylight-saving handling.
