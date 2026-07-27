# Groq weekly scanner update with three-attempt retry limit

Upload the contents of this folder to the root of the GitHub repository and replace matching files.

## Changed behaviour

- Groq remains the image-analysis provider.
- The workflow remains scheduled for Thursday at 12:00 AM in Sydney.
- An unchanged listing with a retryable failure receives no more than **three total attempts**.
- Retryable outcomes are processing errors and `seller rating unverified`.
- After attempt 3, the unchanged listing is skipped.
- A changed price, title, seller rating or image list creates a new fingerprint and resets the counter to attempt 1.
- Groq rate-limit interruptions are recorded as an attempt before the run pauses.
- Successful, rejected and already-alerted unchanged listings continue to be skipped immediately.

The limit is configured in `config.yaml`:

```yaml
retry_policy:
  max_attempts_per_listing: 3
```

After uploading, commit to `main` and manually run the workflow once.
