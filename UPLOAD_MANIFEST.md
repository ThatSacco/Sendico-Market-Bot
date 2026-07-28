# Upload manifest

Upload this package from the repository root and preserve every folder path.
Matching files should be replaced.

## Files included

- `.github/workflows/scan.yml`
- `config.yaml`
- `src/pokemon_deal_bot/config.py`
- `src/pokemon_deal_bot/discord.py`
- `src/pokemon_deal_bot/gemini_vision.py` (new)
- `src/pokemon_deal_bot/main.py`
- `src/pokemon_deal_bot/sendico.py`
- `src/pokemon_deal_bot/vision.py`
- `tests/test_discord.py`
- `tests/test_gemini_vision.py` (new)
- `tests/test_repository_integrity.py`
- `README.md`
- `UPDATE_INSTRUCTIONS.md`
- `GEMINI_MIGRATION_NOTES.md` (new)

## GitHub secret

Create or update the Actions secret named exactly:

`GEMINI_API_KEY`

Keep `DISCORD_WEBHOOK_URL`. After the Gemini scan succeeds, `GROQ_API_KEY`
can be removed.

## Optional cleanup

Delete the old root document `SERVICE_TIER_FIX.md` because it describes the
retired Groq service-tier workaround. Leaving it in the repository does not
affect the scanner, but it is no longer current documentation.
