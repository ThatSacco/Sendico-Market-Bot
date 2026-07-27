# Two-pass Gemini lot-analysis patch

This patch tests the known Sendico lot:

`https://sendico.com/shop/mercari/catalog/m10381389468`

## What it changes

- Adds a two-pass Gemini method for lots and collections.
- Pass 1 reviews the original listing image and returns card bounding boxes.
- The bot crops and enlarges up to 16 cards locally using Pillow.
- Pass 2 sends all crops together in one Gemini request and identifies exact card numbers.
- Maximum Gemini calls for the test listing: **2**.
- Diagnostic mode sends one Discord result.
- The exact test listing is queued directly, so search ordering cannot select a single card first.

## Upload

1. Extract the ZIP.
2. Upload the contents to the root of the GitHub repository.
3. Allow the existing files to be replaced.
4. Commit directly to `main`.
5. Run `Scan Sendico Pokemon Deals` manually.

## Expected Discord result

Look for `Vision notes` containing text similar to:

`Two-pass Gemini analysis: 16 regions selected, 16 enlarged crops sent in one second request...`

The listing may still have unidentified cards if the original photo does not contain enough detail.

## Turn it off

In `config.yaml`:

```yaml
vision:
  two_pass_enabled: false
```

To stop diagnostic alerts and return to normal filtering:

```yaml
test_mode:
  enabled: false
```

Remove `direct_listing_urls` after the test.
