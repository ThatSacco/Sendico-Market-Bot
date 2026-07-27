# Sendico Japanese Pokemon Deal Bot

This bot searches Sendico's Mercari Pokemon listings, identifies Japanese raw cards, checks PriceCharting values, and posts qualifying results to Discord.

## Vision provider

The scanner uses Groq vision with the model:

```text
qwen/qwen3.6-27b
```

Each lot uses at most two Groq requests:

1. An overview request using up to three selected Sendico photos.
2. A crop-identification request using up to three labelled contact sheets containing the enlarged card crops.

If Groq returns a rate-limit response, the scanner stops cleanly. Already processed listings remain stored in `data/seen.json`, so later runs can continue with unprocessed listings.

## Required GitHub secrets

Create these repository secrets under:

```text
Settings -> Secrets and variables -> Actions
```

Required names:

```text
GROQ_API_KEY
DISCORD_WEBHOOK_URL
```

The previous `GEMINI_API_KEY` secret is no longer used.

## Schedule

The workflow runs once each week at midnight at the start of Thursday in the `Australia/Sydney` time zone.

Sydney alternates between AEST and AEDT. The workflow therefore schedules both possible UTC times and uses a timezone guard to allow only the trigger that is actually Thursday at 00:00 in Sydney.

Manual runs through **Actions -> Run workflow** are always allowed.

## Groq image limits

The code caps each Groq request at three images to match the current Qwen 3.6 model limit. The bot can still download up to 12 Sendico photos and selects the most useful overview images. Enlarged card crops are combined into labelled contact sheets so up to 16 cards can be analysed in one second request.

## Current search scope

The watchlist currently contains one target:

```text
Victini AR 097/086 - Black Bolt sv11B
```

The next planned update is self-service watchlist management, including adding and removing cards through Discord commands.

## Retry limit

The scanner stores listing state in `data/seen.json`. Retryable failures are limited to three total attempts for the same listing fingerprint. The counter resets only when the listing's price, title, seller rating or images change. Configure this in `config.yaml`:

```yaml
retry_policy:
  max_attempts_per_listing: 3
```
