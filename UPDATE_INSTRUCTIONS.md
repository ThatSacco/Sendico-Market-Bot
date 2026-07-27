# Groq multi-model fallback update

Upload the contents of this ZIP to the repository root and replace matching files.

This update does not contain or replace:

- `data/seen.json`
- `data/price_cache.json`
- `data/watchlist.yaml`
- `reports/latest.json`
- `reports/latest.csv`

## What changed

- Accepts an ordered `vision.models` list instead of relying on one model.
- Uses the Groq Models API to discover models enabled for the API key.
- Switches to another model when one is rate-limited, unavailable, deprecated, permission-blocked, or incompatible with image input.
- Keeps the last successful model at the front of the pool for later batches.
- Applies the 65-second request spacing per model, so switching models does not create an unnecessary one-minute delay.
- Retries a model without `response_format` if that model accepts vision but not JSON mode.
- Counts every attempted fallback call against `max_groq_requests_per_run`.
- Shows completed model usage in the Discord scan summary.

## Configuration

The supplied `config.yaml` contains:

```yaml
vision:
  models:
    - "qwen/qwen3.6-27b"
  auto_discover_models: true
  max_model_attempts_per_request: 8
  service_tier: "auto"
```

You may add any Groq model ID enabled for the account. Automatically discovered models are appended. Models still need image-input support for card recognition; text-only models are skipped after their first compatibility error.

## After upload

1. Commit the replaced files to `main`.
2. Run **Test Sendico Market Bot**.
3. Confirm all tests pass.
4. Run **Scan Sendico Pokemon Deals** manually.
5. Review the log for `Trying Groq model ...` and the Discord completion summary for the models used.

Validation for this package: Python compilation passed and 78 automated tests passed.
