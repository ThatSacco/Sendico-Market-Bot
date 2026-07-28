# Upload instructions

Do not upload the earlier `sendico-groq-json-fallback-update.zip` package.
Use this package instead.

From the extracted folder, upload these paths to the repository root and replace the existing files:

- `config.yaml`
- `src/pokemon_deal_bot/vision.py`
- `tests/test_groq_json_fallback.py`
- `tests/test_groq_vision_discovery.py`

Then run the GitHub Actions test workflow.

Expected test result for the reviewed codebase:

```text
82 passed
```

On the next scanner run, an intermittent Groq JSON failure should produce a warning similar to:

```text
Groq model qwen/qwen3.6-27b failed JSON object validation; retrying the same model with prompt-only JSON instructions
```

If Qwen reaches its daily quota, the bot should stop without trying the text-only account models.
