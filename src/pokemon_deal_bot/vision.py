from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
import unicodedata
from dataclasses import dataclass
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
    """Combine separate physical crops that identify as the same exact card."""
    by_key: dict[str, IdentifiedCard] = {}
    for card in cards:
        existing = by_key.get(card.key)
        if existing is None:
            by_key[card.key] = card
            continue
        existing.quantity += card.quantity
        existing.confidence = max(existing.confidence, card.confidence)
        existing.is_target = existing.is_target or card.is_target
        existing.matched_watchlist_ids = list(
            dict.fromkeys(
                [*existing.matched_watchlist_ids, *card.matched_watchlist_ids]
            )
        )
        existing.evidence_image_indexes = sorted(
            set(existing.evidence_image_indexes + card.evidence_image_indexes)
        )
    return list(by_key.values())


class LotVisionAnalyzer:
    """Identify locally cropped cards with small, paced Groq vision requests."""

    def __init__(
        self,
        api_key: str,
        model: str,
        max_images: int,
        *,
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
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_images = max(1, max_images)
        self.crop_batch_size = max(1, min(8, crop_batch_size))
        self.request_spacing_seconds = max(0.0, request_spacing_seconds)
        self.max_completion_tokens = max(256, min(4096, max_completion_tokens))
        self.contact_sheet_max_dimension_px = max(500, contact_sheet_max_dimension_px)
        self.contact_sheet_jpeg_quality = max(55, min(92, contact_sheet_jpeg_quality))
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"
        self._last_request_started: float | None = None
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

        merged = _merge_cards(identified)
        matched_ids = list(
            dict.fromkeys(
                target_id
                for card in merged
                for target_id in card.matched_watchlist_ids
            )
        )
        target_cards = [card for card in merged if card.is_target]
        if len(crops) == 1:
            listing_type = "single"
        elif len(crops) <= 8:
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
                "Alternate listing-photo duplicates were removed locally before Groq identification.",
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
            "Identify the Japanese raw Pokemon card in each labelled panel. "
            "Return one card at most per panel. Use the exact printed card number; "
            "if it is unreadable or uncertain, put that panel in unrecognized_crop_indexes. "
            "Do not guess. Default variant to normal_holo. Use poke_ball, master_ball, "
            "reverse_holo or other only when that special pattern is clearly visible. "
            f"Listing title: {listing.title[:300]}\n"
            f"Panel indexes in this request: {crop_indexes}.\n"
            "Return JSON only in this shape: "
            '{"cards":[{"crop_index":1,"name_en":"","name_jp":null,'
            '"set_name":null,"set_code":null,"card_number":"","rarity":null,'
            '"language":"Japanese","confidence":0.0,"condition":"unknown",'
            '"variant":"normal_holo"}],"unrecognized_crop_indexes":[]}'
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

    def _wait_for_request_slot(self) -> None:
        if self._last_request_started is not None and self.request_spacing_seconds > 0:
            elapsed = time.monotonic() - self._last_request_started
            remaining = self.request_spacing_seconds - elapsed
            if remaining > 0:
                LOGGER.info(
                    "Waiting %.1f seconds before the next Groq request to avoid the free-tier TPM window",
                    remaining,
                )
                time.sleep(remaining)
        self._last_request_started = time.monotonic()

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

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "top_p": 1,
            "max_completion_tokens": self.max_completion_tokens,
            "response_format": {"type": "json_object"},
            "reasoning_effort": "none",
            "stream": False,
        }
        self._wait_for_request_slot()
        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=240.0,
        )

        error_code = ""
        error_message = response.text[:1500]
        if response.is_error:
            try:
                error_payload = response.json().get("error") or {}
                error_code = str(error_payload.get("code") or "")
                error_message = str(error_payload.get("message") or error_message)
            except Exception:  # noqa: BLE001
                pass

        lowered_message = error_message.lower()
        if response.status_code == 413 and (
            error_code == "rate_limit_exceeded"
            or "request too large" in lowered_message
            or "requested" in lowered_message and "tokens per minute" in lowered_message
        ):
            raise VisionRequestTooLargeError(
                f"Groq API returned HTTP 413: {error_message}"
            )
        if response.status_code == 429 or error_code == "rate_limit_exceeded":
            raise VisionRateLimitError(
                f"Groq API returned HTTP {response.status_code}: {error_message}"
            )
        if response.is_error:
            raise RuntimeError(
                f"Groq API returned HTTP {response.status_code}: {error_message}"
            )
        data = response.json()
        return _json_object(self._extract_text(data))

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
