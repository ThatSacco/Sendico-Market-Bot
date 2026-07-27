from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

import httpx

from .models import IdentifiedCard, SendicoListing, VisionResult, WatchCard

LOGGER = logging.getLogger(__name__)


def _json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Vision response did not contain a JSON object")
    return json.loads(cleaned[start : end + 1])


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
                confidence=max(0.0, min(1.0, float(raw.get("confidence") or 0.0))),
                evidence_image_indexes=[int(v) for v in raw.get("evidence_image_indexes", [])],
                condition=str(raw.get("condition") or "unknown"),
                is_target=is_target,
            )
        )
    return VisionResult(
        listing_type=str(payload.get("listing_type") or "unknown"),
        target_present=bool(payload.get("target_present")),
        target_confidence=max(0.0, min(1.0, float(payload.get("target_confidence") or 0.0))),
        cards=cards,
        unidentified_card_count=max(0, int(payload.get("unidentified_card_count") or 0)),
        notes=[str(note) for note in payload.get("notes", [])],
    )


class LotVisionAnalyzer:
    def __init__(self, api_key: str, model: str, max_images: int) -> None:
        self.api_key = api_key
        self.model = model
        self.max_images = max_images
        self.endpoint = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )

    def analyze(self, listing: SendicoListing, target: WatchCard) -> VisionResult:
        prompt = f"""
You are auditing a Japanese Pokemon TCG Mercari listing for purchase valuation.

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

Inspect every supplied image. Identify every visible Japanese Pokemon card that can be identified with high confidence. Do not guess hidden, blurry, partially covered, or unreadable cards. Exact card number is mandatory for inclusion. Combine duplicates and provide quantity. Only include raw cards; ignore slabs, empty sleeves, boxes and accessories. The target is present only if the artwork/name and exact number {target.card_number} are consistent.

Return JSON only with this shape:
{{
  "listing_type": "single|lot|collection|unknown",
  "target_present": true,
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
  "unidentified_card_count": 0,
  "notes": []
}}
""".strip()

        parts: list[dict[str, Any]] = [{"text": prompt}]
        total_raw_bytes = 0
        max_raw_bytes = 14_000_000

        for image_url in listing.image_urls[: self.max_images]:
            image_part, raw_size = self._image_part(image_url)
            if image_part is None:
                continue
            if total_raw_bytes + raw_size > max_raw_bytes:
                LOGGER.warning("Skipping image because Gemini request would be too large")
                continue
            parts.append(image_part)
            total_raw_bytes += raw_size

        if len(parts) == 1:
            raise RuntimeError("No listing images could be downloaded for Gemini analysis")

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": parts,
                }
            ],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
            },
        }

        response = httpx.post(
            self.endpoint,
            params={"key": self.api_key},
            json=payload,
            timeout=180.0,
        )
        if response.is_error:
            detail = response.text[:1500]
            raise RuntimeError(
                f"Gemini API returned HTTP {response.status_code}: {detail}"
            )

        data = response.json()
        text = self._extract_text(data)
        parsed = _json_object(text)
        return parse_vision_result(parsed, target)

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

    @staticmethod
    def _image_part(image_url: str) -> tuple[dict[str, Any] | None, int]:
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
            mime = response.headers.get("content-type", "image/jpeg").split(";")[0]
            if mime not in {
                "image/png",
                "image/jpeg",
                "image/webp",
                "image/heic",
                "image/heif",
            }:
                mime = "image/jpeg"
            encoded = base64.b64encode(response.content).decode("ascii")
            return (
                {
                    "inlineData": {
                        "mimeType": mime,
                        "data": encoded,
                    }
                },
                len(response.content),
            )
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("Could not download image for Gemini analysis: %s", exc)
            return None, 0
