# Completed-run review

## Confirmed working

- Sendico searches completed.
- Result prefiltering worked.
- Listing hydration excluded unrelated recommendation thumbnails.
- Local card cropping and alternate-photo quantity anchoring worked.
- Groq model discovery worked.
- `service_tier: on_demand` worked; the earlier organisation-tier error is resolved.
- Qwen completed one vision result successfully and PriceCharting lookup ran.
- Discord completion summary was sent.

## Problems shown by the full run

### Intermittent JSON-object validation failure

The first two Qwen calls returned HTTP 400 with:

```text
Failed to validate JSON. Please adjust your prompt.
See 'failed_generation' for more details.
```

A later Qwen request succeeded, confirming that the model and image payload were valid and the JSON failure was intermittent.

### Text-only fallback calls

After Qwen reached its token-per-day quota, automatic discovery attempted seven text-only models. Each rejected the image message with:

```text
messages[0].content must be a string
```

Those models were available to the account but were not usable as vision fallbacks.

### Daily quota

The final Qwen response reported a 200,000 token-per-day limit with 199,860 already used. Code cannot bypass that account limit. The bot should stop once all actual vision models are unavailable.

## Validation

The revised files were installed into the reviewed repository test set and the full suite passed:

```text
82 passed
```
