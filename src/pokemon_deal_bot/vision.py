from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageOps

from .image_processing import CardCrop, DownloadedImage, LocalCardExtractor
from .models import IdentifiedCard, SendicoListing, VisionResult, WatchCard

LOGGER = logging.getLogger(__name__)


class VisionRateLimitError(RuntimeError):
    """Raised when Groq asks the scanner to stop because quota is unavailable."""


class VisionRequestTooLargeError(VisionRateLimitError):
    """Raised when one Groq request exceeds the model or account token budget."""


class VisionRunBudgetReached(RuntimeError):
    """Raised before another Groq request would exceed this scan run's budget."""


class VisionModelPoolExhaustedError(VisionRateLimitError):
    """Raised when no configured or discovered Groq model can handle the request."""


@dataclass(slots=True)
class _BatchResult:
    cards: list[IdentifiedCard]
    unidentified_count: int


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Vision response did not contain a JSON object")
    return json.loads(cleaned[start : end + 1])


def _clamp_confidence(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value or 0.0)))
    except (TypeError, ValueError):
        return 0.0


def _normalize_variant(value: Any) -> str:
    """Return a stable pricing variant, defaulting conservatively to normal/holo."""
    text = re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")
    aliases = {
        "masterball": "master_ball",
        "master_ball_reverse": "master_ball",
        "pokeball": "poke_ball",
        "poke_ball_reverse": "poke_ball",
        "pok_ball": "poke_ball",
        "reverse": "reverse_holo",
        "reverse_foil": "reverse_holo",
        "standard": "normal_holo",
        "normal": "normal_holo",
        "holo": "normal_holo",
        "regular": "normal_holo",
        "": "normal_holo",
    }
    normalized = aliases.get(text, text)
    return normalized if normalized in {
        "normal_holo",
        "poke_ball",
        "master_ball",
        "reverse_holo",
        "other",
    } else "normal_holo"



_GRADING_COMPANY_ALIASES = {
    "psa": "PSA",
    "bgs": "BGS",
    "beckett": "BGS",
    "cgc": "CGC",
    "sgc": "SGC",
    "tag": "TAG",
    "ace": "ACE",
}


def _normalize_grading_company(value: Any) -> str | None:
    compact = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    return _GRADING_COMPANY_ALIASES.get(compact)


def _normalize_grade(value: Any) -> str | None:
    match = re.search(r"(?<!\d)(10|[1-9](?:\.5)?)(?!\d)", str(value or ""))
    if not match:
        return None
    number = float(match.group(1))
    if not 1.0 <= number <= 10.0:
        return None
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _listing_grade_hint(listing: SendicoListing) -> tuple[str, str] | None:
    text = " ".join([listing.title, listing.description[:1000]])
    match = re.search(
        r"\b(PSA|BGS|BECKETT|CGC|SGC|TAG|ACE)\s*(?:GRADE\s*)?"
        r"(10|[1-9](?:\.5)?)\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    company = _normalize_grading_company(match.group(1))
    grade = _normalize_grade(match.group(2))
    return (company, grade) if company and grade else None


def _card_mentioned_in_listing(card: IdentifiedCard, listing: SendicoListing) -> bool:
    haystack = _compact(" ".join([listing.title, listing.description[:1000]]))
    names = [_compact(card.name_en), _compact(card.name_jp)]
    name_match = any(name and name in haystack for name in names)
    numerator = _compact(card.card_number.split("/", 1)[0])
    number_match = bool(numerator and numerator in haystack)
    return name_match and number_match



def _base_identity_key(card: IdentifiedCard) -> str:
    return "|".join(
        [
            card.language.lower().strip(),
            (card.set_code or card.set_name or "").lower().strip(),
            card.card_number.lower().replace(" ", ""),
            card.name_en.lower().strip(),
            card.variant.lower().strip(),
        ]
    )


def _propagate_visible_grading(
    cards: list[IdentifiedCard],
) -> list[IdentifiedCard]:
    """Share one image-confirmed slab grade across duplicate crops of the card.

    Local preprocessing can produce a full slab crop and a sharper inner-card
    crop. When one crop clearly reads the slab label and the other does not, they
    are still the same physical graded card. Conflicting visible grades are never
    merged or propagated.
    """
    groups: dict[str, list[IdentifiedCard]] = {}
    for card in cards:
        groups.setdefault(_base_identity_key(card), []).append(card)

    updated: list[IdentifiedCard] = []
    for group in groups.values():
        visible_grades = {
            (card.grading_company, card.grade)
            for card in group
            if card.is_graded and card.grading_source == "image"
        }
        if len(visible_grades) != 1:
            updated.extend(group)
            continue
        company, grade = next(iter(visible_grades))
        confidence = max(
            card.grading_confidence
            for card in group
            if card.is_graded and card.grading_source == "image"
        )
        for card in group:
            if card.is_graded:
                updated.append(card)
            else:
                updated.append(
                    replace(
                        card,
                        grading_company=company,
                        grade=grade,
                        grading_confidence=confidence,
                        grading_source="image_context",
                    )
                )
    return updated

def _apply_listing_grading_hint(
    cards: list[IdentifiedCard],
    listing: SendicoListing,
) -> tuple[list[IdentifiedCard], bool]:
    """Apply an explicit grading claim from the listing title as a fallback.

    Image-confirmed grading remains preferred. The title fallback is only applied
    to cards whose name and number are mentioned in the listing, or to the sole
    identified target card when the listing contains only one distinct identity.
    Discord labels title-derived grades as claimed so the slab still requires
    manual verification.
    """
    hint = _listing_grade_hint(listing)
    if not hint or not cards:
        return cards, False

    company, grade = hint
    candidates = [card for card in cards if _card_mentioned_in_listing(card, listing)]
    if not candidates:
        distinct_target_keys = {card.key for card in cards if card.is_target}
        if len(distinct_target_keys) == 1:
            candidates = [card for card in cards if card.is_target]

    candidate_ids = {id(card) for card in candidates}
    changed = False
    updated: list[IdentifiedCard] = []
    for card in cards:
        if id(card) not in candidate_ids or card.is_graded:
            updated.append(card)
            continue
        updated.append(
            replace(
                card,
                grading_company=company,
                grade=grade,
                grading_confidence=0.90,
                grading_source="listing_title",
            )
        )
        changed = True
    return updated, changed

def _compact(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


def _number(value: str | None) -> str:
    return re.sub(r"\s+", "", str(value or "")).casefold()


def _name_matches(card: IdentifiedCard, target: WatchCard) -> bool:
    card_names = [_compact(card.name_en), _compact(card.name_jp)]
    target_names = [
        *(_compact(value) for value in target.english_names),
        *(_compact(value) for value in target.japanese_names),
    ]
    card_names = [value for value in card_names if value]
    target_names = [value for value in target_names if value]
    if target.match_mode == "exact_card":
        return any(card_name == target_name for card_name in card_names for target_name in target_names)
    # General Pokemon searches accept a base name within a prefixed/suffixed card
    # name, e.g. Tyranitar also matches Dark Tyranitar and Shining Tyranitar.
    return any(
        card_name == target_name
        or target_name in card_name
        or card_name in target_name
        for card_name in card_names
        for target_name in target_names
    )


def _set_value_matches(candidate: str | None, allowed: str) -> bool:
    candidate_normalized = _compact(candidate)
    allowed_normalized = _compact(allowed)
    if not candidate_normalized or not allowed_normalized:
        return False
    return (
        candidate_normalized == allowed_normalized
        or allowed_normalized in candidate_normalized
        or candidate_normalized in allowed_normalized
    )


def _set_matches(card: IdentifiedCard, target: WatchCard) -> bool:
    if target.match_mode == "exact_card":
        restrictions = [value for value in [target.set_code, target.set_name] if value]
        if not restrictions:
            return True
        candidates = [value for value in [card.set_code, card.set_name] if value]
        # Card number plus exact Pokemon name is still useful when Groq cannot
        # read the set. Reject only when it supplied conflicting set information.
        if not candidates:
            return True
        return any(
            _set_value_matches(candidate, allowed)
            for candidate in candidates
            for allowed in restrictions
        )

    accepted_codes = list(target.accepted_set_codes)
    accepted_sets = list(target.accepted_sets)
    if target.set_code:
        accepted_codes.append(target.set_code)
    if target.set_name:
        accepted_sets.append(target.set_name)
    if not accepted_codes and not accepted_sets:
        return True

    if card.set_code and any(
        _compact(card.set_code) == _compact(value) for value in accepted_codes
    ):
        return True
    if card.set_name and any(
        _set_value_matches(card.set_name, value) for value in accepted_sets
    ):
        return True
    return False


def _target_matches_card(card: IdentifiedCard, target: WatchCard) -> bool:
    if target.language and _compact(card.language) != _compact(target.language):
        return False
    if not _name_matches(card, target):
        return False
    if target.match_mode == "exact_card" and _number(card.card_number) != _number(target.card_number):
        return False
    return _set_matches(card, target)


def parse_vision_result(
    payload: dict[str, Any],
    targets: list[WatchCard] | WatchCard,
) -> VisionResult:
    target_list = targets if isinstance(targets, list) else [targets]
    cards: list[IdentifiedCard] = []
    for raw in payload.get("cards", []):
        number = str(raw.get("card_number") or "").strip()
        if not number:
            continue
        card = IdentifiedCard(
            name_en=str(raw.get("name_en") or "Unknown").strip(),
            name_jp=(str(raw.get("name_jp")).strip() if raw.get("name_jp") else None),
            set_name=(str(raw.get("set_name")).strip() if raw.get("set_name") else None),
            set_code=(str(raw.get("set_code")).strip() if raw.get("set_code") else None),
            card_number=number,
            rarity=(str(raw.get("rarity")).strip() if raw.get("rarity") else None),
            language=str(raw.get("language") or "Japanese"),
            quantity=max(1, int(raw.get("quantity") or 1)),
            confidence=_clamp_confidence(raw.get("confidence")),
            evidence_image_indexes=[
                int(value)
                for value in raw.get("evidence_image_indexes", [])
                if str(value).isdigit()
            ],
            condition=str(raw.get("condition") or "unknown"),
            variant=_normalize_variant(raw.get("variant")),
            grading_company=_normalize_grading_company(raw.get("grading_company")),
            grade=_normalize_grade(raw.get("grade")),
            grading_confidence=_clamp_confidence(raw.get("grading_confidence")),
            grading_source=(
                "image"
                if _normalize_grading_company(raw.get("grading_company"))
                and _normalize_grade(raw.get("grade"))
                else None
            ),
        )
        card.matched_watchlist_ids = [
            target.id for target in target_list if _target_matches_card(card, target)
        ]
        card.is_target = bool(card.matched_watchlist_ids)
        cards.append(card)

    matched_ids = list(
        dict.fromkeys(
            target_id
            for card in cards
            for target_id in card.matched_watchlist_ids
        )
    )
    target_cards = [card for card in cards if card.is_target]
    return VisionResult(
        listing_type=str(payload.get("listing_type") or "unknown"),
        target_present=bool(target_cards),
        target_confidence=max([card.confidence for card in target_cards] + [0.0]),
        cards=cards,
        unidentified_card_count=max(0, int(payload.get("unidentified_card_count") or 0)),
        notes=[str(note) for note in payload.get("notes", [])],
        matched_watchlist_ids=matched_ids,
    )


def _merge_cards(cards: list[IdentifiedCard]) -> list[IdentifiedCard]:
    """Merge repeated identifications without counting alternate photos twice.

    Sendico listings commonly show the same physical card in several photos.
    Every local crop records its source image, so the safest quantity estimate is
    the largest number of identical cards visible together in any single source
    image, not the total number of times the card appears across all photos.

    This still preserves a genuine quantity of two or more when identical cards
    are visible together in one overview photo.
    """
    grouped: dict[str, list[IdentifiedCard]] = {}
    for card in cards:
        grouped.setdefault(card.key, []).append(card)

    merged: list[IdentifiedCard] = []
    for group in grouped.values():
        best = max(group, key=lambda item: item.confidence)
        counts_by_source: dict[int, int] = {}
        without_source = 0

        for card in group:
            source_indexes = sorted(set(card.evidence_image_indexes))
            if source_indexes:
                for source_index in source_indexes:
                    counts_by_source[source_index] = (
                        counts_by_source.get(source_index, 0) + card.quantity
                    )
            else:
                # Legacy/test payloads may not include source-image evidence.
                without_source += card.quantity

        if counts_by_source:
            quantity = max(max(counts_by_source.values()), without_source or 0)
        else:
            quantity = max(1, without_source)

        merged.append(
            replace(
                best,
                quantity=max(1, quantity),
                confidence=max(item.confidence for item in group),
                is_target=any(item.is_target for item in group),
                matched_watchlist_ids=list(
                    dict.fromkeys(
                        target_id
                        for item in group
                        for target_id in item.matched_watchlist_ids
                    )
                ),
                evidence_image_indexes=sorted(
                    {
                        source_index
                        for item in group
                        for source_index in item.evidence_image_indexes
                    }
                ),
            )
        )
    return merged


class LotVisionAnalyzer:
    """Identify locally cropped cards with small, paced Groq vision requests."""

    def __init__(
        self,
        api_key: str,
        model: str | None,
        max_images: int,
        *,
        models: list[str] | tuple[str, ...] | None = None,
        auto_discover_models: bool = False,
        max_model_attempts_per_request: int = 8,
        service_tier: str = "auto",
        max_local_crops: int = 40,
        crop_batch_size: int = 4,
        request_spacing_seconds: float = 65.0,
        max_completion_tokens: int = 1600,
        contact_sheet_max_dimension_px: int = 1100,
        contact_sheet_jpeg_quality: int = 82,
        analysis_max_dimension_px: int = 2200,
        crop_max_dimension_px: int = 1400,
        crop_jpeg_quality: int = 86,
        minimum_card_area_ratio: float = 0.012,
        maximum_card_area_ratio: float = 0.98,
        minimum_rectangularity: float = 0.58,
        card_aspect_ratio_min: float = 0.52,
        card_aspect_ratio_max: float = 0.84,
        duplicate_phash_distance: int = 10,
        crop_padding_percent: float = 0.025,
        max_requests_per_run: int = 12,
    ) -> None:
        self.api_key = api_key
        configured_models: list[str] = []
        for candidate in list(models or []):
            value = str(candidate).strip()
            if value and value not in configured_models:
                configured_models.append(value)
        legacy_model = str(model or "").strip()
        if legacy_model and legacy_model not in configured_models:
            configured_models.append(legacy_model)
        self.configured_models = configured_models
        self.models = list(configured_models)
        self.model = self.models[0] if self.models else "auto-discovered"
        self.auto_discover_models = bool(auto_discover_models)
        self.max_model_attempts_per_request = max(1, int(max_model_attempts_per_request))
        self.service_tier = str(service_tier or "auto").strip() or "auto"
        self.max_images = max(1, max_images)
        self.crop_batch_size = max(1, min(8, crop_batch_size))
        self.request_spacing_seconds = max(0.0, request_spacing_seconds)
        self.max_completion_tokens = max(256, min(4096, max_completion_tokens))
        self.contact_sheet_max_dimension_px = max(500, contact_sheet_max_dimension_px)
        self.contact_sheet_jpeg_quality = max(55, min(92, contact_sheet_jpeg_quality))
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"
        self.models_endpoint = "https://api.groq.com/openai/v1/models"
        self._last_request_started_by_model: dict[str, float] = {}
        self._models_resolved = not self.auto_discover_models
        self._preferred_model: str | None = None
        self._disabled_models: dict[str, str] = {}
        self.model_usage: dict[str, int] = {}
        self.model_attempts: dict[str, int] = {}
        self.max_requests_per_run = max(0, int(max_requests_per_run))
        self.requests_sent = 0
        self.extractor = LocalCardExtractor(
            max_crops=max_local_crops,
            analysis_max_dimension_px=analysis_max_dimension_px,
            crop_max_dimension_px=crop_max_dimension_px,
            jpeg_quality=crop_jpeg_quality,
            minimum_card_area_ratio=minimum_card_area_ratio,
            maximum_card_area_ratio=maximum_card_area_ratio,
            minimum_rectangularity=minimum_rectangularity,
            card_aspect_ratio_min=card_aspect_ratio_min,
            card_aspect_ratio_max=card_aspect_ratio_max,
            duplicate_phash_distance=duplicate_phash_distance,
            crop_padding_percent=crop_padding_percent,
        )

    @property
    def configured_model_summary(self) -> str:
        values = self.configured_models or ["automatic account discovery"]
        suffix = " + auto-discovery" if self.auto_discover_models else ""
        return ", ".join(values) + suffix

    @property
    def models_used_summary(self) -> str:
        if not self.model_usage:
            return "None completed"
        return ", ".join(
            f"{model} ({count})"
            for model, count in sorted(
                self.model_usage.items(), key=lambda item: (-item[1], item[0])
            )
        )

    def analyze(self, listing: SendicoListing, targets: list[WatchCard]) -> VisionResult:
        downloaded = self._download_images(listing.image_urls[: self.max_images])
        if not downloaded:
            raise RuntimeError("No listing images could be downloaded for Groq analysis")
        LOGGER.info("Downloaded %d Sendico listing image(s)", len(downloaded))

        crops = self.extractor.extract(downloaded)
        if not crops:
            return VisionResult(
                listing_type="unknown",
                target_present=False,
                target_confidence=0.0,
                cards=[],
                unidentified_card_count=0,
                notes=[
                    "Local preprocessing could not isolate any card-shaped regions; "
                    "no Groq request was sent."
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
                "Groq request budget reached before this listing: "
                f"{remaining} request(s) remain, but {len(batches)} are planned"
            )
        identified: list[IdentifiedCard] = []
        unidentified = 0
        completed_requests = 0

        for batch_index, batch in enumerate(batches, start=1):
            LOGGER.info(
                "Sending local crop batch %d/%d to Groq (%d card crop(s))",
                batch_index,
                len(batches),
                len(batch),
            )
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
        identified, title_grade_applied = _apply_listing_grading_hint(
            identified,
            listing,
        )
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
                f"Local OpenCV preprocessing isolated {len(crops)} unique physical card crop(s).",
                f"Groq identification used {completed_requests} small single-image request(s) across {len(batches)} planned batch(es).",
                "Watchlist matching was applied locally after identification; target details were not added to the Groq prompt.",
                "Physical quantity was anchored to one listing photo; alternate views could improve a matching crop but could not add quantity.",
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

    def _identify_with_size_fallback(
        self,
        listing: SendicoListing,
        targets: list[WatchCard],
        crops: list[CardCrop],
        *,
        compact: bool = False,
    ) -> tuple[list[_BatchResult], int]:
        try:
            payload = self._request_batch(listing, crops, compact=compact)
            return [self._parse_batch_result(payload, targets, crops)], 1
        except VisionRequestTooLargeError:
            if len(crops) > 1:
                midpoint = len(crops) // 2
                LOGGER.warning(
                    "Groq rejected a %d-card request as too large; splitting it into %d and %d cards",
                    len(crops),
                    midpoint,
                    len(crops) - midpoint,
                )
                left_results, left_count = self._identify_with_size_fallback(
                    listing,
                    targets,
                    crops[:midpoint],
                    compact=True,
                )
                right_results, right_count = self._identify_with_size_fallback(
                    listing,
                    targets,
                    crops[midpoint:],
                    compact=True,
                )
                return left_results + right_results, left_count + right_count
            if not compact:
                LOGGER.warning(
                    "Groq rejected a one-card sheet as too large; retrying with a smaller compressed sheet"
                )
                return self._identify_with_size_fallback(
                    listing,
                    targets,
                    crops,
                    compact=True,
                )
            raise VisionRateLimitError(
                "Groq rejected even the compact one-card request as larger than the available token budget"
            )

    def _request_batch(
        self,
        listing: SendicoListing,
        crops: list[CardCrop],
        *,
        compact: bool,
    ) -> dict[str, Any]:
        sheet = self._make_contact_sheet(crops, compact=compact)
        crop_indexes = ", ".join(str(crop.crop_index) for crop in crops)
        prompt = (
            "Identify the Japanese Pokemon card in each labelled panel. "
            "Return one card at most per panel. Only identify a card when its front face "
            "and exact printed card number are readable; card backs and unreadable slab "
            "backs must go in unrecognized_crop_indexes. Do not guess and never identify "
            "an unreadable panel from the listing title alone. If a professional grading "
            "slab and label are visibly present, return grading_company and grade exactly "
            "as printed, plus grading_confidence. Otherwise use null grading fields. "
            "Default variant to normal_holo. Use poke_ball, master_ball, "
            "reverse_holo or other only when that special pattern is clearly visible. "
            f"Listing title: {listing.title[:300]}\n"
            f"Panel indexes in this request: {crop_indexes}.\n"
            "Return JSON only in this shape: "
            '{"cards":[{"crop_index":1,"name_en":"","name_jp":null,'
            '"set_name":null,"set_code":null,"card_number":"","rarity":null,'
            '"language":"Japanese","confidence":0.0,"condition":"unknown",'
            '"variant":"normal_holo","grading_company":null,"grade":null,'
            '"grading_confidence":0.0}],"unrecognized_crop_indexes":[]}'
        )
        parts = [
            {"text": prompt},
            self._inline_part("image/jpeg", sheet),
        ]
        return self._generate(parts)

    def _parse_batch_result(
        self,
        payload: dict[str, Any],
        targets: list[WatchCard],
        crops: list[CardCrop],
    ) -> _BatchResult:
        source_by_crop = {
            crop.crop_index: crop.source_image_index
            for crop in crops
        }
        best_by_crop: dict[int, dict[str, Any]] = {}
        for raw in payload.get("cards", []):
            item = dict(raw)
            try:
                crop_index = int(item.get("crop_index") or 0)
            except (TypeError, ValueError):
                continue
            if crop_index not in source_by_crop:
                continue
            existing = best_by_crop.get(crop_index)
            if existing is None or _clamp_confidence(item.get("confidence")) > _clamp_confidence(
                existing.get("confidence")
            ):
                best_by_crop[crop_index] = item

        normalized_cards: list[dict[str, Any]] = []
        for crop_index, item in sorted(best_by_crop.items()):
            if not str(item.get("card_number") or "").strip():
                continue
            item["evidence_image_indexes"] = [source_by_crop[crop_index]]
            item["quantity"] = 1
            normalized_cards.append(item)

        explicitly_unrecognized = {
            int(value)
            for value in payload.get("unrecognized_crop_indexes", [])
            if str(value).isdigit() and int(value) in source_by_crop
        }
        recognized_indexes = {
            crop_index
            for crop_index, item in best_by_crop.items()
            if str(item.get("card_number") or "").strip()
        }
        all_indexes = set(source_by_crop)
        unrecognized = explicitly_unrecognized | (all_indexes - recognized_indexes)

        normalized = {
            "listing_type": "lot",
            "cards": normalized_cards,
            "unidentified_card_count": len(unrecognized),
            "notes": [],
        }
        result = parse_vision_result(normalized, targets)
        return _BatchResult(
            cards=result.cards,
            unidentified_count=result.unidentified_card_count,
        )

    def _make_contact_sheet(self, crops: list[CardCrop], *, compact: bool = False) -> bytes:
        if not crops:
            raise ValueError("Cannot create a contact sheet without crops")

        columns = 1 if len(crops) == 1 else 2
        rows = (len(crops) + columns - 1) // columns
        if compact:
            panel_width = 270
            image_height = 380
            label_height = 28
        else:
            panel_width = 360
            image_height = 500
            label_height = 34
        panel_height = image_height + label_height

        canvas = Image.new(
            "RGB",
            (columns * panel_width, rows * panel_height),
            "white",
        )
        draw = ImageDraw.Draw(canvas)
        for position, crop in enumerate(crops):
            column = position % columns
            row = position // columns
            x0 = column * panel_width
            y0 = row * panel_height
            draw.rectangle(
                (x0, y0, x0 + panel_width - 1, y0 + label_height - 1),
                fill="white",
                outline="black",
                width=2,
            )
            draw.text((x0 + 10, y0 + 9), f"Card {crop.crop_index}", fill="black")
            with Image.open(io.BytesIO(crop.data)) as source:
                source = ImageOps.exif_transpose(source).convert("RGB")
                fitted = ImageOps.contain(
                    source,
                    (panel_width - 14, image_height - 14),
                    Image.Resampling.LANCZOS,
                )
                image_x = x0 + (panel_width - fitted.width) // 2
                image_y = y0 + label_height + (image_height - fitted.height) // 2
                canvas.paste(fitted, (image_x, image_y))

        longest = max(canvas.size)
        maximum = min(
            self.contact_sheet_max_dimension_px,
            780 if compact else self.contact_sheet_max_dimension_px,
        )
        if longest > maximum:
            scale = maximum / longest
            canvas = canvas.resize(
                (
                    max(1, round(canvas.width * scale)),
                    max(1, round(canvas.height * scale)),
                ),
                Image.Resampling.LANCZOS,
            )

        output = io.BytesIO()
        canvas.save(
            output,
            format="JPEG",
            quality=(72 if compact else self.contact_sheet_jpeg_quality),
            optimize=True,
        )
        return output.getvalue()

    @staticmethod
    def _looks_like_chat_candidate(model_id: str) -> bool:
        """Exclude models that clearly belong to non-chat API families.

        The Groq Models endpoint currently does not expose input modalities, so
        future or account-specific chat models are kept and tested lazily. Models
        that reject images are disabled for the rest of the scan after one try.
        """
        lowered = model_id.casefold()
        excluded_markers = (
            "whisper",
            "distil-whisper",
            "orpheus",
            "text-to-speech",
            "tts",
            "prompt-guard",
            "safeguard",
            "llama-guard",
        )
        return not any(marker in lowered for marker in excluded_markers)

    @staticmethod
    def _vision_likelihood(model_id: str) -> tuple[int, str]:
        lowered = model_id.casefold()
        likely_markers = (
            "vision",
            "multimodal",
            "qwen3.6",
            "qwen-vl",
            "qwen2-vl",
            "llava",
            "pixtral",
            "llama-4",
            "scout",
            "maverick",
        )
        return (0 if any(marker in lowered for marker in likely_markers) else 1, lowered)

    def _resolve_models(self) -> None:
        if self._models_resolved:
            return
        self._models_resolved = True
        discovered: list[str] = []
        try:
            response = httpx.get(
                self.models_endpoint,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30.0,
            )
            response.raise_for_status()
            for raw in response.json().get("data", []):
                model_id = str(raw.get("id") or "").strip()
                if not model_id or raw.get("active") is False:
                    continue
                if self._looks_like_chat_candidate(model_id):
                    discovered.append(model_id)
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning(
                "Could not discover Groq account models; using configured model pool only: %s",
                exc,
            )
            if not self.models:
                raise VisionModelPoolExhaustedError(
                    "Groq model discovery failed and no fallback models are configured"
                ) from exc
            return

        discovered = list(dict.fromkeys(discovered))
        discovered.sort(key=self._vision_likelihood)
        discovered_set = set(discovered)
        for configured in self.configured_models:
            if configured not in discovered_set:
                self._disabled_models[configured] = (
                    "not returned by the Groq Models API for this account"
                )

        accessible_configured = [
            model for model in self.configured_models if model in discovered_set
        ]
        self.models = list(
            dict.fromkeys([*accessible_configured, *discovered])
        )
        LOGGER.info(
            "Groq account model discovery returned %d chat candidate(s): %s",
            len(self.models),
            ", ".join(self.models) if self.models else "none",
        )
        if not self.models:
            raise VisionModelPoolExhaustedError(
                "Groq returned no active chat-model candidates for this account"
            )

    def _candidate_models(self) -> list[str]:
        self._resolve_models()
        enabled = [
            model for model in self.models if model not in self._disabled_models
        ]
        if self._preferred_model in enabled:
            enabled.remove(self._preferred_model)
            enabled.insert(0, self._preferred_model)
        return enabled[: self.max_model_attempts_per_request]

    def _wait_for_request_slot(self, model: str) -> None:
        previous = self._last_request_started_by_model.get(model)
        if previous is not None and self.request_spacing_seconds > 0:
            elapsed = time.monotonic() - previous
            remaining = self.request_spacing_seconds - elapsed
            if remaining > 0:
                LOGGER.info(
                    "Waiting %.1f seconds before reusing Groq model %s to avoid its TPM window",
                    remaining,
                    model,
                )
                time.sleep(remaining)
        self._last_request_started_by_model[model] = time.monotonic()

    @staticmethod
    def _error_details(response: httpx.Response) -> tuple[str, str]:
        error_code = ""
        error_message = response.text[:1500]
        if response.is_error:
            try:
                error_payload = response.json().get("error") or {}
                error_code = str(error_payload.get("code") or "")
                error_message = str(error_payload.get("message") or error_message)
            except Exception:  # noqa: BLE001
                pass
        return error_code, error_message

    @staticmethod
    def _is_model_compatibility_error(status_code: int, message: str) -> bool:
        lowered = message.casefold()
        markers = (
            "does not support image",
            "doesn't support image",
            "does not support vision",
            "vision is not supported",
            "image input is not supported",
            "image inputs are not supported",
            "image_url is not supported",
            "unsupported type: image_url",
            "multimodal input",
            "unsupported content type",
            "content must be a string",
            "model not found",
            "model does not exist",
            "model is not available",
            "model is decommissioned",
            "model has been deprecated",
            "not permitted to use model",
            "permission to use model",
            "model permission",
            "do not have access",
            "not have access",
            "not allowed to use",
        )
        return status_code in {400, 403, 404, 422} and any(
            marker in lowered for marker in markers
        )

    @staticmethod
    def _is_json_mode_error(status_code: int, message: str) -> bool:
        lowered = message.casefold()
        return status_code in {400, 422} and (
            "response_format" in lowered
            or "json mode" in lowered
            or "json_object" in lowered
        )

    def _post_model_request(
        self,
        model: str,
        content: list[dict[str, Any]],
        *,
        json_mode: bool,
    ) -> httpx.Response:
        if (
            self.max_requests_per_run > 0
            and self.requests_sent >= self.max_requests_per_run
        ):
            raise VisionRunBudgetReached(
                f"Groq request budget of {self.max_requests_per_run} reached for this scan"
            )
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "top_p": 1,
            "max_completion_tokens": self.max_completion_tokens,
            "stream": False,
            "service_tier": self.service_tier,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        self._wait_for_request_slot(model)
        self.requests_sent += 1
        self.model_attempts[model] = self.model_attempts.get(model, 0) + 1
        return httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=240.0,
        )

    def _generate(self, parts: list[dict[str, Any]]) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        image_count = 0
        for part in parts:
            if "text" in part:
                content.append({"type": "text", "text": str(part["text"])})
                continue
            inline = part.get("inlineData") or {}
            if inline:
                image_count += 1
                mime = str(inline.get("mimeType") or "image/jpeg")
                data = str(inline.get("data") or "")
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{data}"},
                    }
                )

        if image_count != 1:
            raise RuntimeError(
                f"Local-crop Groq requests must contain exactly one contact-sheet image; got {image_count}"
            )

        candidates = self._candidate_models()
        if not candidates:
            reasons = "; ".join(
                f"{model}: {reason}"
                for model, reason in self._disabled_models.items()
            )
            raise VisionModelPoolExhaustedError(
                "No Groq model remains available for this scan"
                + (f" ({reasons})" if reasons else "")
            )

        too_large_errors: list[str] = []
        rate_limit_errors: list[str] = []
        transient_errors: list[str] = []

        for model in candidates:
            json_mode = True
            while True:
                LOGGER.info("Trying Groq model %s", model)
                response = self._post_model_request(
                    model,
                    content,
                    json_mode=json_mode,
                )
                error_code, error_message = self._error_details(response)
                lowered_message = error_message.casefold()

                if not response.is_error:
                    try:
                        parsed = _json_object(self._extract_text(response.json()))
                    except Exception as exc:  # noqa: BLE001
                        transient_errors.append(
                            f"{model}: invalid JSON response ({exc})"
                        )
                        LOGGER.warning(
                            "Groq model %s returned an unusable response; trying the next model: %s",
                            model,
                            exc,
                        )
                        break
                    self._preferred_model = model
                    self.model = model
                    self.model_usage[model] = self.model_usage.get(model, 0) + 1
                    return parsed

                if response.status_code == 413 and (
                    error_code == "rate_limit_exceeded"
                    or "request too large" in lowered_message
                    or (
                        "requested" in lowered_message
                        and "tokens per minute" in lowered_message
                    )
                ):
                    too_large_errors.append(f"{model}: {error_message}")
                    LOGGER.warning(
                        "Groq model %s rejected this image batch as too large; trying another model",
                        model,
                    )
                    break

                if response.status_code == 429 or error_code == "rate_limit_exceeded":
                    reason = f"rate limited: {error_message}"
                    self._disabled_models[model] = reason
                    rate_limit_errors.append(f"{model}: {error_message}")
                    LOGGER.warning(
                        "Groq model %s reached a quota; switching to the next model",
                        model,
                    )
                    break

                if json_mode and self._is_json_mode_error(
                    response.status_code, error_message
                ):
                    LOGGER.warning(
                        "Groq model %s does not accept JSON mode; retrying it with prompt-only JSON instructions",
                        model,
                    )
                    json_mode = False
                    continue

                if self._is_model_compatibility_error(
                    response.status_code, error_message
                ):
                    self._disabled_models[model] = error_message
                    LOGGER.warning(
                        "Groq model %s cannot process this vision request and will be skipped for the rest of the run: %s",
                        model,
                        error_message,
                    )
                    break

                if response.status_code in {500, 502, 503, 504}:
                    transient_errors.append(f"{model}: {error_message}")
                    LOGGER.warning(
                        "Groq model %s returned HTTP %s; trying the next model",
                        model,
                        response.status_code,
                    )
                    break

                raise RuntimeError(
                    f"Groq API returned HTTP {response.status_code} from model {model}: {error_message}"
                )

        if too_large_errors:
            raise VisionRequestTooLargeError(
                "All available Groq models rejected this request as too large: "
                + " | ".join(too_large_errors)
            )
        if rate_limit_errors or self._disabled_models:
            details = [*rate_limit_errors]
            details.extend(
                f"{model}: {reason}"
                for model, reason in self._disabled_models.items()
                if not any(item.startswith(f"{model}:") for item in details)
            )
            raise VisionModelPoolExhaustedError(
                "All Groq model candidates are rate-limited, unavailable, or incompatible: "
                + " | ".join(details)
            )
        if transient_errors:
            raise RuntimeError(
                "All Groq model candidates failed temporarily: "
                + " | ".join(transient_errors)
            )
        raise VisionModelPoolExhaustedError(
            "No Groq model candidate could complete the vision request"
        )

    def _download_images(self, image_urls: list[str]) -> list[DownloadedImage]:
        images: list[DownloadedImage] = []
        total_raw_bytes = 0
        max_raw_bytes = 30_000_000
        for index, image_url in enumerate(image_urls, start=1):
            try:
                response = httpx.get(
                    image_url,
                    timeout=30.0,
                    follow_redirects=True,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "Chrome/130 Safari/537.36"
                        )
                    },
                )
                response.raise_for_status()
                if len(response.content) > 10_000_000:
                    raise ValueError("image is larger than 10 MB")
                if total_raw_bytes + len(response.content) > max_raw_bytes:
                    LOGGER.warning(
                        "Skipping image because the listing image download budget would be exceeded"
                    )
                    continue
                mime = response.headers.get("content-type", "image/jpeg").split(";")[0]
                if mime not in {
                    "image/png",
                    "image/jpeg",
                    "image/webp",
                    "image/heic",
                    "image/heif",
                }:
                    mime = "image/jpeg"
                images.append(
                    DownloadedImage(
                        image_index=index,
                        url=image_url,
                        mime_type=mime,
                        data=response.content,
                    )
                )
                total_raw_bytes += len(response.content)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning("Could not download image for local analysis: %s", exc)
        return images

    @staticmethod
    def _inline_part(mime_type: str, data: bytes) -> dict[str, Any]:
        return {
            "inlineData": {
                "mimeType": mime_type,
                "data": base64.b64encode(data).decode("ascii"),
            }
        }

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        choices = data.get("choices") or []
        for choice in choices:
            message = choice.get("message") or {}
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content
        raise ValueError("Groq response did not contain text content")
