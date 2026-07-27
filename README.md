# Sendico Pokémon Bot — variant-safe pricing update

This patch prevents ordinary cards from being priced as premium Master Ball, Poké Ball, reverse-holo, or other special printings.

The default pricing assumption is **Normal/Holo**. A premium variant is only selected when Gemini explicitly identifies the special pattern using the card crop, listing text, or additional Sendico listing photographs.

The scanner now processes up to **10 listings per scheduled run** and reviews multiple listing photos to improve variant and condition checks.
