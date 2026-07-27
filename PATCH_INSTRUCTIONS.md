# Local-crop Groq update

Upload the contents of this folder to the root of the GitHub repository and replace matching files.

## Important

This is a replacement for the previous Groq weekly retry package. Upload **all** included files, including the new file:

```text
src/pokemon_deal_bot/image_processing.py
```

Also replace:

```text
src/pokemon_deal_bot/vision.py
src/pokemon_deal_bot/main.py
config.yaml
requirements.txt
pyproject.toml
tests/test_vision.py
README.md
```

## Changed behaviour

- Removes the Groq overview pass entirely.
- Detects card rectangles and aligned grids locally with OpenCV.
- Sends only perspective-corrected card crops to Groq.
- Sends one compressed contact-sheet image per request.
- Uses four crops per request by default.
- Waits 65 seconds between Groq requests to avoid overlapping free-tier TPM windows.
- Automatically splits an HTTP 413 oversized batch into smaller requests.
- Omits the full listing description from Groq prompts.
- Removes duplicate alternate-photo views using perceptual hashes.
- Preserves the weekly Thursday 12:00 AM Sydney schedule.
- Preserves the three-total-attempt retry limit and `seen.json` deduplication.

## Upload process

1. Extract this ZIP.
2. Upload the extracted contents to the repository root.
3. Allow GitHub to replace matching files.
4. Confirm `image_processing.py` appears under `src/pokemon_deal_bot/`.
5. Commit to `main`.
6. Run the workflow manually once from the **Actions** tab.

Do not delete your existing `data/seen.json`, `data/price_cache.json`, or reports unless you intentionally want to reset history.
