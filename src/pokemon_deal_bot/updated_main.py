"""Backward-compatible entry point for the Sendico scanner.

The production workflow runs :mod:`pokemon_deal_bot.main` directly.  This module
keeps older workflows and tests working without importing private helper names
from ``main.py``.  The helper implementations intentionally live here so a
partial GitHub file upload cannot create another import-time failure.
"""

from __future__ import annotations

import re
import unicodedata
from importlib import import_module
from typing import Any

_LOT_MARKERS = (
    "まとめ売り",
    "大量",
    "引退品",
    "引退",
    "詰め合わせ",
    "セット販売",
    "lot",
    "bundle",
    "collection",
    "bulk",
    "assorted",
)
_DESCRIPTION_START = (
    "item description",
    "description",
    "商品説明",
    "商品の説明",
)
_DESCRIPTION_END = (
    "seller",
    "出品者",
    "shipping",
    "配送",
    "comments",
    "コメント",
    "recommended",
    "おすすめ",
    "related items",
    "商品の情報",
    "category",
    "カテゴリー",
)


def _compact(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _normalize_card_number(value: str | None) -> str:
    """Normalize printed numbers so 27/81 and 027/081 compare equally."""

    text = unicodedata.normalize("NFKC", str(value or ""))
    match = re.search(r"(\d{1,3})\s*/\s*(\d{1,3})", text)
    if not match:
        return ""
    numerator = str(int(match.group(1)))
    denominator = str(int(match.group(2)))
    return f"{numerator}/{denominator}"


def _number_tokens(value: str | None) -> set[str]:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return {
        token
        for match in re.finditer(r"\b\d{1,3}\s*/\s*\d{1,3}\b", normalized)
        if (token := _normalize_card_number(match.group(0)))
    }


def _contains_lot_marker(value: str | None) -> bool:
    compact = _compact(value)
    return any(_compact(marker) in compact for marker in _LOT_MARKERS)


def extract_seller_description(body_text: str, title: str = "") -> str:
    """Conservatively isolate the seller-authored description.

    Sendico pages may contain navigation and recommended-listing text.  If a
    clear description section cannot be found, returning an empty string is
    safer than allowing page boilerplate to qualify a listing as a lot.
    """

    lines = [line.strip() for line in str(body_text or "").splitlines() if line.strip()]
    if not lines:
        return ""

    title_folded = str(title or "").strip().casefold()
    start: int | None = None
    for index, line in enumerate(lines):
        folded = line.casefold().rstrip(":：")
        if folded in _DESCRIPTION_START or any(
            folded.startswith(marker + ":") for marker in _DESCRIPTION_START
        ):
            start = index + 1
            break

    if start is None:
        return ""

    captured: list[str] = []
    for line in lines[start:]:
        folded = line.casefold().rstrip(":：")
        if any(
            folded == marker or folded.startswith(marker + ":")
            for marker in _DESCRIPTION_END
        ):
            break
        if title_folded and line.casefold() == title_folded:
            continue
        captured.append(line)
        if sum(len(item) for item in captured) >= 3000:
            break

    return "\n".join(captured).strip()[:3000]


def strong_lot_evidence(
    listing: Any,
    configured_terms: list[str] | tuple[str, ...] | None = None,
) -> bool:
    """Use only the title and isolated seller description as lot evidence."""

    title = str(getattr(listing, "title", "") or "")
    description = str(getattr(listing, "description", "") or "")[:2000]
    haystack = " ".join([title, description])
    normalized = unicodedata.normalize("NFKC", haystack).casefold()

    explicit_single = bool(
        re.search(r"(?:カード\s*)?1\s*枚|one\s+card|single\s+card", normalized)
    )
    explicit_multiple = bool(
        re.search(
            r"(?:^|\D)(?:[2-9]|[1-9]\d{1,3})\s*(?:枚|cards?)(?:\D|$)",
            normalized,
        )
    )
    if explicit_single and not explicit_multiple:
        return False

    terms = [
        str(term).strip()
        for term in (configured_terms or _LOT_MARKERS)
        if str(term).strip()
    ]
    compact = _compact(haystack)
    if any(_compact(term) in compact for term in terms):
        return True
    return explicit_multiple


def candidate_relevance_score(listing: Any, targets: list[Any]) -> int:
    """Rank title-confirmed lots above likely single-card listings."""

    title = str(getattr(listing, "title", "") or "")
    seller_text = str(getattr(listing, "description", "") or "")[:500]
    result_text = str(getattr(listing, "raw_text", "") or "")[:700]
    haystack = _compact(" ".join([title, seller_text, result_text]))
    if not haystack:
        return 0

    title_lot = _contains_lot_marker(title)
    seller_lot = _contains_lot_marker(seller_text)
    title_numbers = _number_tokens(title)
    all_numbers = _number_tokens(" ".join([title, result_text]))
    best = 0

    for target in targets:
        score = 0
        names = [
            *list(getattr(target, "english_names", []) or []),
            *list(getattr(target, "japanese_names", []) or []),
        ]
        if not names:
            names = [
                str(getattr(target, "english_name", "") or ""),
                str(getattr(target, "japanese_name", "") or ""),
            ]

        name_match = any(
            compact_name and compact_name in haystack
            for compact_name in (_compact(name) for name in names)
        )
        if name_match:
            score += 60

        target_number = _normalize_card_number(
            str(getattr(target, "card_number", "") or "")
        )
        number_match = bool(target_number and target_number in all_numbers)
        if getattr(target, "match_mode", "exact_card") == "exact_card" and number_match:
            score += 100

        set_values = [
            str(getattr(target, "set_name", "") or ""),
            str(getattr(target, "set_code", "") or ""),
            *list(getattr(target, "accepted_sets", []) or []),
            *list(getattr(target, "accepted_set_codes", []) or []),
        ]
        if any(
            compact_set and compact_set in haystack
            for compact_set in (_compact(value) for value in set_values)
        ):
            score += 25

        if title_lot:
            score += 90
        elif seller_lot:
            score += 25

        if title_numbers and not title_lot:
            score -= 90
        if name_match and number_match and not title_lot:
            score -= 60

        best = max(best, score)

    if best <= 0 and title_lot:
        return 10
    return max(0, best)


def _main_module() -> Any:
    """Import the production runtime lazily.

    Keeping this import out of module initialisation lets helper tests run even
    while GitHub is validating a separate change to ``main.py``.
    """

    return import_module("pokemon_deal_bot.main")


async def run(config_path: str, dry_run: bool = False) -> int:
    """Delegate to the consolidated production runtime."""

    runtime = _main_module()
    return int(await runtime.run(config_path, dry_run))


def cli() -> None:
    """Delegate command-line execution to the consolidated runtime."""

    _main_module().cli()


__all__ = [
    "candidate_relevance_score",
    "extract_seller_description",
    "strong_lot_evidence",
    "cli",
    "run",
]


if __name__ == "__main__":
    cli()
