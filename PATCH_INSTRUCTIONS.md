# Fixed two-pass Gemini patch

This patch fixes the `No listing images could be downloaded for Gemini analysis` error.

## What changed

1. Direct test listings are searched by their exact Mercari item code and enriched with the real Sendico search result.
2. A search result now replaces missing placeholder data instead of being ignored.
3. Sendico detail pages now check:
   - Open Graph and Twitter preview images
   - regular and lazy-loaded image attributes
   - `srcset` images
   - CSS background images
   - image URLs embedded in page data
4. The full Gemini two-pass files, Discord diagnostic functions and GitHub workflow are included together so the repository cannot end up with mixed versions.

## Upload

1. Extract the ZIP.
2. Open the extracted `sendico-two-pass-fixed-patch` folder.
3. Upload the **contents inside it** to the root of the GitHub repository.
4. Allow GitHub to replace all matching files.
5. Commit directly to `main`.
6. Confirm the repository secret `GEMINI_API_KEY` still exists.
7. Run `Scan Sendico Pokemon Deals` manually.

## Expected result

The Discord result should show the real listing title and one or more listing images. The two-pass result should include a note similar to:

`Two-pass Gemini analysis: ... enlarged crops sent in one second request ...`

## Disable later

Turn off two-pass image cropping:

```yaml
vision:
  two_pass_enabled: false
```

Return to normal deal restrictions:

```yaml
test_mode:
  enabled: false
```
