# Sendico Market Bot — Direct GitHub Update Package

This ZIP is a **direct repository overlay** for:

`ThatSacco/Sendico-Market-Bot`

It does not contain an updater or patching program. Every file is already located at its final GitHub path. Copy the contents over the root of the existing repository and allow the listed replacement files to overwrite their current versions.

## Repository structure supplied

```text
.github/
  workflows/
    scan.yml                         replacement
src/
  pokemon_deal_bot/
    __init__.py                      replacement
    tier2_vision.py                  new
    updated_main.py                  new
tests/
  test_complete_update.py            new
config.yaml                           replacement
verify_complete_update.py             new
UPDATE_PACKAGE_README.md               new
UPDATE_MANIFEST.md                     new
COMPLETE_UPDATE_RECOMMENDATIONS.md     new
```

All other existing repository files remain unchanged, including `main.py`, `gemini_vision.py`, `vision.py`, `sendico.py`, the watchlist, state files, reports and pricing logic.

## Install over the existing repository

1. Download and extract this ZIP.
2. Open the extracted folder.
3. Copy **all contents**, including the hidden `.github` folder, into the root of your existing `Sendico-Market-Bot` checkout.
4. Select **Replace files in the destination** for:
   - `config.yaml`
   - `.github/workflows/scan.yml`
   - `src/pokemon_deal_bot/__init__.py`
5. Do not delete existing files that are not included in this package.

The final repository should still contain the existing files such as:

```text
pyproject.toml
requirements.txt
data/watchlist.yaml
src/pokemon_deal_bot/main.py
src/pokemon_deal_bot/gemini_vision.py
src/pokemon_deal_bot/vision.py
```

## Verify before committing

From PowerShell in the repository root:

```powershell
python .\verify_complete_update.py
```

The verification script checks:

- Required original and update files are present.
- GitHub Actions points to the updated runtime entry point.
- Configuration references and image limits are correct.
- Python source and tests compile.
- The missing Tier 2 methods are available on the existing Gemini class import path.
- The complete `pytest` suite passes.

You can perform the structural checks without running pytest using:

```powershell
python .\verify_complete_update.py --skip-tests
```

## Review and push

```powershell
git status --short
git diff --check
git diff
python .\verify_complete_update.py
git add .
git commit -m "Complete Gemini Tier 2 reliability update"
git push
```

After pushing, run **Actions → Scan Sendico Pokemon Deals → Run workflow** once manually and review the Discord completion summary and `reports/latest.json`.

## Rollback

Before copying the package, create a branch or commit the current state:

```powershell
git switch -c backup-before-complete-update
git add .
git commit -m "Backup before complete Sendico update"
git switch main
```

Alternatively, after applying but before pushing, restore the changed files with Git:

```powershell
git restore config.yaml .github/workflows/scan.yml src/pokemon_deal_bot/__init__.py
git clean -fd
```

Review `git clean -fdn` first if the repository contains other untracked work.
