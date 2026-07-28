# Current Gemini Two-Pass Working Copy

This is the complete assembled two-pass Gemini version. It adds Flash-Lite broad screening, Flash detailed analysis, era/set and generic Tier 2 lot pools, and multi-overview-photo screening.

Generated state, cache, and report files have been reset. No API keys or Discord webhook secrets are included.

Required GitHub Actions secrets:
- `GEMINI_API_KEY`
- `DISCORD_WEBHOOK_URL`

Restore by uploading the contents to the repository root, preserving paths, then run the test workflow before the scan workflow.
