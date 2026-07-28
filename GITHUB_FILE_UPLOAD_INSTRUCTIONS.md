# GitHub-only upload instructions

No local computer, PowerShell, installer, or patch script is required.

Replace or add these files in the repository using the GitHub website:

1. `config.yaml` — replace the complete file.
2. `data/run_limits.yaml` — add this new file.
3. `src/pokemon_deal_bot/config.py` — replace the complete file.
4. `tests/test_config.py` — replace the complete file.
5. `tests/test_repository_integrity.py` — replace the complete file.
6. `tests/test_v5_token_pipeline.py` — replace the complete file.
7. `RUN_LIMITS_GUIDE.md` — add this guide at the repository root.

Upload all files before rerunning Actions. Use the commit message:

`Centralise Sendico run limits in one YAML file`

After the Tests workflow passes, future tuning requires editing only:

- `data/watchlist.yaml` for cards and search wording;
- `data/run_limits.yaml` for run volume and token limits.
