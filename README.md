# Sendico Groq full-run fix

This package is based on the completed GitHub Actions log from 28 July 2026.
It replaces the earlier JSON-fallback package.

## Production changes

1. Keeps `service_tier: "on_demand"`.
2. Treats Groq's `Failed to validate JSON` / `failed_generation` response as a recoverable JSON-object-mode failure.
3. Retries the same Qwen vision model without `response_format`.
4. Remembers that fallback for the remainder of the run so later listings do not repeat the same failed JSON-mode call.
5. Filters automatic model discovery to likely vision models only. Text-only models such as Allam, Compound, Llama 3 and GPT-OSS are no longer probed with image content after Qwen reaches quota.

## Important limit

This update does not bypass Groq's token-per-day quota. If the available vision model has exhausted its daily allowance and no second vision-capable model is enabled for the account, the scan stops cleanly and resumes on the next run.
