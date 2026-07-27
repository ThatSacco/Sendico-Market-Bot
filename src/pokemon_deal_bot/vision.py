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
from PIL import Image, ImageDraw

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
        "normal_holo", "poke_ball", "master_ball", "reverse_holo", "other"
    } else "normal_holo"


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
                variant=_normalize_variant(raw.get("variant")),
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


def _merge_cards(
    overview_cards: list[IdentifiedCard],
    crop_cards: list[IdentifiedCard],
) -> list[IdentifiedCard]:
    """Return crop-only identities, combining true physical duplicates.

    The overview pass is used only to locate card regions. Its card identities are
    intentionally ignored once enlarged crop results exist, because overview guesses
    can describe the same physical card with a different set or card number.
    """
    del overview_cards
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
    return list(crop_by_key.values())


class VisionRateLimitError(RuntimeError):
    """Raised when Groq asks the scanner to pause because a quota is exhausted."""


class LotVisionAnalyzer:
    def __init__(
        self,
        api_key: str,
        model: str,
        max_images: int,
        *,
        max_images_per_request: int = 3,
        two_pass_enabled: bool = True,
        two_pass_listing_types: list[str] | None = None,
        max_crops_per_listing: int = 16,
        crop_minimum_confidence: float = 0.40,
        crop_padding_percent: float = 0.06,
        crop_max_dimension_px: int = 1400,
        supporting_images_in_crop_pass: int = 6,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.max_images = max_images
        self.max_images_per_request = max(1, min(3, max_images_per_request))
        self.two_pass_enabled = two_pass_enabled
        self.two_pass_listing_types = {
            item.lower() for item in (two_pass_listing_types or ["lot", "collection"])
        }
        self.max_crops_per_listing = max(1, max_crops_per_listing)
        self.crop_minimum_confidence = crop_minimum_confidence
        self.crop_padding_percent = max(0.0, min(0.25, crop_padding_percent))
        self.crop_max_dimension_px = max(400, crop_max_dimension_px)
        self.supporting_images_in_crop_pass = max(0, supporting_images_in_crop_pass)
        self.endpoint = "https://api.groq.com/openai/v1/chat/completions"

    def analyze(self, listing: SendicoListing, target: WatchCard) -> VisionResult:
        downloaded = self._download_images(listing.image_urls[: self.max_images])
        if not downloaded:
            raise RuntimeError("No listing images could be downloaded for Groq analysis")

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

        crop_payload = self._crop_identification_pass(
            listing, target, crops, downloaded
        )
        crop_result = self._parse_crop_result(crop_payload, target, crops)
        # Pass 1 locates the physical cards only. Pass 2 is the sole identity source.
        merged_cards = _merge_cards(overview_result.cards, crop_result.cards)
        target_cards = [card for card in merged_cards if card.is_target]
        target_confidence = max(
            [card.confidence for card in target_cards] + [0.0]
        )
        identified_crop_count = sum(card.quantity for card in merged_cards)
        unidentified = max(
            crop_result.unidentified_card_count,
            len(crops) - identified_crop_count,
        )
        notes = list(crop_result.notes)
        notes.append(
            "Overview-pass card identities were discarded; enlarged crops are the "
            "only identities used for valuation."
        )
        notes.append(
            f"Two-pass Groq analysis: {len(selected)} regions selected, "
            f"{len(crops)} enlarged crops sent in one second request, "
            f"{identified_crop_count} crops identified."
        )
        notes.append(
            f"Groq reviewed {len(downloaded)} Sendico listing photo(s); "
            f"up to {min(len(downloaded), self.supporting_images_in_crop_pass)} "
            "full-photo views were included in pass 2 when image slots were available."
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
        selected_images = self._select_overview_images(images)
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
3. Review every supplied listing photo. Alternate photos can be close-ups or foil-angle views of the same physical cards; never count them as extra copies.
4. Locate every distinct raw card visible in the best overview/group image. Return one bounding box per physical card. Prefer the image containing the most distinct cards and avoid duplicate regions from alternate views.
5. Bounding boxes use normalized 0-1000 coordinates in this exact order: [y_min, x_min, y_max, x_max]. image_index must use the original listing-image number printed before each image.
6. Mark possible_target true only when the card artwork or visible text resembles {target.english_name}/{target.japanese_name}. This is only a locator hint, not final identification.
7. Ignore slabs, sleeves without cards, boxes, accessories and non-Pokemon cards.
8. For variant, default to normal_holo. Only use poke_ball, master_ball, reverse_holo or other when a special foil/pattern is clearly proven by the photos or listing text. Standard set holofoil is normal_holo.

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
      "condition": "near_mint|lightly_played|moderately_played|heavily_played|damaged|unknown",
      "variant": "normal_holo|poke_ball|master_ball|reverse_holo|other"
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
        for image in selected_images:
            parts.append({"text": f"Original listing image {image.image_index}:"})
            parts.append(self._inline_part(image.mime_type, image.data))
        return self._generate(parts)

    def _crop_identification_pass(
        self,
        listing: SendicoListing,
        target: WatchCard,
        crops: list[CardCrop],
        supporting_images: list[DownloadedImage],
    ) -> dict[str, Any]:
        prompt = f"""
You are auditing enlarged card crops from one Japanese Pokemon TCG Mercari listing. This is pass 2.

TARGET CARD:
- English name: {target.english_name}
- Japanese name: {target.japanese_name}
- Set code: {target.set_code}
- Card number: {target.card_number}

The supplied contact sheets contain labelled panels such as Crop 1, Crop 2 and so on. Usually each panel contains one physical card. Identify a card only when its exact printed card number is readable or the identity is otherwise unmistakable from the exact artwork and set context. Do not invent a number. Include Japanese raw Pokemon cards only. Return one entry for every confidently identified crop. If two crop panels show two physical copies of the same card, return both entries with quantity 1. If a crop is unreadable, add its index to unrecognized_crop_indexes.

VARIANT RULE — IMPORTANT:
- Always default to variant normal_holo.
- Standard holofoil and ordinary non-holo printings are normal_holo.
- Only return poke_ball, master_ball, reverse_holo or other when a photo or crop clearly proves that exact special pattern.
- If the foil pattern is unclear, return normal_holo. Never infer a premium variant from a PriceCharting title.
- Supporting listing photos may show alternate angles or close-ups of the same physical cards. Use them only to verify identity, variant and condition; do not count them as extra copies.

LISTING TITLE:
{listing.title}

LISTING TEXT:
{listing.description[:8000]}

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
      "condition": "near_mint|lightly_played|moderately_played|heavily_played|damaged|unknown",
      "variant": "normal_holo|poke_ball|master_ball|reverse_holo|other"
    }}
  ],
  "unrecognized_crop_indexes": [],
  "notes": []
}}
""".strip()
        parts: list[dict[str, Any]] = [{"text": prompt}]
        sheets = self._make_crop_contact_sheets(crops)
        for sheet_index, sheet_data in enumerate(sheets, start=1):
            parts.append(
                {
                    "text": (
                        f"Crop contact sheet {sheet_index}. Read the Crop N label "
                        "above each panel and return that N as crop_index."
                    )
                }
            )
            parts.append(self._inline_part("image/jpeg", sheet_data))

        image_slots_remaining = max(0, self.max_images_per_request - len(sheets))
        if image_slots_remaining:
            selected_support = self._select_overview_images(supporting_images)
            for image in selected_support[: min(image_slots_remaining, self.supporting_images_in_crop_pass)]:
                parts.append(
                    {
                        "text": (
                            f"Supporting full listing image {image.image_index}. "
                            "Do not count copies from this supporting image."
                        )
                    }
                )
                parts.append(self._inline_part(image.mime_type, image.data))
        return self._generate(parts)

    def _parse_crop_result(
        self,
        payload: dict[str, Any],
        target: WatchCard,
        crops: list[CardCrop],
    ) -> VisionResult:
        source_by_crop = {crop.crop_index: crop.source_image_index for crop in crops}

        # The vision model can return more than one possible identity for one crop.
        # Keep only the highest-confidence identity for each physical crop.
        best_by_crop: dict[int, dict[str, Any]] = {}
        duplicate_responses = 0
        for raw in payload.get("cards", []):
            item = dict(raw)
            try:
                crop_index = int(item.get("crop_index") or 0)
            except (TypeError, ValueError):
                continue
            if crop_index not in source_by_crop:
                continue
            existing = best_by_crop.get(crop_index)
            if existing is not None:
                duplicate_responses += 1
            if existing is None or _clamp_confidence(item.get("confidence")) > _clamp_confidence(
                existing.get("confidence")
            ):
                best_by_crop[crop_index] = item

        normalized_cards: list[dict[str, Any]] = []
        for crop_index, item in sorted(best_by_crop.items()):
            source_index = source_by_crop[crop_index]
            item["evidence_image_indexes"] = [source_index]
            item["quantity"] = 1
            normalized_cards.append(item)

        unrecognized = {
            int(value)
            for value in payload.get("unrecognized_crop_indexes", [])
            if str(value).isdigit() and int(value) in source_by_crop
        }
        unrecognized.update(set(source_by_crop) - set(best_by_crop))
        notes = [str(note) for note in payload.get("notes", [])]
        if duplicate_responses:
            notes.append(
                f"Discarded {duplicate_responses} duplicate crop identity response(s); "
                "one identity is retained per physical crop."
            )

        normalized = {
            "listing_type": "lot",
            "target_present": False,
            "target_confidence": 0.0,
            "cards": normalized_cards,
            "unidentified_card_count": len(unrecognized),
            "notes": notes,
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

    def _select_overview_images(
        self,
        images: list[DownloadedImage],
    ) -> list[DownloadedImage]:
        if len(images) <= self.max_images_per_request:
            return images

        first = images[0]
        remaining = [image for image in images[1:]]
        remaining.sort(
            key=lambda image: (self._image_area(image.data), -image.image_index),
            reverse=True,
        )
        return [first, *remaining[: self.max_images_per_request - 1]]

    @staticmethod
    def _image_area(data: bytes) -> int:
        try:
            with Image.open(io.BytesIO(data)) as image:
                return image.width * image.height
        except Exception:
            return 0

    def _make_crop_contact_sheets(self, crops: list[CardCrop]) -> list[bytes]:
        if not crops:
            return []

        sheet_count = min(self.max_images_per_request, len(crops))
        chunks: list[list[CardCrop]] = [[] for _ in range(sheet_count)]
        for index, crop in enumerate(crops):
            chunks[index % sheet_count].append(crop)

        sheets: list[bytes] = []
        panel_width = 440
        panel_height = 650
        label_height = 44
        columns = 2

        for chunk in chunks:
            rows = (len(chunk) + columns - 1) // columns
            canvas = Image.new(
                "RGB",
                (columns * panel_width, rows * (panel_height + label_height)),
                "white",
            )
            draw = ImageDraw.Draw(canvas)

            for position, crop in enumerate(chunk):
                column = position % columns
                row = position // columns
                x0 = column * panel_width
                y0 = row * (panel_height + label_height)
                draw.rectangle(
                    (x0, y0, x0 + panel_width - 1, y0 + label_height - 1),
                    fill="white",
                    outline="black",
                    width=2,
                )
                draw.text((x0 + 12, y0 + 12), f"Crop {crop.crop_index}", fill="black")

                try:
                    with Image.open(io.BytesIO(crop.data)) as source:
                        source = source.convert("RGB")
                        max_width = panel_width - 16
                        max_height = panel_height - 16
                        scale = min(
                            max_width / source.width,
                            max_height / source.height,
                        )
                        resized = source.resize(
                            (
                                max(1, int(source.width * scale)),
                                max(1, int(source.height * scale)),
                            ),
                            Image.Resampling.LANCZOS,
                        )
                        image_x = x0 + (panel_width - resized.width) // 2
                        image_y = y0 + label_height + (panel_height - resized.height) // 2
                        canvas.paste(resized, (image_x, image_y))
                except Exception as exc:  # noqa: BLE001
                    LOGGER.warning(
                        "Could not place crop %s on contact sheet: %s",
                        crop.crop_index,
                        exc,
                    )

            output = io.BytesIO()
            canvas.save(output, format="JPEG", quality=90, optimize=True)
            sheets.append(output.getvalue())

        return sheets

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

        if image_count > self.max_images_per_request:
            raise RuntimeError(
                f"Groq request contains {image_count} images; configured maximum is "
                f"{self.max_images_per_request}"
            )

        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "temperature": 0.1,
            "top_p": 1,
            "max_completion_tokens": 8192,
            "response_format": {"type": "json_object"},
            "reasoning_effort": "none",
            "stream": False,
        }
        response = httpx.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=240.0,
        )
        if response.status_code == 429:
            detail = response.text[:1500]
            raise VisionRateLimitError(
                f"Groq API returned HTTP 429: {detail}"
            )
        if response.is_error:
            detail = response.text[:1500]
            raise RuntimeError(
                f"Groq API returned HTTP {response.status_code}: {detail}"
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
                    LOGGER.warning("Skipping image because the image download budget would be exceeded")
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
                LOGGER.warning("Could not download image for Groq analysis: %s", exc)
        return images

    @staticmethod
    def _inline_part(mime_type: str, data: bytes) -> dict[str, Any]:
        # Resize and recompress listing photos so Groq requests remain comfortably
        # below the per-image size limit while preserving readable card detail.
        try:
            with Image.open(io.BytesIO(data)) as source:
                source = source.convert("RGB")
                longest = max(source.size)
                if longest > 1800:
                    scale = 1800 / longest
                    source = source.resize(
                        (
                            max(1, int(source.width * scale)),
                            max(1, int(source.height * scale)),
                        ),
                        Image.Resampling.LANCZOS,
                    )
                output = io.BytesIO()
                source.save(output, format="JPEG", quality=88, optimize=True)
                mime_type = "image/jpeg"
                data = output.getvalue()
        except Exception:
            pass
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
