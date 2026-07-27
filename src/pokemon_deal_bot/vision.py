from __future__ import annotations

import base64
import io
import json
import logging
import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image

from .models import IdentifiedCard, SendicoListing, VisionResult, WatchCard

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class CropRegion:
    image_index: int
    box_2d: tuple[int, int, int, int]
    confidence: float
    possible_target: bool = False


@dataclass(slots=True)
class DownloadedImage:
    image_index: int
    url: str
    mime_type: str
    data: bytes


@dataclass(slots=True)
class CardCrop:
    crop_index: int
    source_image_index: int
    mime_type: str
    data: bytes


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


def parse_vision_result(payload: dict[str, Any], target: WatchCard) -> VisionResult:
    cards: list[IdentifiedCard] = []
    target_number = target.card_number.replace(" ", "").lower()
    for raw in payload.get("cards", []):
        number = str(raw.get("card_number") or "").strip()
        if not number:
            continue
        language = str(raw.get("language") or "Japanese")
        raw_name = str(raw.get("name_en") or "").strip().lower()
        raw_set_code = str(raw.get("set_code") or "").strip().lower()
        is_target = (
            number.replace(" ", "").lower() == target_number
            and target.english_name.lower() in raw_name
            and (not raw_set_code or raw_set_code == target.set_code.lower())
        )
        cards.append(
            IdentifiedCard(
                name_en=str(raw.get("name_en") or "Unknown").strip(),
                name_jp=(str(raw.get("name_jp")).strip() if raw.get("name_jp") else None),
                set_name=(str(raw.get("set_name")).strip() if raw.get("set_name") else None),
                set_code=(str(raw.get("set_code")).strip() if raw.get("set_code") else None),
                card_number=number,
                rarity=(str(raw.get("rarity")).strip() if raw.get("rarity") else None),
                language=language,
                quantity=max(1, int(raw.get("quantity") or 1)),
                confidence=_clamp_confidence(raw.get("confidence")),
                evidence_image_indexes=[int(v) for v in raw.get("evidence_image_indexes", [])],
                condition=str(raw.get("condition") or "unknown"),
                is_target=is_target,
            )
        )
    return VisionResult(
        listing_type=str(payload.get("listing_type") or "unknown"),
        target_present=bool(payload.get("target_present")),
        target_confidence=_clamp_confidence(payload.get("target_confidence")),
        cards=cards,
        unidentified_card_count=max(0, int(payload.get("unidentified_card_count") or 0)),
        notes=[str(note) for note in payload.get("notes", [])],
    )


def parse_crop_regions(payload: dict[str, Any], minimum_confidence: float = 0.0) -> list[CropRegion]:
    regions: list[CropRegion] = []
    for raw in payload.get("crop_regions", []):
        try:
            image_index = int(raw.get("image_index") or 0)
            coords = raw.get("box_2d") or raw.get("box") or []
            if image_index < 1 or len(coords) != 4:
                continue
            y_min, x_min, y_max, x_max = [int(round(float(v))) for v in coords]
            y_min = max(0, min(1000, y_min))
            x_min = max(0, min(1000, x_min))
            y_max = max(0, min(1000, y_max))
            x_max = max(0, min(1000, x_max))
            if y_max - y_min < 20 or x_max - x_min < 20:
                continue
            confidence = _clamp_confidence(raw.get("confidence"))
            if confidence < minimum_confidence:
                continue
            regions.append(
                CropRegion(
                    image_index=image_index,
                    box_2d=(y_min, x_min, y_max, x_max),
                    confidence=confidence,
                    possible_target=bool(raw.get("possible_target")),
                )
            )
        except (TypeError, ValueError):
            continue
    return dedupe_crop_regions(regions)


def _intersection_over_union(a: CropRegion, b: CropRegion) -> float:
    if a.image_index != b.image_index:
        return 0.0
    ay1, ax1, ay2, ax2 = a.box_2d
    by1, bx1, by2, bx2 = b.box_2d
    inter_y1 = max(ay1, by1)
    inter_x1 = max(ax1, bx1)
    inter_y2 = min(ay2, by2)
    inter_x2 = min(ax2, bx2)
    inter = max(0, inter_y2 - inter_y1) * max(0, inter_x2 - inter_x1)
    area_a = max(0, ay2 - ay1) * max(0, ax2 - ax1)
    area_b = max(0, by2 - by1) * max(0, bx2 - bx1)
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def dedupe_crop_regions(regions: list[CropRegion], iou_threshold: float = 0.65) -> list[CropRegion]:
    kept: list[CropRegion] = []
    for region in sorted(regions, key=lambda item: item.confidence, reverse=True):
        if any(_intersection_over_union(region, existing) >= iou_threshold for existing in kept):
            continue
        kept.append(region)
    return sorted(kept, key=lambda item: (item.image_index, item.box_2d[0], item.box_2d[1]))


def _merge_cards(overview_cards: list[IdentifiedCard], crop_cards: list[IdentifiedCard]) -> list[IdentifiedCard]:
    # Crop results are preferred because they come from enlarged card images.
    # Multiple crop results with the same exact identity are separate physical cards,
    # so their quantities are summed. Overview results are retained only when no crop
    # result exists for the same exact card.
    crop_by_key: dict[str, IdentifiedCard] = {}
    for card in crop_cards:
        existing = crop_by_key.get(card.key)
        if existing is None:
            crop_by_key[card.key] = card
            continue
        existing.quantity += card.quantity
        existing.confidence = max(existing.confidence, card.confidence)
        existing.is_target = existing.is_target or card.is_target
        existing.evidence_image_indexes = sorted(
            set(existing.evidence_image_indexes + card.evidence_image_indexes)
        )

    merged = dict(crop_by_key)
    for card in overview_cards:
        existing = merged.get(card.key)
        if existing is None:
            merged[card.key] = card
            continue
        existing.confidence = max(existing.confidence, card.confidence)
        existing.is_target = existing.is_target or card.is_target
        existing.evidence_image_indexes = sorted(
            set(existing.evidence_image_indexes + card.evidence_image_indexes)
        )
    return list(merged.values())


class LotVisionAnalyzer:
    def __init__(
        self,
        api_key: str,
        model: str,
        max_images: int,
        *,
        two_pass_enabled: bool = True,
        two_pass_listing_types: list[str] | None = None,
        max_crops_per_listing: int = 16,
        crop_minimum_confidence: float = 0.40,
        crop_padding_percent: float = 0.06,
        crop_max_dimension_px: int = 1400,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_images = max_images
        self.two_pass_enabled = two_pass_enabled
        self.two_pass_listing_types = {
            item.lower() for item in (two_pass_listing_types or ["lot", "collection"])
        }
        self.max_crops_per_listing = max(1, max_crops_per_listing)
        self.crop_minimum_confidence = crop_minimum_confidence
        self.crop_padding_percent = max(0.0, min(0.25, crop_padding_percent))
        self.crop_max_dimension_px = max(400, crop_max_dimension_px)
        self.endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )

    def analyze(self, listing: SendicoListing, target: WatchCard) -> VisionResult:
        downloaded = self._download_images(listing.image_urls[: self.max_images])
        if not downloaded:
            raise RuntimeError("No listing images could be downloaded for Gemini analysis")

        overview_payload = self._overview_pass(listing, target, downloaded)
        overview_result = parse_vision_result(overview_payload, target)
        regions = parse_crop_regions(
            overview_payload,
            minimum_confidence=self.crop_minimum_confidence,
        )

        listing_type = overview_result.listing_type.lower()
        if (
            not self.two_pass_enabled
            or listing_type not in self.two_pass_listing_types
            or not regions
        ):
            overview_result.notes.append(
                "Two-pass crop analysis was not used for this listing."
            )
            return overview_result

        selected = self._select_regions(regions)
        crops = self._make_crops(downloaded, selected)
        if not crops:
            overview_result.notes.append(
                "Two-pass mode was enabled, but no usable card crops could be created."
            )
            return overview_result

        crop_payload = self._crop_identification_pass(listing, target, crops)
        crop_result = self._parse_crop_result(crop_payload, target, crops)
        merged_cards = _merge_cards(overview_result.cards, crop_result.cards)
        target_cards = [card for card in merged_cards if card.is_target]
        target_confidence = max(
            [card.confidence for card in target_cards] + [0.0]
        )
        identified_crop_count = len(
            {
                crop_index
                for raw in crop_payload.get("cards", [])
                for crop_index in [raw.get("crop_index")]
                if crop_index is not None
            }
        )
        unidentified = max(
            overview_result.unidentified_card_count,
            len(crops) - identified_crop_count,
        )
        notes = list(overview_result.notes)
        notes.extend(crop_result.notes)
        notes.append(
            f"Two-pass Gemini analysis: {len(selected)} regions selected, "
            f"{len(crops)} enlarged crops sent in one second request, "
            f"{identified_crop_count} crops identified."
        )

        return VisionResult(
            listing_type=overview_result.listing_type,
            target_present=bool(target_cards),
            target_confidence=target_confidence,
            cards=merged_cards,
            unidentified_card_count=unidentified,
            notes=notes,
        )

    def _overview_pass(
        self,
        listing: SendicoListing,
        target: WatchCard,
        images: list[DownloadedImage],
    ) -> dict[str, Any]:
        prompt = f"""
You are auditing a Japanese Pokemon TCG Mercari listing. This is pass 1 of a two-pass process.

TARGET CARD:
- English name: {target.english_name}
- Japanese name: {target.japanese_name}
- Set: {target.set_name}
- Set code: {target.set_code}
- Card number: {target.card_number}
- Rarity: {target.rarity}

LISTING TITLE:
{listing.title}

LISTING TEXT:
{listing.description[:12000]}

Tasks:
1. Classify the listing as single, lot, collection, or unknown.
2. Identify any Japanese raw Pokemon cards whose exact card number is already readable. Do not guess.
3. Locate every distinct raw card visible in the best overview/group image. Return one bounding box per physical card. Prefer the image containing the most distinct cards and avoid duplicate regions from alternate views.
4. Bounding boxes use normalized 0-1000 coordinates in this exact order: [y_min, x_min, y_max, x_max]. image_index is 1-based in the order supplied.
5. Mark possible_target true only when the card artwork or visible text resembles {target.english_name}/{target.japanese_name}. This is only a locator hint, not final identification.
6. Ignore slabs, sleeves without cards, boxes, accessories and non-Pokemon cards.

Return JSON only:
{{
  "listing_type": "single|lot|collection|unknown",
  "target_present": false,
  "target_confidence": 0.0,
  "cards": [
    {{
      "name_en": "Victini",
      "name_jp": "ビクティニ",
      "set_name": "Pokemon Japanese Black Bolt",
      "set_code": "sv11B",
      "card_number": "097/086",
      "rarity": "AR",
      "language": "Japanese",
      "quantity": 1,
      "confidence": 0.0,
      "evidence_image_indexes": [1],
      "condition": "near_mint|lightly_played|moderately_played|heavily_played|damaged|unknown"
    }}
  ],
  "crop_regions": [
    {{
      "image_index": 1,
      "box_2d": [100, 100, 500, 350],
      "confidence": 0.0,
      "possible_target": false
    }}
  ],
  "unidentified_card_count": 0,
  "notes": []
}}
""".strip()
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for image in images:
            parts.append({"text": f"Listing image {image.image_index}:"})
            parts.append(self._inline_part(image.mime_type, image.data))
        return self._generate(parts)

    def _crop_identification_pass(
        self,
        listing: SendicoListing,
        target: WatchCard,
        crops: list[CardCrop],
    ) -> dict[str, Any]:
        prompt = f"""
You are auditing enlarged crops from one Japanese Pokemon TCG Mercari listing. This is pass 2.

TARGET CARD:
- English name: {target.english_name}
- Japanese name: {target.japanese_name}
- Set code: {target.set_code}
- Card number: {target.card_number}

Each supplied crop is labelled with a crop_index. Usually each crop contains one physical card.
Identify a card only when its exact printed card number is readable or the identity is otherwise unmistakable from the exact artwork and set context. Do not invent a number. Include Japanese raw Pokemon cards only. Return one entry for every confidently identified crop. If two crops show two physical copies of the same card, return both entries with quantity 1; the software will combine them. If a crop is unreadable, add its index to unrecognized_crop_indexes.

LISTING TITLE:
{listing.title}

Return JSON only:
{{
  "cards": [
    {{
      "crop_index": 1,
      "name_en": "Victini",
      "name_jp": "ビクティニ",
      "set_name": "Pokemon Japanese Black Bolt",
      "set_code": "sv11B",
      "card_number": "097/086",
      "rarity": "AR",
      "language": "Japanese",
      "quantity": 1,
      "confidence": 0.0,
      "condition": "near_mint|lightly_played|moderately_played|heavily_played|damaged|unknown"
    }}
  ],
  "unrecognized_crop_indexes": [],
  "notes": []
}}
""".strip()
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for crop in crops:
            parts.append(
                {
                    "text": (
                        f"Crop {crop.crop_index} from original listing image "
                        f"{crop.source_image_index}:"
                    )
                }
            )
            parts.append(self._inline_part(crop.mime_type, crop.data))
        return self._generate(parts)

    def _parse_crop_result(
        self,
        payload: dict[str, Any],
        target: WatchCard,
        crops: list[CardCrop],
    ) -> VisionResult:
        source_by_crop = {crop.crop_index: crop.source_image_index for crop in crops}
        normalized_cards: list[dict[str, Any]] = []
        for raw in payload.get("cards", []):
            item = dict(raw)
            try:
                crop_index = int(item.get("crop_index") or 0)
            except (TypeError, ValueError):
                crop_index = 0
            source_index = source_by_crop.get(crop_index)
            item["evidence_image_indexes"] = [source_index] if source_index else []
            item["quantity"] = 1
            normalized_cards.append(item)
        normalized = {
            "listing_type": "lot",
            "target_present": False,
            "target_confidence": 0.0,
            "cards": normalized_cards,
            "unidentified_card_count": len(payload.get("unrecognized_crop_indexes", [])),
            "notes": payload.get("notes", []),
        }
        result = parse_vision_result(normalized, target)
        targets = [card for card in result.cards if card.is_target]
        result.target_present = bool(targets)
        result.target_confidence = max(
            [card.confidence for card in targets] + [0.0]
        )
        return result

    def _select_regions(self, regions: list[CropRegion]) -> list[CropRegion]:
        # To avoid double-counting the same physical cards across front/back or
        # alternate listing images, crop only the image containing the most regions.
        counts = Counter(region.image_index for region in regions)
        selected_image = max(counts, key=lambda index: (counts[index], -index))
        selected = [region for region in regions if region.image_index == selected_image]
        selected.sort(
            key=lambda item: (
                not item.possible_target,
                -item.confidence,
                item.box_2d[0],
                item.box_2d[1],
            )
        )
        return selected[: self.max_crops_per_listing]

    def _make_crops(
        self,
        downloaded: list[DownloadedImage],
        regions: list[CropRegion],
    ) -> list[CardCrop]:
        image_map = {image.image_index: image for image in downloaded}
        crops: list[CardCrop] = []
        for region in regions:
            image = image_map.get(region.image_index)
            if image is None:
                continue
            try:
                with Image.open(io.BytesIO(image.data)) as source:
                    source = source.convert("RGB")
                    width, height = source.size
                    y_min, x_min, y_max, x_max = region.box_2d
                    left = x_min / 1000 * width
                    top = y_min / 1000 * height
                    right = x_max / 1000 * width
                    bottom = y_max / 1000 * height
                    padding_x = (right - left) * self.crop_padding_percent
                    padding_y = (bottom - top) * self.crop_padding_percent
                    left = max(0, int(left - padding_x))
                    top = max(0, int(top - padding_y))
                    right = min(width, int(right + padding_x))
                    bottom = min(height, int(bottom + padding_y))
                    if right - left < 20 or bottom - top < 20:
                        continue
                    crop = source.crop((left, top, right, bottom))
                    longest = max(crop.size)
                    if longest < self.crop_max_dimension_px:
                        scale = self.crop_max_dimension_px / longest
                        crop = crop.resize(
                            (
                                max(1, int(crop.width * scale)),
                                max(1, int(crop.height * scale)),
                            ),
                            Image.Resampling.LANCZOS,
                        )
                    output = io.BytesIO()
                    crop.save(output, format="JPEG", quality=92, optimize=True)
                    crops.append(
                        CardCrop(
                            crop_index=len(crops) + 1,
                            source_image_index=region.image_index,
                            mime_type="image/jpeg",
                            data=output.getvalue(),
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "Could not crop region from listing image %s: %s",
                    region.image_index,
                    exc,
                )
        return crops

    def _generate(self, parts: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }
        response = httpx.post(
            self.endpoint,
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=240.0,
        )
        if response.is_error:
            detail = response.text[:1500]
            raise RuntimeError(
                f"Gemini API returned HTTP {response.status_code}: {detail}"
            )
        data = response.json()
        return _json_object(self._extract_text(data))

    def _download_images(self, image_urls: list[str]) -> list[DownloadedImage]:
        images: list[DownloadedImage] = []
        total_raw_bytes = 0
        max_raw_bytes = 14_000_000
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
                if len(response.content) > 8_000_000:
                    raise ValueError("image is larger than 8 MB")
                if total_raw_bytes + len(response.content) > max_raw_bytes:
                    LOGGER.warning("Skipping image because Gemini request would be too large")
                    continue
                mime = response.headers.get("content-type", "image/jpeg").split(";")[0]
                if mime not in {"image/png", "image/jpeg", "image/webp", "image/heic", "image/heif"}:
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
                LOGGER.warning("Could not download image for Gemini analysis: %s", exc)
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
        candidates = data.get("candidates", [])
        for candidate in candidates:
            content = candidate.get("content", {})
            for part in content.get("parts", []):
                if "text" in part and part["text"]:
                    return str(part["text"])
        prompt_feedback = data.get("promptFeedback") or data.get("prompt_feedback")
        raise ValueError(
            "Gemini response did not contain text content"
            + (f": {prompt_feedback}" if prompt_feedback else "")
        )
