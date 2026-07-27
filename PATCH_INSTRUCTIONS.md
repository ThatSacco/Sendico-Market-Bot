# Sendico timeout fix

Upload the contents of this folder to the root of the GitHub repository and replace the existing files.

This patch:
- skips the Sendico category search when `test_mode.direct_listing_urls` is present;
- hydrates the direct listing from its own listing page;
- catches ordinary Sendico search timeouts so one failed search does not stop the workflow;
- continues when Sendico commits a page but does not finish `domcontentloaded`;
- updates the Frankfurter FX endpoint and follows redirects.

After committing to `main`, manually rerun the GitHub Action.
