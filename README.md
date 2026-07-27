# Sendico Japanese Pokemon Deal Bot

This bot searches Sendico's Mercari Pokemon listings, identifies Japanese raw cards, checks PriceCharting values, and posts qualifying results to Discord.

## Vision pipeline

The scanner uses Groq vision with:

```text
qwen/qwen3.6-27b
```

The previous two-pass Groq overview/crop workflow has been removed. The current pipeline is:

```text
Sendico listing photos
    -> local OpenCV rectangle/grid detection
    -> perspective-corrected card crops
    -> perceptual-hash alternate-photo deduplication
    -> small JPEG contact-sheet batches
    -> Groq card identification
    -> PriceCharting
    -> Discord
```

Overview photos and full listing descriptions are no longer sent to Groq. Every Groq request contains one compressed contact-sheet image and a short identification prompt.

## TPM protection

The default configuration is deliberately conservative for a Groq account with an 8,000-token-per-minute limit:

```yaml
vision:
  crop_batch_size: 4
  request_spacing_seconds: 65
  contact_sheet_max_dimension_px: 1100
  max_completion_tokens: 1600
```

If Groq returns HTTP 413 because one request is too large, the batch is automatically divided into smaller batches. A one-card batch is retried once with a smaller, more compressed image. A normal HTTP 429 quota response still stops the run cleanly so unprocessed listings can resume later.

Because batches are intentionally spaced by 65 seconds, large card lots take longer to process. The weekly workflow retains a 180-minute timeout.

## Local card handling

The local preprocessor:

- detects rotated card rectangles using OpenCV contours;
- detects aligned card grids using long horizontal and vertical border lines;
- recognizes a full-frame single-card close-up;
- perspective-corrects and compresses each crop;
- uses perceptual hashes to remove alternate-photo views;
- preserves two identical physical cards when they appear together in the same overview photo;
- can replace an overview crop with a sharper matching close-up from another listing photo.

The rectangle and deduplication thresholds can be adjusted in `config.yaml`.

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

The previous `GEMINI_API_KEY` secret is not used.

## Schedule

The workflow runs once each week at midnight at the start of Thursday in the `Australia/Sydney` time zone.

Sydney alternates between AEST and AEDT. The workflow schedules both possible UTC times and uses a timezone guard so only the trigger that is actually Thursday at 00:00 in Sydney proceeds.

Manual runs through **Actions -> Run workflow** are always allowed.

## Current search scope

The active watchlist currently contains:

```text
Victini AR 097/086 - Black Bolt sv11B
```

## Listing deduplication and retry limit

The scanner stores listing state in `data/seen.json`.

- Successfully processed unchanged listings are skipped.
- Already-alerted unchanged listings are not alerted again.
- Retryable failures receive no more than three total attempts for the same fingerprint.
- The counter resets when the listing price, title, seller rating, or image list changes.

Configure the retry limit in `config.yaml`:

```yaml
retry_policy:
  max_attempts_per_listing: 3
```

## New dependencies

The local vision stage adds:

```text
numpy
opencv-python-headless
```

GitHub Actions installs them automatically from `requirements.txt`.
