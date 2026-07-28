from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any, Iterable

from PIL import Image, ImageOps

from .image_processing import CardCrop, DownloadedImage, _hamming_distance
from .models import IdentifiedCard, SendicoListing, VisionResult, WatchCard
from .vision import (
    VisionModelPoolExhaustedError,
    VisionRequestTooLargeError,
    VisionRunBudgetReached,
    _apply_listing_grading_hint,
    _json_object,
    _merge_cards,
    _propagate_visible_grading,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Tier2ScreeningResult:
    target_likely_present: bool
    confidence: float
    relevant_image_indexes: list[int]
    inspected_image_indexes: list[int]
    reason: str
    model: str


@dataclass(slots=True)
class _OverviewCandidate:
    source_image_index: int
    data: bytes
    perceptual_hash: int
    quality_score: float


def _clamp(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _ordered_unique(values: Iterable[int]) -> list[int]:
    result: list[int] = []
    for value in values:
        number = int(value)
        if number not in result:
            result.append(number)
    return result


def _candidate_models(self, requested: list[str] | tuple[str, ...] | None) -> list[str]:
    configured = list(getattr(self, "models", []) or getattr(self, "configured_models", []))
    ordered: list[str] = []
    for value in [*(requested or []), *configured]:
        model = str(value or "").strip()
        if model and model not in ordered and model not in getattr(self, "_disabled_models", {}):
            ordered.append(model)
    return ordered


def _compress_overview(
    downloaded: DownloadedImage,
    *,
    maximum_dimension_px: int,
    jpeg_quality: int,
) -> bytes:
    with Image.open(io.BytesIO(downloaded.data)) as source:
        image = ImageOps.exif_transpose(source).convert("RGB")
        maximum = max(400, int(maximum_dimension_px))
        longest = max(image.size)
        if longest > maximum:
            scale = maximum / longest
            image = image.resize(
                (
                    max(1, round(image.width * scale)),
                    max(1, round(image.height * scale)),
                ),
                Image.Resampling.LANCZOS,
            )
        output = io.BytesIO()
        image.save(
            output,
            format="JPEG",
            quality=max(55, min(92, int(jpeg_quality))),
            optimize=True,
        )
        return output.getvalue()


def _detect_candidates_by_image(self, images: list[DownloadedImage]) -> dict[int, list[Any]]:
    result: dict[int, list[Any]] = {}
    for downloaded in images:
        try:
            result[downloaded.image_index] = self.extractor._extract_from_image(downloaded)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "Tier 2 local card detection failed for image %s: %s",
                downloaded.image_index,
                exc,
            )
            result[downloaded.image_index] = []
    return result


def _select_overview_images(
    downloaded: list[DownloadedImage],
    *,
    preferred_image_indexes: list[int] | tuple[int, ...] | None,
    maximum_overview_images: int,
) -> list[DownloadedImage]:
    by_index = {image.image_index: image for image in downloaded}
    ordered_indexes = _ordered_unique(
        [*(preferred_image_indexes or []), *(image.image_index for image in downloaded)]
    )
    maximum = max(1, int(maximum_overview_images))
    return [by_index[index] for index in ordered_indexes if index in by_index][:maximum]


def _generate_overview_json(
    self,
    parts: list[dict[str, Any]],
    *,
    models: list[str] | tuple[str, ...] | None,
    thinking_level: str,
) -> tuple[dict[str, Any], str]:
    candidates = _candidate_models(self, models)
    if not candidates:
        raise VisionModelPoolExhaustedError(
            "No configured Gemini model remains available for overview analysis"
        )

    previous_thinking = self.thinking_level
    self.thinking_level = thinking_level
    failures: list[str] = []
    try:
        for model in candidates:
            try:
                response = self._post_model_request(
                    model,
                    parts,
                    output_mode="prompt",
                )
            except VisionRunBudgetReached:
                raise
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{model}: {exc}")
                continue

            status, message = self._error_details(response)
            if response.is_error:
                if self._is_request_too_large(response.status_code, message):
                    failures.append(f"{model}: request too large ({message})")
                    continue
                if self._is_model_unavailable(response.status_code, message):
                    self._disabled_models[model] = message
                    failures.append(f"{model}: unavailable ({message})")
                    continue
                if response.status_code in {401, 403}:
                    raise RuntimeError(
                        "Gemini API authentication, billing or permission failure "
                        f"(HTTP {response.status_code}, {status}): {message}"
                    )
                failures.append(f"{model}: HTTP {response.status_code} ({message})")
                continue

            data = response.json()
            self._record_usage(data)
            payload = _json_object(self._extract_text(data))
            self._preferred_model = model
            self.model = model
            self.model_usage[model] = self.model_usage.get(model, 0) + 1
            return payload, model
    finally:
        self.thinking_level = previous_thinking

    if any("request too large" in failure for failure in failures):
        raise VisionRequestTooLargeError(" | ".join(failures))
    raise VisionModelPoolExhaustedError(
        "No Gemini model completed overview analysis: " + " | ".join(failures)
    )


def screen_listing(
    self,
    listing: SendicoListing,
    targets: list[WatchCard],
    *,
    screening_models: list[str] | tuple[str, ...] | None = None,
    maximum_overview_images: int = 6,
    maximum_dimension_px: int = 1400,
    jpeg_quality: int = 78,
) -> Tier2ScreeningResult:
    downloaded = self._download_images(listing.image_urls[: self.max_images])
    if not downloaded:
        raise RuntimeError("No listing images could be downloaded for Tier 2 screening")

    candidates_by_image = self._detect_candidates_by_image(downloaded)
    selected = _select_overview_images(
        downloaded,
        preferred_image_indexes=[],
        maximum_overview_images=maximum_overview_images,
    )
    selected_indexes = [image.image_index for image in selected]

    target_lines: list[str] = []
    for target in targets:
        names = [*target.english_names, *target.japanese_names]
        target_lines.append(
            " | ".join(
                part
                for part in [
                    ", ".join(name for name in names if name),
                    target.set_name,
                    target.set_code,
                    target.card_number,
                ]
                if part
            )
        )
    image_counts = ", ".join(
        f"image {index}: {len(candidates_by_image.get(index, []))} detected card region(s)"
        for index in selected_indexes
    )
    prompt = (
        "Screen these seller overview photos for the exact Japanese Pokemon card targets. "
        "Do not claim a match from the listing title alone. A positive result requires visible "
        "artwork and, where readable, a compatible printed card number/set. Return JSON only: "
        '{"target_likely_present":false,"confidence":0.0,'
        '"relevant_image_indexes":[],"reason":""}.\n'
        f"Listing title: {listing.title[:300]}\n"
        f"Targets: {'; '.join(target_lines)}\n"
        f"Local image observations: {image_counts}\n"
        f"Image indexes supplied in order: {selected_indexes}"
    )
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for image in selected:
        prepared = _compress_overview(
            image,
            maximum_dimension_px=maximum_dimension_px,
            jpeg_quality=jpeg_quality,
        )
        parts.append(self._inline_part("image/jpeg", prepared))

    payload, model = _generate_overview_json(
        self,
        parts,
        models=screening_models,
        thinking_level="minimal",
    )
    selected_set = set(selected_indexes)
    relevant = _ordered_unique(
        int(value)
        for value in payload.get("relevant_image_indexes", [])
        if str(value).lstrip("-").isdigit() and int(value) in selected_set
    )
    return Tier2ScreeningResult(
        target_likely_present=bool(payload.get("target_likely_present")),
        confidence=_clamp(payload.get("confidence")),
        relevant_image_indexes=relevant,
        inspected_image_indexes=selected_indexes,
        reason=str(payload.get("reason") or "No reason supplied").strip(),
        model=model,
    )


def _extract_multi_overview_crops(
    self,
    downloaded: list[DownloadedImage],
    *,
    preferred_image_indexes: list[int] | tuple[int, ...] | None = None,
    maximum_overview_images: int = 12,
) -> tuple[list[CardCrop], list[int], int]:
    selected = _select_overview_images(
        downloaded,
        preferred_image_indexes=preferred_image_indexes,
        maximum_overview_images=maximum_overview_images,
    )
    selected_indexes = [image.image_index for image in selected]
    candidates_by_image = self._detect_candidates_by_image(selected)

    # Match alternate-photo views one-to-one against crops already established
    # by earlier photos. Candidates newly found in the same photo are never
    # deduplicated against each other because they may be genuine duplicate cards
    # visible together. This mirrors the quantity safeguard in LocalCardExtractor
    # while still allowing a later photo to introduce cards omitted from an
    # earlier overview.
    groups: list[_OverviewCandidate] = []
    duplicates = 0
    for image_index in selected_indexes:
        raw_candidates = sorted(
            candidates_by_image.get(image_index, []),
            key=lambda item: float(getattr(item, "quality_score", 0.0)),
            reverse=True,
        )
        candidates = [
            _OverviewCandidate(
                source_image_index=int(getattr(candidate, "source_image_index", image_index)),
                data=bytes(candidate.data),
                perceptual_hash=int(getattr(candidate, "perceptual_hash", 0)),
                quality_score=float(getattr(candidate, "quality_score", 0.0)),
            )
            for candidate in raw_candidates
        ]
        prior_group_count = len(groups)
        matched_prior_groups: set[int] = set()
        for candidate in candidates:
            duplicate_index: int | None = None
            best_distance = self.extractor.duplicate_phash_distance + 1
            for index in range(prior_group_count):
                if index in matched_prior_groups:
                    continue
                existing = groups[index]
                distance = _hamming_distance(
                    candidate.perceptual_hash,
                    existing.perceptual_hash,
                )
                if distance < best_distance:
                    best_distance = distance
                    duplicate_index = index
            if (
                duplicate_index is not None
                and best_distance <= self.extractor.duplicate_phash_distance
            ):
                duplicates += 1
                matched_prior_groups.add(duplicate_index)
                existing = groups[duplicate_index]
                if candidate.quality_score > existing.quality_score:
                    groups[duplicate_index] = _OverviewCandidate(
                        # Preserve the earlier overview as quantity evidence even
                        # when the later photo provides the sharper pixels.
                        source_image_index=existing.source_image_index,
                        data=candidate.data,
                        perceptual_hash=candidate.perceptual_hash,
                        quality_score=candidate.quality_score,
                    )
                continue
            groups.append(candidate)

    buckets: dict[int, list[_OverviewCandidate]] = {
        index: [] for index in selected_indexes
    }
    for candidate in groups:
        buckets.setdefault(candidate.source_image_index, []).append(candidate)
    for bucket in buckets.values():
        bucket.sort(key=lambda item: item.quality_score, reverse=True)

    balanced: list[_OverviewCandidate] = []
    limit = max(1, int(self.extractor.max_crops))
    while len(balanced) < limit:
        added = False
        for image_index in selected_indexes:
            bucket = buckets.get(image_index, [])
            if bucket:
                balanced.append(bucket.pop(0))
                added = True
                if len(balanced) >= limit:
                    break
        if not added:
            break

    crops = [
        CardCrop(
            crop_index=index,
            source_image_index=candidate.source_image_index,
            mime_type="image/jpeg",
            data=candidate.data,
            perceptual_hash=candidate.perceptual_hash,
            quality_score=candidate.quality_score,
        )
        for index, candidate in enumerate(balanced, start=1)
    ]
    return crops, selected_indexes, duplicates


def _vision_result_from_crops(
    self,
    listing: SendicoListing,
    targets: list[WatchCard],
    crops: list[CardCrop],
    *,
    selected_indexes: list[int],
    duplicate_count: int,
) -> VisionResult:
    if not crops:
        return VisionResult(
            listing_type="unknown",
            target_present=False,
            target_confidence=0.0,
            cards=[],
            unidentified_card_count=0,
            notes=[
                "Multi-image preprocessing could not isolate any card-shaped regions; "
                "no detailed Gemini identification request was sent."
            ],
        )

    batches = [
        crops[index : index + self.crop_batch_size]
        for index in range(0, len(crops), self.crop_batch_size)
    ]
    if (
        self.max_requests_per_run > 0
        and self.requests_sent + len(batches) > self.max_requests_per_run
    ):
        remaining = max(0, self.max_requests_per_run - self.requests_sent)
        raise VisionRunBudgetReached(
            "Gemini request budget reached before this listing: "
            f"{remaining} request(s) remain, but {len(batches)} are planned"
        )

    identified: list[IdentifiedCard] = []
    unidentified = 0
    completed_requests = 0
    for batch in batches:
        batch_results, request_count = self._identify_with_size_fallback(
            listing,
            targets,
            batch,
        )
        completed_requests += request_count
        for batch_result in batch_results:
            identified.extend(batch_result.cards)
            unidentified += batch_result.unidentified_count

    identified = _propagate_visible_grading(identified)
    identified, title_grade_applied = _apply_listing_grading_hint(identified, listing)
    merged = _merge_cards(identified)
    matched_ids = list(
        dict.fromkeys(
            target_id
            for card in merged
            for target_id in card.matched_watchlist_ids
        )
    )
    target_cards = [card for card in merged if card.is_target]
    physical_card_count = sum(card.quantity for card in merged)
    if physical_card_count == 1:
        listing_type = "single"
    elif physical_card_count <= 8:
        listing_type = "lot"
    else:
        listing_type = "collection"

    return VisionResult(
        listing_type=listing_type,
        target_present=bool(target_cards),
        target_confidence=max([card.confidence for card in target_cards] + [0.0]),
        cards=merged,
        unidentified_card_count=unidentified,
        notes=[
            f"Detailed multi-image mode inspected listing photos {selected_indexes}.",
            f"Local preprocessing retained {len(crops)} unique card crop(s) and removed {duplicate_count} duplicate view(s).",
            f"Gemini identification used {completed_requests} request(s) across {len(batches)} batch(es).",
            "Crop selection was balanced across inspected photos before using additional crops from a dense photo.",
            *(
                [
                    "A grading company and grade were taken from the explicit listing title; verify the slab label and certification number manually."
                ]
                if title_grade_applied
                else []
            ),
        ],
        matched_watchlist_ids=matched_ids,
    )


def analyze_with_overviews(
    self,
    listing: SendicoListing,
    targets: list[WatchCard],
    *,
    preferred_image_indexes: list[int] | tuple[int, ...] | None = None,
    maximum_overview_images: int = 12,
) -> VisionResult:
    downloaded = self._download_images(listing.image_urls[: self.max_images])
    if not downloaded:
        raise RuntimeError("No listing images could be downloaded for Gemini analysis")
    crops, selected_indexes, duplicate_count = self._extract_multi_overview_crops(
        downloaded,
        preferred_image_indexes=preferred_image_indexes,
        maximum_overview_images=maximum_overview_images,
    )
    return _vision_result_from_crops(
        self,
        listing,
        targets,
        crops,
        selected_indexes=selected_indexes,
        duplicate_count=duplicate_count,
    )


def install_on(analyzer_class: type) -> None:
    """Install the Tier 2 methods on the existing Gemini analyser class.

    This keeps the public import path and all current references unchanged while
    adding the methods already called by main.py and exercised by the test suite.
    """

    methods = {
        "_detect_candidates_by_image": _detect_candidates_by_image,
        "_extract_multi_overview_crops": _extract_multi_overview_crops,
        "screen_listing": screen_listing,
        "analyze_with_overviews": analyze_with_overviews,
    }
    for name, method in methods.items():
        if not callable(getattr(analyzer_class, name, None)):
            setattr(analyzer_class, name, method)


# Runtime compatibility and safety guards
# ---------------------------------------
# These guards are installed from pokemon_deal_bot.__init__ so GitHub file-only
# updates work even when gemini_vision.py and main.py come from an older checkout.
# The patch is deliberately idempotent.
_RUNTIME_INSTALLED = False
_PRICING_TARGET_CONFIRMED = False
_SINGLE_CARD_REJECTIONS = 0


def _wrap_token_budget(analyzer_class: type) -> None:
    if getattr(analyzer_class, "_sendico_token_budget_installed", False):
        return

    original_init = analyzer_class.__init__
    original_post = analyzer_class._post_model_request

    def budgeted_init(
        self,
        *args,
        max_total_tokens_per_run: int = 125000,
        token_budget_reserve_per_request: int = 5000,
        **kwargs,
    ):
        original_init(self, *args, **kwargs)
        self.max_total_tokens_per_run = max(0, int(max_total_tokens_per_run))
        self.token_budget_reserve_per_request = max(
            0, int(token_budget_reserve_per_request)
        )

    def budgeted_post(self, *args, **kwargs):
        limit = max(0, int(getattr(self, "max_total_tokens_per_run", 125000)))
        reserve = max(
            0,
            int(getattr(self, "token_budget_reserve_per_request", 5000)),
        )
        used = max(0, int(getattr(self, "total_tokens", 0)))
        if limit > 0 and used + reserve > limit:
            raise VisionRunBudgetReached(
                "Gemini token budget reached for this scan: "
                f"{used:,} tokens used; {reserve:,} reserved for the next request; "
                f"limit {limit:,}."
            )
        return original_post(self, *args, **kwargs)

    analyzer_class.__init__ = budgeted_init
    analyzer_class._post_model_request = budgeted_post
    analyzer_class._sendico_token_budget_installed = True


def _wrap_analysis_results(analyzer_class: type) -> None:
    global _PRICING_TARGET_CONFIRMED

    if getattr(analyzer_class, "_sendico_analysis_guards_installed", False):
        return

    def wrap(method):
        def guarded(self, *args, **kwargs):
            global _PRICING_TARGET_CONFIRMED, _SINGLE_CARD_REJECTIONS
            _PRICING_TARGET_CONFIRMED = False
            result = method(self, *args, **kwargs)
            if str(getattr(result, "listing_type", "")).strip().lower() == "single":
                _SINGLE_CARD_REJECTIONS += 1
                result.target_present = False
                result.target_confidence = 0.0
                notes = list(getattr(result, "notes", []) or [])
                message = "Detailed Gemini confirmed a single-card listing"
                if message not in notes:
                    notes.append(message)
                result.notes = notes
            _PRICING_TARGET_CONFIRMED = bool(
                getattr(result, "target_present", False)
            )
            return result

        return guarded

    if callable(getattr(analyzer_class, "analyze", None)):
        analyzer_class.analyze = wrap(analyzer_class.analyze)
    if callable(getattr(analyzer_class, "analyze_with_overviews", None)):
        analyzer_class.analyze_with_overviews = wrap(
            analyzer_class.analyze_with_overviews
        )
    analyzer_class._sendico_analysis_guards_installed = True


def _install_price_guard() -> None:
    from .pricecharting import PriceChartingClient

    if getattr(PriceChartingClient, "_sendico_target_guard_installed", False):
        return

    original_price_card = PriceChartingClient.price_card

    def guarded_price_card(self, *args, **kwargs):
        if not _PRICING_TARGET_CONFIRMED:
            LOGGER.info("no watchlist target was confirmed; pricing skipped")
            return None
        return original_price_card(self, *args, **kwargs)

    PriceChartingClient.price_card = guarded_price_card
    PriceChartingClient._sendico_target_guard_installed = True


def _install_discord_summary_guard() -> None:
    from . import discord as discord_module

    original_summary = discord_module.send_discord_summary
    if getattr(original_summary, "_sendico_held_guard_installed", False):
        return

    def guarded_summary(*args, **kwargs):
        global _PRICING_TARGET_CONFIRMED, _SINGLE_CARD_REJECTIONS
        original_non_lot = int(kwargs.get("tier2_non_lot_filtered", 0) or 0)
        kwargs["tier2_non_lot_filtered"] = (
            original_non_lot + _SINGLE_CARD_REJECTIONS
        )

        stop_reason = str(kwargs.get("stop_reason") or "").strip()
        if stop_reason:
            selected = int(kwargs.get("tier2_selected", 0) or 0)
            screened = int(kwargs.get("tier2_screened", 0) or 0)
            probable = int(kwargs.get("tier2_probable", 0) or 0)
            analysed = int(kwargs.get("tier2_analysed", 0) or 0)
            held = int(kwargs.get("tier2_held", 0) or 0)

            if screened > 0:
                inferred_held = max(0, selected - screened) + max(
                    0, probable - analysed
                )
            else:
                inferred_held = max(
                    0,
                    selected - analysed - kwargs["tier2_non_lot_filtered"],
                )
            held = max(held, inferred_held)
            kwargs["tier2_held"] = held
            if held > 0 and "remaining eligible Tier 2" not in stop_reason:
                kwargs["stop_reason"] = (
                    f"{stop_reason} {held} remaining eligible Tier 2 listing(s) "
                    "will be considered on the next run."
                )

        try:
            return original_summary(*args, **kwargs)
        finally:
            _PRICING_TARGET_CONFIRMED = False
            _SINGLE_CARD_REJECTIONS = 0

    guarded_summary._sendico_held_guard_installed = True
    discord_module.send_discord_summary = guarded_summary


def install_runtime_support() -> None:
    """Install Tier 2 methods and v5 safety controls exactly once.

    This is designed for GitHub UI file uploads. It makes the current analyzer
    compatible with the two-pass pipeline without requiring a local patch script.
    """

    global _RUNTIME_INSTALLED
    if _RUNTIME_INSTALLED:
        return

    from .gemini_vision import GeminiLotVisionAnalyzer

    install_on(GeminiLotVisionAnalyzer)
    _wrap_token_budget(GeminiLotVisionAnalyzer)
    _wrap_analysis_results(GeminiLotVisionAnalyzer)
    _install_price_guard()
    _install_discord_summary_guard()
    _RUNTIME_INSTALLED = True
