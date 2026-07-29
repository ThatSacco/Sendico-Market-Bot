# GitHub-only upload instructions

Add or replace these files through the GitHub website:

1. `config.yaml`
2. `data/run_limits.yaml`
3. `data/search_criteria.yaml` — new
4. `src/pokemon_deal_bot/config.py`
5. `tests/test_config.py`
6. `tests/test_repository_integrity.py`
7. `tests/test_v5_token_pipeline.py`
8. `SEARCH_CRITERIA_GUIDE.md` — new

Do not replace `data/watchlist.yaml`; keep your current card and search entries.

Commit all files together:

`Centralise search criteria and qualification settings`

Run the Tests workflow before running the scanner.
