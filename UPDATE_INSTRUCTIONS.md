# Groq service-tier compatibility update

Upload the contents of this ZIP to the repository root and replace matching files.

This update does not contain or replace:

- `data/seen.json`
- `data/price_cache.json`
- `data/watchlist.yaml`
- `reports/latest.json`
- `reports/latest.csv`

## What changed

- Keeps the existing ordered `vision.models` pool and account model discovery.
- Changes the default Groq service tier from `auto` to `on_demand`.
- Retries the same model with `on_demand`, then with the service-tier field omitted, when an organisation rejects the configured tier.
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
  service_tier: "on_demand"
```

You may add any Groq model ID enabled for the account. Automatically discovered models are appended. Models still need image-input support for card recognition; text-only models are skipped after their first compatibility error.

## After upload

1. Commit the replaced files to `main`.
2. Run **Test Sendico Market Bot**.
3. Confirm all tests pass.
4. Run **Scan Sendico Pokemon Deals** manually.
5. Review the log for `Trying Groq model ...` and the Discord completion summary for the models used.

Validation for this package: Python compilation passed. Run the repository test workflow after upload to validate against the complete GitHub checkout.
