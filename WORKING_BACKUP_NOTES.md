# Stable Gemini Working Backup

This is the last proven pre-two-pass Gemini version assembled from the project update packages.

It includes Gemini API vision, genuine Tier 2 Pokemon lot searches, the 20-listing detailed-analysis cap, and Discord completion reporting. Generated state, cache, and report files have been reset so it can be restored cleanly.

No API keys or Discord webhook secrets are included.

Required GitHub Actions secrets:
- `GEMINI_API_KEY`
- `DISCORD_WEBHOOK_URL`

Restore by uploading the contents to the repository root, preserving paths, then run the test workflow before the scan workflow.
