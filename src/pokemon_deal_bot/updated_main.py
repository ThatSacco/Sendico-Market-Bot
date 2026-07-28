from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import re
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass, replace
from typing import Any, Iterator

from . import discord as discord_module
from . import main as legacy_main
from . import vision as vision_module
from .config import (
    load_config,
    load_watchlist,
    validate_watchlist_for_run,
)
from .deal import sendico_fee_jpy
from .gemini_vision import GeminiLotVisionAnalyzer
from .models import normalize_card_number
from .sendico import SendicoMercariScanner
from .vision import VisionRateLimitError, VisionRunBudgetReached

LOGGER = logging.getLogger(__name__)

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


@dataclass(slots=True)
class RuntimeTelemetry:
    search_attempts: int = 0
    search_errors: int = 0
    hydration_attempts: int = 0
    hydration_errors: int = 0
    screening_attempts: int = 0
    screening_successes: int = 0
    screening_errors: int = 0
    detailed_attempts: int = 0
    detailed_successes: int = 0
    detailed_errors: int = 0
    single_listings_rejected: int = 0
    assessments: int = 0
    processing_errors: int = 0
    paused: bool = False

    @property
    def vision_attempts(self) -> int:
        return self.screening_attempts + self.detailed_attempts

    @property
    def vision_successes(self) -> int:
        return self.screening_successes + self.detailed_successes

    @property
    def total_errors(self) -> int:
        return (
            self.search_errors
            + self.hydration_errors
            + self.screening_errors
            + self.detailed_errors
            + self.processing_errors
        )


def _compact(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _contains_lot_marker(value: str) -> bool:
    compact = _compact(value)
    return any(_compact(marker) in compact for marker in _LOT_MARKERS)


def _number_tokens(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return {
        normalize_card_number(match.group(0))
        for match in re.finditer(r"\b\d{1,3}\s*/\s*\d{1,3}\b", normalized)
    }


def extract_seller_description(body_text: str, title: str = "") -> str:
    """Conservatively isolate the seller description from Sendico page text.

    The previous scanner copied the complete page body into ``description``. That
    allowed navigation, recommendation cards and seller boilerplate to satisfy the
    lot-evidence filter. If a clear description section cannot be isolated, return
    an empty string rather than treating unrelated page text as seller evidence.
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
        if any(folded == marker or folded.startswith(marker + ":") for marker in _DESCRIPTION_END):
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

    haystack = " ".join([str(listing.title or ""), str(listing.description or "")[:2000]])
    terms = [str(term).strip() for term in (configured_terms or _LOT_MARKERS) if str(term).strip()]
    compact = _compact(haystack)
    if any(_compact(term) in compact for term in terms):
        return True
    normalized = unicodedata.normalize("NFKC", haystack).casefold()
    return bool(
        re.search(r"(?:^|\D)(?:[2-9]|[1-9]\d{1,3})\s*(?:枚|cards?)(?:\D|$)", normalized)
    )


def candidate_relevance_score(listing: Any, targets: list[Any]) -> int:
    """Rank title-confirmed lots first and penalise obvious single-card titles."""

    title = str(listing.title or "")
    seller_text = str(listing.description or "")[:500]
    result_text = str(listing.raw_text or "")[:700]
    haystack = _compact(" ".join([title, seller_text, result_text]))
    if not haystack:
        return 0

    title_lot = _contains_lot_marker(title)
    seller_lot = _contains_lot_marker(seller_text)
    title_numbers = _number_tokens(title)
    best = 0
    for target in targets:
        score = 0
        names = [*target.english_names, *target.japanese_names]
        name_match = any(
            compact_name and compact_name in haystack
            for compact_name in (_compact(name) for name in names)
        )
        if name_match:
            score += 60

        target_number = normalize_card_number(target.card_number)
        number_match = bool(target_number and target_number in _number_tokens(" ".join([title, result_text])))
        if target.match_mode == "exact_card" and number_match:
            score += 100

        set_values = [
            target.set_name,
            target.set_code,
            *target.accepted_sets,
            *target.accepted_set_codes,
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
            # A title naming one printed card is usually a single-card listing.
            score -= 90
        if name_match and number_match and not title_lot:
            score -= 60
        best = max(best, score)

    if best <= 0 and title_lot:
        return 10
    return max(0, best)


async def bounded_scroll_results(self: Any, page: Any) -> None:
    """Stop scrolling when the useful raw-link allowance has been reached."""

    result_limit = max(1, int(self.config.get("max_results_per_search", 15)))
    configured_raw_limit = int(self.config.get("max_raw_links_per_search", 0) or 0)
    raw_limit = configured_raw_limit or min(40, max(20, result_limit * 2))
    maximum_rounds = max(1, int(self.config.get("maximum_scroll_rounds", 5)))
    stable_required = max(1, int(self.config.get("stable_scroll_rounds_before_stop", 2)))
    pause_ms = max(250, int(self.config.get("scroll_pause_ms", 1200)))

    previous_count = -1
    stable_rounds = 0
    for round_number in range(maximum_rounds + 1):
        current_count = await page.locator(
            'a[href*="/shop/mercari/catalog/"]'
        ).evaluate_all(
            """
            (anchors) => new Set(
              anchors.map((a) => a.href || '')
                .filter((href) => href && !href.includes('/categories/'))
            ).size
            """
        )
        LOGGER.info(
            "Sendico bounded load round %d: %d unique links (stop at %d)",
            round_number,
            current_count,
            raw_limit,
        )
        if current_count >= raw_limit:
            LOGGER.info("Reached raw-link search limit of %d", raw_limit)
            return
        if current_count <= previous_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        if stable_rounds >= stable_required:
            LOGGER.info("Sendico results stabilised at %d unique links", current_count)
            return
        if round_number >= maximum_rounds:
            LOGGER.info("Reached Sendico scroll limit of %d rounds", maximum_rounds)
            return
        previous_count = current_count
        load_more = page.get_by_role(
            "button",
            name=re.compile(r"load more|show more|more results|もっと見る", re.IGNORECASE),
        ).first
        try:
            if await load_more.count() and await load_more.is_visible():
                await load_more.click()
        except Exception:  # noqa: BLE001
            pass
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(pause_ms)


def versioned_scan_signature(base_signature: str, vision_config: dict[str, Any]) -> str:
    models_raw = vision_config.get("models") or []
    models = [models_raw] if isinstance(models_raw, str) else [
        str(value).strip() for value in models_raw if str(value).strip()
    ]
    identity = {
        "watchlist_signature": base_signature,
        "pipeline_state_version": str(
            vision_config.get("pipeline_state_version", "watchlist-only-bounded-v4")
        ),
        "provider": str(vision_config.get("provider", "gemini")),
        "models": models,
        "api_version": str(vision_config.get("api_version", "v1beta")),
    }
    serialized = json.dumps(identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def systemic_failure_reason(telemetry: RuntimeTelemetry, *, has_direct_urls: bool) -> str | None:
    if telemetry.paused:
        return None
    if telemetry.search_attempts and telemetry.search_errors == telemetry.search_attempts and not has_direct_urls:
        return "Every Sendico search failed; no reliable marketplace scan completed."
    if telemetry.hydration_attempts and telemetry.hydration_errors == telemetry.hydration_attempts:
        return "Every selected listing failed during detail-page hydration."
    if telemetry.vision_attempts and telemetry.vision_successes == 0:
        return "Every Gemini screening or detailed-analysis attempt failed."
    return None


def _replace_fee_text(value: Any, fee_jpy: int) -> Any:
    if isinstance(value, str):
        return value.replace("¥800", f"¥{fee_jpy:,}")
    if isinstance(value, list):
        return [_replace_fee_text(item, fee_jpy) for item in value]
    if isinstance(value, dict):
        return {key: _replace_fee_text(item, fee_jpy) for key, item in value.items()}
    return value


def decorate_summary_embed(
    embed: dict[str, Any],
    telemetry: RuntimeTelemetry,
    summary: dict[str, Any],
    *,
    has_direct_urls: bool,
) -> dict[str, Any]:
    telemetry.processing_errors = max(
        telemetry.processing_errors,
        int(summary.get("errors", 0) or 0),
    )
    stop_reason = str(summary.get("stop_reason") or "").strip()
    if stop_reason:
        telemetry.paused = True
    failure_reason = systemic_failure_reason(telemetry, has_direct_urls=has_direct_urls)
    if stop_reason or telemetry.paused:
        embed["title"] = "SENDICO SCAN PAUSED"
        embed["color"] = 0xF1C40F
    elif failure_reason:
        embed["title"] = "SENDICO SCAN FAILED"
        embed["description"] = failure_reason[:4000]
        embed["color"] = 0xE74C3C
    elif telemetry.total_errors:
        embed["title"] = "SENDICO SCAN COMPLETED WITH ERRORS"
        embed["color"] = 0xE67E22

    fields = embed.get("fields")
    if isinstance(fields, list):
        for field in fields:
            if not isinstance(field, dict):
                continue
            if field.get("name") == "Listings":
                existing = str(field.get("value") or "")
                field["value"] = (
                    f"Searches attempted: **{telemetry.search_attempts}**\n"
                    f"Search failures: **{telemetry.search_errors}**\n"
                    f"Hydration failures: **{telemetry.hydration_errors}**\n"
                    f"Gemini-confirmed singles rejected: **{telemetry.single_listings_rejected}**\n"
                    f"{existing}"
                )[:1024]
    return embed


def _mark_pause(telemetry: RuntimeTelemetry, exc: BaseException) -> None:
    if isinstance(exc, (VisionRateLimitError, VisionRunBudgetReached)):
        telemetry.paused = True


@contextmanager
def _runtime_patches(*, config: Any, telemetry: RuntimeTelemetry) -> Iterator[None]:
    vision_config = dict(config.raw.get("vision", {}) or {})
    test_config = dict(config.raw.get("test_mode", {}) or {})
    has_direct_urls = any(str(value).strip() for value in test_config.get("direct_listing_urls", []))
    fee_jpy = sendico_fee_jpy(dict(config.raw.get("sendico_fee", {}) or {}))

    original_watchlist_signature = legacy_main.watchlist_signature
    original_search = SendicoMercariScanner.search
    original_hydrate = SendicoMercariScanner.hydrate
    original_scroll = SendicoMercariScanner._scroll_search_results
    original_screen = GeminiLotVisionAnalyzer.screen_listing
    original_analyze = GeminiLotVisionAnalyzer.analyze
    original_detailed = GeminiLotVisionAnalyzer.analyze_with_overviews
    original_assess = legacy_main.assess_deal
    original_number = vision_module._number

    def patched_watchlist_signature(targets: list[Any]) -> str:
        return versioned_scan_signature(original_watchlist_signature(targets), vision_config)

    async def tracked_search(self: Any, *args: Any, **kwargs: Any) -> Any:
        telemetry.search_attempts += 1
        try:
            return await original_search(self, *args, **kwargs)
        except Exception:
            telemetry.search_errors += 1
            raise

    async def tracked_hydrate(self: Any, *args: Any, **kwargs: Any) -> Any:
        telemetry.hydration_attempts += 1
        try:
            listing = await original_hydrate(self, *args, **kwargs)
        except Exception:
            telemetry.hydration_errors += 1
            raise
        listing.description = extract_seller_description(listing.raw_text, listing.title)
        return listing

    def tracked_screen(self: Any, *args: Any, **kwargs: Any) -> Any:
        telemetry.screening_attempts += 1
        try:
            result = original_screen(self, *args, **kwargs)
        except Exception as exc:
            telemetry.screening_errors += 1
            _mark_pause(telemetry, exc)
            raise
        telemetry.screening_successes += 1
        return result

    def tracked_analyze(self: Any, *args: Any, **kwargs: Any) -> Any:
        telemetry.detailed_attempts += 1
        try:
            result = original_analyze(self, *args, **kwargs)
        except Exception as exc:
            telemetry.detailed_errors += 1
            _mark_pause(telemetry, exc)
            raise
        telemetry.detailed_successes += 1
        return result

    def tracked_detailed(self: Any, *args: Any, **kwargs: Any) -> Any:
        telemetry.detailed_attempts += 1
        try:
            result = original_detailed(self, *args, **kwargs)
        except Exception as exc:
            telemetry.detailed_errors += 1
            _mark_pause(telemetry, exc)
            raise
        telemetry.detailed_successes += 1
        if str(result.listing_type or "").strip().lower() == "single":
            telemetry.single_listings_rejected += 1
            return replace(
                result,
                target_present=False,
                target_confidence=0.0,
                cards=[],
                matched_watchlist_ids=[],
                notes=[*result.notes, "Rejected after Gemini confirmed a single-card listing."],
            )
        return result

    def tracked_assess(*args: Any, **kwargs: Any) -> Any:
        result = original_assess(*args, **kwargs)
        telemetry.assessments += 1
        return result

    def configured_embed_factory(original: Any):
        def configured(*args: Any, **kwargs: Any) -> dict[str, Any]:
            return _replace_fee_text(original(*args, **kwargs), fee_jpy)
        return configured

    replacements: list[tuple[Any, str, Any]] = [
        (legacy_main, "watchlist_signature", patched_watchlist_signature),
        (legacy_main, "_has_strong_lot_evidence", strong_lot_evidence),
        (legacy_main, "_candidate_relevance_score", candidate_relevance_score),
        (SendicoMercariScanner, "search", tracked_search),
        (SendicoMercariScanner, "hydrate", tracked_hydrate),
        (SendicoMercariScanner, "_scroll_search_results", bounded_scroll_results),
        (GeminiLotVisionAnalyzer, "screen_listing", tracked_screen),
        (GeminiLotVisionAnalyzer, "analyze", tracked_analyze),
        (GeminiLotVisionAnalyzer, "analyze_with_overviews", tracked_detailed),
        (legacy_main, "assess_deal", tracked_assess),
        (vision_module, "_number", normalize_card_number),
    ]

    for name in ("build_embed", "build_test_embed"):
        original = getattr(discord_module, name, None)
        if original is not None:
            replacements.append((discord_module, name, configured_embed_factory(original)))

    original_summary = getattr(discord_module, "build_scan_summary_embed", None)
    if original_summary is not None:
        def truthful_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
            embed = original_summary(*args, **kwargs)
            return decorate_summary_embed(
                embed,
                telemetry,
                dict(kwargs),
                has_direct_urls=has_direct_urls,
            )
        replacements.append((discord_module, "build_scan_summary_embed", truthful_summary))

    originals: list[tuple[Any, str, Any]] = []
    for owner, name, replacement in replacements:
        originals.append((owner, name, getattr(owner, name)))
        setattr(owner, name, replacement)
    try:
        yield
    finally:
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)


async def run(config_path: str, dry_run: bool = False) -> int:
    config = load_config(config_path)
    targets = load_watchlist(config)
    validate_watchlist_for_run(targets)

    LOGGER.info("Watchlist is the sole search source. Approved searches:")
    for target in targets:
        LOGGER.info("Target: %s", target.display_name)
        if target.pricecharting_url:
            LOGGER.info("PriceCharting: %s", target.pricecharting_url)
        for search in target.active_searches:
            LOGGER.info("  [%s] %s", search.mode, search.term)

    telemetry = RuntimeTelemetry()
    test_config = dict(config.raw.get("test_mode", {}) or {})
    has_direct_urls = any(str(value).strip() for value in test_config.get("direct_listing_urls", []))
    with _runtime_patches(config=config, telemetry=telemetry):
        exit_code = await legacy_main.run(config_path, dry_run)

    failure_reason = systemic_failure_reason(telemetry, has_direct_urls=has_direct_urls)
    if failure_reason:
        LOGGER.error("Systemic scan failure: %s", failure_reason)
        return 1
    return int(exit_code)


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Sendico scanner using watchlist-only bounded searches"
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(asyncio.run(run(args.config, args.dry_run)))


if __name__ == "__main__":
    cli()
