# Provisional seller-rating patch

This patch lets listings continue through image analysis and pricing when Sendico does not expose the seller rating.

## Safety behaviour

- Verified seller rating below 301: rejected.
- Verified seller rating of 301 or more: can become a normal green deal alert.
- Unavailable seller rating: can only become an amber `MANUAL SELLER CHECK` alert.
- The 20% saving, Victini target confirmation and all card-pricing rules still apply.

## Upload through GitHub

1. Extract this ZIP on your computer.
2. Open `https://github.com/ThatSacco/Sendico-Market-Bot`.
3. Select **Add file > Upload files**.
4. Drag all extracted patch contents into the upload area. Keep the folder structure intact and allow the existing files to be replaced.
5. Commit directly to `main` with a message such as `Allow provisional seller verification alerts`.
6. Open **Actions > Scan Sendico Pokemon Deals > Run workflow**.

Do not upload the ZIP itself. Upload the extracted files and folders.

The workflow file is included at `.github/workflows/scan.yml` and also updates the official GitHub actions to Node 24-compatible major versions.
