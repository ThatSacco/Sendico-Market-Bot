# Tier 2 genuine-lot search update

This update changes the Tier 2 test from **Pokemon-name-plus-lot** searches to
**generic and XY-era multi-card lot** searches.

## Why the previous test returned single cards

The previous Tier 2 queries still contained `デンリュウ` or `Ampharos`.
Sendico/Mercari therefore continued to prioritise listings whose main subject was
one Ampharos card. The normal exact-card searches also remained enabled, so the
same known single-card alerts continued to appear.

## New test behaviour

For this controlled test:

- normal exact-card marketplace searches are temporarily disabled;
- Tier 2 searches use generic Pokemon-card lot terms and XY/Bandit Ring terms;
- a hydrated Tier 2 result must contain strong multi-card wording such as
  `まとめ売り`, `大量`, `引退品`, `詰め合わせ`, `lot`, `bundle`, or an explicit
  count such as `20枚` before Gemini tokens are spent;
- no more than 20 genuine Tier 2 candidates are analysed per run;
- Gemini must still identify **Ampharos EX 027/081** before an alert qualifies;
- the Discord completion summary reports Tier 2 non-lots rejected and Tier 2
  lot matches separately.

## Search terms used

- `ポケカ まとめ売り`
- `ポケモンカード まとめ売り`
- `ポケカ 引退品`
- `ポケカ 大量`
- `ポケカ XY まとめ売り`
- `バンデットリング まとめ売り`

## Current limitation

This update tests whether broader search discovery produces real multi-card
listings within the Gemini budget. The existing image pipeline still reconciles
alternate photos conservatively and may not inspect every distinct page of a
large collection. If genuine lots are found but the target is rarely detected,
the next update should add dedicated multi-image lot mode.
