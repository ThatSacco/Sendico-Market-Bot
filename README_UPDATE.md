# Applying the manual bounded-search update

1. Extract the ZIP.
2. Copy all extracted files and folders into the root of the existing GitHub repository checkout.
3. Include the hidden `.github` folder.
4. Replace matching files.
5. Run:

```powershell
python .\verify_manual_update.py
```

6. Review changes:

```powershell
git status --short
git diff --check
git diff
```

7. Commit and push:

```powershell
git add .
git commit -m "Add manual bounded Sendico search inputs"
git push
```

After the push, use **Actions > Manual Sendico Pokemon Deal Search > Run workflow**.

The workflow will no longer run automatically each Thursday. This is intentional because the required search terms and PriceCharting URL must be supplied for every run.
