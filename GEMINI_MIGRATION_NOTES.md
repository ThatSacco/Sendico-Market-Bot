# Migration summary

This release changes the production vision provider from Groq to Gemini while preserving the existing Sendico, OpenCV, quantity, pricing, state, and Discord pipelines.

## Main changes

- Adds `GeminiLotVisionAnalyzer` using the Gemini Interactions REST API.
- Uses `GEMINI_API_KEY` through the `x-goog-api-key` header.
- Sends each card-analysis request with `store: false`; no server-side conversation history is needed.
- Sets `gemini-3.6-flash` as primary and `gemini-3.5-flash-lite` as fallback.
- Sends one text item and one Base64 JPEG image item as multimodal input.
- Requests schema-constrained JSON, with a prompt-only JSON compatibility fallback.
- Uses low thinking effort to reduce latency and token cost for card extraction.
- Retries 429 and temporary server errors using provider retry guidance.
- Tracks input, output, inferred thinking, and total tokens.
- Raises the run caps to 100 listing analyses and 150 vision requests.
- Updates workflow, configuration, Discord wording, documentation, and tests.

The existing Groq implementation remains in `vision.py` only as dormant compatibility code for older imports and tests. `main.py` does not instantiate it and the GitHub Actions scan does not provide a Groq key.
