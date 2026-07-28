# Change summary

## Search funnel

- Era/set lot searches run before generic searches.
- Default screening allocation: 70 era/set lots and 30 generic lots.
- Strong lot-language filtering remains enabled.

## Gemini funnel

- First pass: `gemini-3.5-flash-lite`, minimal thinking, up to four overview images.
- Probability threshold: 45%.
- Second pass: `gemini-3.6-flash`, up to 20 probable listings.
- Existing per-run request budget remains 150 requests.

## Multi-photo detailed analysis

The detailed pass includes the screening-relevant images plus the photos with the highest locally detected card counts. Perceptual hashing removes likely alternate-photo duplicates while retaining unique cards from separate overview photos.

## State rotation

A screened negative listing is recorded as processed. Listings held behind screening or detailed-analysis caps are not recorded and are reconsidered in later runs.
