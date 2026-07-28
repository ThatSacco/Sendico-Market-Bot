# Gemini paid-vision update

## Upload

Upload the package contents to the repository root and allow matching files to be replaced. The new file `src/pokemon_deal_bot/gemini_vision.py` must retain that folder path.

## GitHub Actions secrets

In **Settings -> Secrets and variables -> Actions**, create or update:

```text
GEMINI_API_KEY
DISCORD_WEBHOOK_URL
```

The secret name must be exactly `GEMINI_API_KEY`. The production workflow no longer reads `GROQ_API_KEY`; remove the old secret after the Gemini scan succeeds.

## Recommended first run

1. Run the normal test workflow.
2. Confirm the test suite passes.
3. Manually run the scan workflow.
4. Check the log for `Trying Gemini model gemini-3.6-flash`.
5. Confirm the log shows `POST https://generativelanguage.googleapis.com/v1beta/interactions`.
6. Confirm the Discord completion summary shows the Gemini model and token usage.

## Expected fallback behaviour

- Temporary 429/5xx: retry the same model with backoff.
- Primary unavailable: move to `gemini-3.5-flash-lite`.
- Structured-output field rejected or unusable JSON returned: retry with prompt-only JSON.
- Invalid API key, disabled API, billing, or permission issue: stop with a clear authentication/billing error.
- Run limit reached: save state and stop cleanly so later listings can continue on the next run.
