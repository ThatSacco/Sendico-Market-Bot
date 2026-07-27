# Unlimited Sendico Scan Update

This patch removes the configured limits on search results and listings processed.

## Install

1. Extract the ZIP.
2. Upload the **contents** of the extracted folder to the root of the GitHub repository.
3. Replace the matching files.
4. Commit directly to `main`.
5. Run the workflow manually from **Actions > Scan Sendico Pokemon Deals > Run workflow**.

## Behaviour

- `max_results_per_search: 0` means no configured result cap.
- `max_listings_per_run: 0` means process every unique listing found.
- `maximum_scroll_rounds: 0` means keep scrolling until the number of unique Sendico listings is unchanged for three consecutive rounds.
- The workflow timeout is increased to 180 minutes.
- The existing Monday and Thursday schedule remains enabled.

## Important

An unlimited scan may make up to two Gemini requests for every listing requiring two-pass analysis. Review Gemini usage after the first manual run.

To restore a cap later, set positive numbers in `config.yaml`, for example:

```yaml
sendico:
  max_results_per_search: 50
  max_listings_per_run: 25
  maximum_scroll_rounds: 10
```
