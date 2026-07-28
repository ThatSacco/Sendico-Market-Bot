# Review of current GitHub code

Reviewed against the current `main` branch documentation and the uploaded current copies of `vision.py`, `main.py`, and `config.yaml`.

## Already implemented

- Ordered Groq model pool.
- Groq `/models` account discovery.
- Per-model fallback for quota, permissions, deprecation, and image incompatibility.
- JSON-mode fallback.
- Per-model request pacing.
- Per-run request and listing-analysis budgets.
- Discord model-usage summary.

## Required update

The current configuration and Python defaults use `service_tier: auto`. The reported Groq HTTP 400 shows that this tier is unavailable for the organisation. This package changes the default to `on_demand`.

## Resilience update

When Groq rejects a service tier, the client now retries the same model in this order:

1. `on_demand` (when the original tier was different).
2. No `service_tier` field, allowing Groq to use its account default.
3. Normal model fallback if the request still fails for another reason.

## Recommendation corrected from today's discussion

The existing behaviour that disables a 429-limited model for the remainder of the current scan is sensible. It prevents repeatedly spending requests on a model whose quota is unavailable and immediately moves to the next model. This package leaves that behaviour unchanged.
