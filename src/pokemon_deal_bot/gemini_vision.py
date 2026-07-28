from __future__ import annotations

import io
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx
from PIL import Image, ImageOps

from .image_processing import CardCrop, DownloadedImage
from .models import SendicoListing, VisionResult, WatchCard

from .vision import (
    LotVisionAnalyzer,
    _apply_listing_grading_hint,
    _merge_cards,
    _propagate_visible_grading,
    VisionModelPoolExhaustedError,
    VisionRequestTooLargeError,
    VisionRunBudgetReached,
    _json_object,
)

LOGGER = logging.getLogger(__name__)


_GEMINI_BATCH_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "crop_index": {"type": "integer"},
                    "name_en": {"type": "string"},
                    "name_jp": {"type": ["string", "null"]},
                    "set_name": {"type": ["string", "null"]},
                    "set_code": {"type": ["string", "null"]},
                    "card_number": {"type": "string"},
                    "rarity": {"type": ["string", "null"]},
                    "language": {"type": "string"},
                    "confidence": {"type": "number"},
                    "condition": {"type": "string"},
                    "variant": {
                        "type": "string",
                        "enum": [
                            "normal_holo",
                            "poke_ball",
                            "master_ball",
                            "reverse_holo",
                            "other",
                        ],
                    },
                    "grading_company": {"type": ["string", "null"]},
                    "grade": {"type": ["string", "null"]},
                    "grading_confidence": {"type": "number"},
                },
                "required": [
                    "crop_index",
                    "name_en",
                    "name_jp",
                    "set_name",
                    "set_code",
                    "card_number",
                    "rarity",
                    "language",
                    "confidence",
                    "condition",
                    "variant",
                    "grading_company",
                    "grade",
                    "grading_confidence",
                ],
            },
        },
        "unrecognized_crop_indexes": {
            "type": "array",
            "items": {"type": "integer"},
        },
    },
    "required": ["cards", "unrecognized_crop_indexes"],
}

_GEMINI_SCREENING_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "target_likely_present": {"type": "boolean"},
        "confidence": {"type": "number"},
        "relevant_image_indexes": {
            "type": "array",
            "items": {"type": "integer"},
        },
        "reason": {"type": "string"},
    },
    "required": [
        "target_likely_present",
        "confidence",
        "relevant_image_indexes",
        "reason",
    ],
}


@dataclass(slots=True)
class TargetScreeningResult:
    target_likely_present: bool
    confidence: float
    relevant_image_indexes: list[int]
    inspected_image_indexes: list[int]
    reason: str = ""
    model: str | None = None




class GeminiLotVisionAnalyzer(LotVisionAnalyzer):
    """Identify locally cropped cards with Gemini multimodal models.

    The inherited class contains the provider-independent local image pipeline,
    quantity anchoring, grading propagation, card parsing and watchlist matching.
    This subclass replaces only the remote model transport and retry behaviour.

    Requests use Google's stateless Interactions API (``store=false``), with
    schema-constrained JSON first and prompt-only JSON as a compatibility path.
    """

    def __init__(
        self,
        api_key: str,
        model: str | None,
        max_images: int,
        *,
        models: list[str] | tuple[str, ...] | None = None,
        max_model_attempts_per_request: int = 2,
        thinking_level: str = "low",
        max_retries_per_model: int = 2,
        retry_base_seconds: float = 2.0,
        retry_max_seconds: float = 30.0,
        api_version: str = "v1beta",
        api_revision: str | None = "2026-05-20",
        request_timeout_seconds: float = 240.0,
        max_local_crops: int = 40,
        crop_batch_size: int = 4,
        request_spacing_seconds: float = 1.0,
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
        max_requests_per_run: int = 150,
    ) -> None:
        configured = [
            str(value).strip()
            for value in (models or [])
            if str(value).strip()
        ]
        legacy_model = str(model or "").strip()
        if legacy_model and legacy_model not in configured:
            configured.append(legacy_model)
        if not configured:
            configured = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]

        super().__init__(
            api_key=api_key,
            model=configured[0],
            models=configured,
            auto_discover_models=False,
            max_model_attempts_per_request=max_model_attempts_per_request,
            service_tier="on_demand",
            max_images=max_images,
            max_local_crops=max_local_crops,
            crop_batch_size=crop_batch_size,
            request_spacing_seconds=request_spacing_seconds,
            max_completion_tokens=max_completion_tokens,
            contact_sheet_max_dimension_px=contact_sheet_max_dimension_px,
            contact_sheet_jpeg_quality=contact_sheet_jpeg_quality,
            analysis_max_dimension_px=analysis_max_dimension_px,
            crop_max_dimension_px=crop_max_dimension_px,
            crop_jpeg_quality=crop_jpeg_quality,
            minimum_card_area_ratio=minimum_card_area_ratio,
            maximum_card_area_ratio=maximum_card_area_ratio,
            minimum_rectangularity=minimum_rectangularity,
            card_aspect_ratio_min=card_aspect_ratio_min,
            card_aspect_ratio_max=card_aspect_ratio_max,
            duplicate_phash_distance=duplicate_phash_distance,
            crop_padding_percent=crop_padding_percent,
            max_requests_per_run=max_requests_per_run,
        )
        self.api_version = str(api_version or "v1beta").strip() or "v1beta"
        self.api_revision = str(api_revision or "").strip() or None
        self.endpoint = (
            f"https://generativelanguage.googleapis.com/"
            f"{self.api_version}/interactions"
        )
        self.thinking_level = self._normalize_thinking_level(thinking_level)
        self.max_retries_per_model = max(0, int(max_retries_per_model))
        self.retry_base_seconds = max(0.0, float(retry_base_seconds))
        self.retry_max_seconds = max(
            self.retry_base_seconds,
            float(retry_max_seconds),
        )
        self.request_timeout_seconds = max(10.0, float(request_timeout_seconds))
        self._output_mode_by_model: dict[str, str] = {}
        self.input_tokens = 0
        self.output_tokens = 0
        self.thought_tokens = 0
        self.total_tokens = 0

    @staticmethod
    def _normalize_thinking_level(value: str) -> str:
        normalized = str(value or "low").strip().lower()
        return normalized if normalized in {"minimal", "low", "medium", "high"} else "low"

    @property
    def usage_summary(self) -> str:
        return (
            f"input {self.input_tokens:,}; output {self.output_tokens:,}; "
            f"thinking {self.thought_tokens:,}; total {self.total_tokens:,} tokens"
        )

    @staticmethod
    def _output_modes(start_mode: str) -> list[str]:
        modes = ["schema", "prompt"]
        if start_mode not in modes:
            return modes
        return modes[modes.index(start_mode) :]

    def _interaction_input(self, parts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        interaction_input: list[dict[str, Any]] = []
        for part in parts:
            if "text" in part:
                interaction_input.append(
                    {"type": "text", "text": str(part["text"])}
                )
                continue
            inline = part.get("inlineData") or {}
            if inline:
                interaction_input.append(
                    {
                        "type": "image",
                        "data": str(inline.get("data") or ""),
                        "mime_type": str(
                            inline.get("mimeType") or "image/jpeg"
                        ),
                    }
                )
        return interaction_input

    def _post_model_request(
        self,
        model: str,
        parts: list[dict[str, Any]],
        *,
        output_mode: str,
        response_schema: dict[str, Any],
        max_output_tokens: int | None = None,
        thinking_level: str | None = None,
    ) -> httpx.Response:
        if (
            self.max_requests_per_run > 0
            and self.requests_sent >= self.max_requests_per_run
        ):
            raise VisionRunBudgetReached(
                f"Gemini request budget of {self.max_requests_per_run} reached for this scan"
            )

        payload: dict[str, Any] = {
            "model": model,
            "input": self._interaction_input(parts),
            "store": False,
            "generation_config": {
                "thinking_level": self._normalize_thinking_level(
                    thinking_level or self.thinking_level
                ),
                "max_output_tokens": int(
                    max_output_tokens or self.max_completion_tokens
                ),
            },
        }
        if output_mode == "schema":
            payload["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": response_schema,
            }

        headers = {
            "x-goog-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        if self.api_revision:
            headers["Api-Revision"] = self.api_revision

        self._wait_for_request_slot(model)
        self.requests_sent += 1
        self.model_attempts[model] = self.model_attempts.get(model, 0) + 1
        return httpx.post(
            self.endpoint,
            headers=headers,
            json=payload,
            timeout=self.request_timeout_seconds,
        )

    @staticmethod
    def _error_details(response: httpx.Response) -> tuple[str, str]:
        status = ""
        message = response.text[:2000]
        try:
            error = response.json().get("error") or {}
            status = str(error.get("status") or error.get("code") or "")
            message = str(error.get("message") or message)
        except Exception:  # noqa: BLE001
            pass
        return status, message

    @staticmethod
    def _is_output_format_error(status_code: int, message: str) -> bool:
        if status_code not in {400, 422}:
            return False
        lowered = message.casefold()
        markers = (
            "response_format",
            "response format",
            "mime_type",
            "response schema",
            "json schema",
            "schema is not supported",
            "unknown name \"response_format\"",
        )
        return any(marker in lowered for marker in markers)

    @staticmethod
    def _is_request_too_large(status_code: int, message: str) -> bool:
        lowered = message.casefold()
        markers = (
            "request too large",
            "payload size",
            "request payload size exceeds",
            "input token count exceeds",
            "too many input tokens",
            "maximum context length",
            "exceeds the maximum number of tokens",
        )
        return status_code == 413 or any(marker in lowered for marker in markers)

    @staticmethod
    def _is_model_unavailable(status_code: int, message: str) -> bool:
        lowered = message.casefold()
        markers = (
            "model is not found",
            "model not found",
            "is not found for api version",
            "is not supported for interactions",
            "model is not supported",
            "model has been deprecated",
        )
        return status_code == 404 or (
            status_code in {400, 403} and any(marker in lowered for marker in markers)
        )

    @staticmethod
    def _retry_delay_seconds(
        response: httpx.Response,
        retry_number: int,
        base_seconds: float,
        maximum_seconds: float,
    ) -> float:
        header = response.headers.get("retry-after")
        if header:
            try:
                return min(maximum_seconds, max(0.0, float(header)))
            except ValueError:
                pass

        try:
            details = (response.json().get("error") or {}).get("details") or []
            for detail in details:
                retry_delay = str(
                    detail.get("retryDelay")
                    or detail.get("retry_delay")
                    or ""
                )
                match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)s", retry_delay)
                if match:
                    return min(maximum_seconds, float(match.group(1)))
        except Exception:  # noqa: BLE001
            pass

        return min(maximum_seconds, base_seconds * (2**retry_number))

    def _record_usage(self, data: dict[str, Any]) -> None:
        usage = data.get("usage") or {}
        input_tokens = int(usage.get("total_input_tokens") or 0)
        output_tokens = int(usage.get("total_output_tokens") or 0)
        total_tokens = int(usage.get("total_tokens") or 0)
        thought_tokens = max(0, total_tokens - input_tokens - output_tokens)

        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.thought_tokens += thought_tokens
        self.total_tokens += total_tokens

    @staticmethod
    def _extract_text(data: dict[str, Any]) -> str:
        output_blocks: list[str] = []
        for step in data.get("steps") or []:
            if step.get("type") != "model_output":
                continue
            for content in step.get("content") or []:
                if content.get("type") != "text":
                    continue
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    output_blocks.append(text)

        if output_blocks:
            return "\n".join(output_blocks)

        status = str(data.get("status") or "unknown")
        raise ValueError(
            "Gemini interaction did not contain model output text "
            f"(status: {status})"
        )

    def _generate_json(
        self,
        parts: list[dict[str, Any]],
        *,
        response_schema: dict[str, Any],
        model_candidates: list[str] | None = None,
        operation: str = "identification",
        max_output_tokens: int | None = None,
        thinking_level: str | None = None,
    ) -> tuple[dict[str, Any], str]:
        candidates = list(model_candidates or self._candidate_models())
        candidates = [
            model for model in dict.fromkeys(candidates)
            if model and model not in self._disabled_models
        ][: self.max_model_attempts_per_request]
        if not candidates:
            raise VisionModelPoolExhaustedError(
                f"No configured Gemini model remains available for {operation}"
            )

        too_large_errors: list[str] = []
        rate_limit_errors: list[str] = []
        transient_errors: list[str] = []
        unavailable_errors: list[str] = []

        for model in candidates:
            start_mode = self._output_mode_by_model.get(model, "schema")
            move_to_next_model = False

            for output_mode in self._output_modes(start_mode):
                advance_output_mode = False

                for retry_number in range(self.max_retries_per_model + 1):
                    LOGGER.info(
                        "Trying Gemini model %s for %s (output mode: %s)",
                        model,
                        operation,
                        output_mode,
                    )
                    response = self._post_model_request(
                        model,
                        parts,
                        output_mode=output_mode,
                        response_schema=response_schema,
                        max_output_tokens=max_output_tokens,
                        thinking_level=thinking_level,
                    )
                    error_status, error_message = self._error_details(response)

                    if not response.is_error:
                        data = response.json()
                        self._record_usage(data)
                        try:
                            parsed = _json_object(self._extract_text(data))
                        except Exception as exc:  # noqa: BLE001
                            if retry_number < self.max_retries_per_model:
                                delay = min(
                                    self.retry_max_seconds,
                                    self.retry_base_seconds * (2**retry_number),
                                )
                                LOGGER.warning(
                                    "Gemini model %s returned unusable JSON during %s; "
                                    "retrying in %.1f seconds: %s",
                                    model,
                                    operation,
                                    delay,
                                    exc,
                                )
                                if delay > 0:
                                    time.sleep(delay)
                                continue

                            if output_mode == "schema":
                                LOGGER.warning(
                                    "Gemini model %s exhausted structured-output "
                                    "retries during %s; trying prompt-only JSON: %s",
                                    model,
                                    operation,
                                    exc,
                                )
                                advance_output_mode = True
                                break

                            transient_errors.append(
                                f"{model}: invalid JSON response ({exc})"
                            )
                            move_to_next_model = True
                            break

                        self._preferred_model = model
                        self._output_mode_by_model[model] = output_mode
                        self.model = model
                        self.model_usage[model] = self.model_usage.get(model, 0) + 1
                        LOGGER.info(
                            "Gemini model %s succeeded for %s; cumulative usage: %s",
                            model,
                            operation,
                            self.usage_summary,
                        )
                        return parsed, model

                    if self._is_output_format_error(
                        response.status_code,
                        error_message,
                    ):
                        if output_mode == "schema":
                            LOGGER.warning(
                                "Gemini model %s rejected structured output during "
                                "%s; trying prompt-only JSON: %s",
                                model,
                                operation,
                                error_message,
                            )
                            advance_output_mode = True
                            break
                        transient_errors.append(
                            f"{model}: output format error ({error_message})"
                        )
                        move_to_next_model = True
                        break

                    if self._is_request_too_large(
                        response.status_code,
                        error_message,
                    ):
                        too_large_errors.append(f"{model}: {error_message}")
                        move_to_next_model = True
                        break

                    if self._is_model_unavailable(
                        response.status_code,
                        error_message,
                    ):
                        self._disabled_models[model] = error_message
                        unavailable_errors.append(f"{model}: {error_message}")
                        LOGGER.warning(
                            "Gemini model %s is unavailable during %s; trying the "
                            "next configured model: %s",
                            model,
                            operation,
                            error_message,
                        )
                        move_to_next_model = True
                        break

                    if response.status_code in {401, 403}:
                        raise RuntimeError(
                            "Gemini API authentication, billing or permission "
                            f"failure (HTTP {response.status_code}, {error_status}): "
                            f"{error_message}"
                        )

                    if response.status_code == 429 or error_status == "RESOURCE_EXHAUSTED":
                        if retry_number < self.max_retries_per_model:
                            delay = self._retry_delay_seconds(
                                response,
                                retry_number,
                                self.retry_base_seconds,
                                self.retry_max_seconds,
                            )
                            LOGGER.warning(
                                "Gemini model %s is rate-limited during %s; retrying "
                                "in %.1f seconds (%d/%d)",
                                model,
                                operation,
                                delay,
                                retry_number + 1,
                                self.max_retries_per_model,
                            )
                            if delay > 0:
                                time.sleep(delay)
                            continue
                        rate_limit_errors.append(f"{model}: {error_message}")
                        move_to_next_model = True
                        break

                    if response.status_code in {500, 502, 503, 504}:
                        if retry_number < self.max_retries_per_model:
                            delay = self._retry_delay_seconds(
                                response,
                                retry_number,
                                self.retry_base_seconds,
                                self.retry_max_seconds,
                            )
                            LOGGER.warning(
                                "Gemini model %s returned HTTP %s during %s; "
                                "retrying in %.1f seconds (%d/%d)",
                                model,
                                response.status_code,
                                operation,
                                delay,
                                retry_number + 1,
                                self.max_retries_per_model,
                            )
                            if delay > 0:
                                time.sleep(delay)
                            continue
                        transient_errors.append(f"{model}: {error_message}")
                        move_to_next_model = True
                        break

                    raise RuntimeError(
                        f"Gemini API returned HTTP {response.status_code} "
                        f"({error_status}) from model {model} during {operation}: "
                        f"{error_message}"
                    )

                if move_to_next_model:
                    break
                if advance_output_mode:
                    continue

            if move_to_next_model:
                continue

        if too_large_errors:
            raise VisionRequestTooLargeError(
                f"All configured Gemini models rejected the {operation} request "
                "as too large: " + " | ".join(too_large_errors)
            )
        if rate_limit_errors:
            details = [*rate_limit_errors, *unavailable_errors]
            raise VisionModelPoolExhaustedError(
                f"All configured Gemini models are rate-limited or unavailable "
                f"for {operation}: " + " | ".join(details)
            )
        if transient_errors:
            raise RuntimeError(
                f"All configured Gemini models failed temporarily during "
                f"{operation}: "
                + " | ".join([*transient_errors, *unavailable_errors])
            )
        if unavailable_errors:
            raise VisionModelPoolExhaustedError(
                f"No configured Gemini model is currently available for "
                f"{operation}: " + " | ".join(unavailable_errors)
            )
        raise VisionModelPoolExhaustedError(
            f"No configured Gemini model could complete {operation}"
        )

    def _generate(self, parts: list[dict[str, Any]]) -> dict[str, Any]:
        image_count = sum(1 for part in parts if part.get("inlineData"))
        if image_count != 1:
            raise RuntimeError(
                "Local-crop Gemini requests must contain exactly one "
                f"contact-sheet image; got {image_count}"
            )
        payload, _ = self._generate_json(
            parts,
            response_schema=_GEMINI_BATCH_RESPONSE_SCHEMA,
            operation="card identification",
        )
        return payload

    @staticmethod
    def _clamp_screening_confidence(value: Any) -> float:
        try:
            return max(0.0, min(1.0, float(value or 0.0)))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _compress_overview_image(
        image: DownloadedImage,
        *,
        maximum_dimension_px: int,
        jpeg_quality: int,
    ) -> bytes:
        with Image.open(io.BytesIO(image.data)) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            longest = max(source.size)
            if longest > maximum_dimension_px:
                scale = maximum_dimension_px / longest
                source = source.resize(
                    (
                        max(1, round(source.width * scale)),
                        max(1, round(source.height * scale)),
                    ),
                    Image.Resampling.LANCZOS,
                )
            output = io.BytesIO()
            source.save(
                output,
                format="JPEG",
                quality=max(55, min(90, int(jpeg_quality))),
                optimize=True,
            )
            return output.getvalue()

    def _detect_candidates_by_image(
        self,
        downloaded: list[DownloadedImage],
    ) -> dict[int, list[Any]]:
        candidates_by_image: dict[int, list[Any]] = {}
        for image in downloaded:
            try:
                candidates = self.extractor._extract_from_image(image)
            except Exception as exc:  # noqa: BLE001
                LOGGER.warning(
                    "Local screening card detection failed for image %s: %s",
                    image.image_index,
                    exc,
                )
                candidates = []
            candidates_by_image[image.image_index] = candidates
            LOGGER.info(
                "Tier 2 screening found %d card-shaped region(s) in image %d",
                len(candidates),
                image.image_index,
            )
        return candidates_by_image

    @staticmethod
    def _select_overview_indexes(
        downloaded: list[DownloadedImage],
        candidates_by_image: dict[int, list[Any]],
        *,
        maximum_images: int,
        preferred_indexes: list[int] | None = None,
    ) -> list[int]:
        available = {image.image_index for image in downloaded}
        selected: list[int] = []
        for index in preferred_indexes or []:
            if index in available and index not in selected:
                selected.append(index)

        if downloaded and downloaded[0].image_index not in selected:
            selected.append(downloaded[0].image_index)

        ranked = sorted(
            downloaded,
            key=lambda image: (
                -len(candidates_by_image.get(image.image_index, [])),
                -sum(
                    candidate.quality_score
                    for candidate in candidates_by_image.get(image.image_index, [])
                ),
                image.image_index,
            ),
        )
        for image in ranked:
            if image.image_index not in selected:
                selected.append(image.image_index)
            if len(selected) >= maximum_images:
                break
        return selected[: max(1, maximum_images)]

    def screen_listing(
        self,
        listing: SendicoListing,
        targets: list[WatchCard],
        *,
        screening_models: list[str] | tuple[str, ...] | None = None,
        maximum_overview_images: int = 4,
        maximum_dimension_px: int = 1400,
        jpeg_quality: int = 78,
    ) -> TargetScreeningResult:
        downloaded = self._download_images(listing.image_urls[: self.max_images])
        if not downloaded:
            return TargetScreeningResult(
                target_likely_present=False,
                confidence=0.0,
                relevant_image_indexes=[],
                inspected_image_indexes=[],
                reason="No listing images could be downloaded for target screening",
            )

        candidates_by_image = self._detect_candidates_by_image(downloaded)
        selected_indexes = self._select_overview_indexes(
            downloaded,
            candidates_by_image,
            maximum_images=max(1, maximum_overview_images),
        )
        by_index = {image.image_index: image for image in downloaded}
        target_payload = [
            {
                "id": target.id,
                "display_name": target.display_name,
                "english_names": target.english_names,
                "japanese_names": target.japanese_names,
                "set_name": target.set_name,
                "set_code": target.set_code,
                "card_number": target.card_number,
                "language": target.language,
            }
            for target in targets
        ]
        prompt = (
            "This is a low-cost first-pass screen of a Japanese Pokemon card lot. "
            "Decide whether any exact watchlist target is probably visible in the "
            "supplied listing images. Do not treat a related Pokemon, different card "
            "number, listing title, or seller description as visual confirmation. "
            "Set target_likely_present true when the exact printed number is readable "
            "or when the artwork/name strongly resembles the exact target and deserves "
            "a detailed pass. Use confidence no higher than 0.75 when the printed card "
            "number is not readable. relevant_image_indexes must contain only supplied "
            "listing image indexes that may show the target. Return JSON only.\n"
            f"Watchlist targets: {json.dumps(target_payload, ensure_ascii=False)}\n"
            f"Listing title (context only): {listing.title[:300]}"
        )
        parts: list[dict[str, Any]] = [{"text": prompt}]
        for index in selected_indexes:
            image = by_index[index]
            parts.append({"text": f"Listing image index {index}:"})
            parts.append(
                self._inline_part(
                    "image/jpeg",
                    self._compress_overview_image(
                        image,
                        maximum_dimension_px=max(600, maximum_dimension_px),
                        jpeg_quality=jpeg_quality,
                    ),
                )
            )

        configured_screening_models = [
            str(model).strip()
            for model in (screening_models or [])
            if str(model).strip()
        ]
        if not configured_screening_models:
            configured_screening_models = list(reversed(self.models))
        payload, used_model = self._generate_json(
            parts,
            response_schema=_GEMINI_SCREENING_RESPONSE_SCHEMA,
            model_candidates=configured_screening_models,
            operation="Tier 2 target screening",
            max_output_tokens=320,
            thinking_level="minimal",
        )
        allowed_indexes = set(selected_indexes)
        relevant = []
        for value in payload.get("relevant_image_indexes", []):
            try:
                index = int(value)
            except (TypeError, ValueError):
                continue
            if index in allowed_indexes and index not in relevant:
                relevant.append(index)
        confidence = self._clamp_screening_confidence(payload.get("confidence"))
        likely = bool(payload.get("target_likely_present"))
        if likely and not relevant:
            relevant = selected_indexes[:1]
        return TargetScreeningResult(
            target_likely_present=likely,
            confidence=confidence,
            relevant_image_indexes=relevant,
            inspected_image_indexes=selected_indexes,
            reason=str(payload.get("reason") or "").strip(),
            model=used_model,
        )

    def _extract_multi_overview_crops(
        self,
        downloaded: list[DownloadedImage],
        *,
        preferred_image_indexes: list[int] | None,
        maximum_overview_images: int,
    ) -> tuple[list[CardCrop], list[int], int]:
        candidates_by_image = self._detect_candidates_by_image(downloaded)
        selected_indexes = self._select_overview_indexes(
            downloaded,
            candidates_by_image,
            maximum_images=max(1, maximum_overview_images),
            preferred_indexes=preferred_image_indexes,
        )
        groups: list[Any] = []
        duplicates_removed = 0
        for image_index in selected_indexes:
            candidates = candidates_by_image.get(image_index, [])
            if not groups:
                groups.extend(candidates)
                continue
            matched_group_indexes: set[int] = set()
            for candidate in sorted(
                candidates,
                key=lambda item: item.quality_score,
                reverse=True,
            ):
                best_group: int | None = None
                best_distance = self.extractor.duplicate_phash_distance + 1
                for group_index, existing in enumerate(groups):
                    if group_index in matched_group_indexes:
                        continue
                    distance = (
                        candidate.perceptual_hash ^ existing.perceptual_hash
                    ).bit_count()
                    if distance < best_distance:
                        best_distance = distance
                        best_group = group_index
                if (
                    best_group is not None
                    and best_distance <= self.extractor.duplicate_phash_distance
                ):
                    matched_group_indexes.add(best_group)
                    duplicates_removed += 1
                    if candidate.quality_score > groups[best_group].quality_score:
                        groups[best_group] = candidate
                    continue
                groups.append(candidate)
                matched_group_indexes.add(len(groups) - 1)

        groups = groups[: self.extractor.max_crops]
        crops = [
            CardCrop(
                crop_index=index,
                source_image_index=item.source_image_index,
                mime_type="image/jpeg",
                data=item.data,
                perceptual_hash=item.perceptual_hash,
                quality_score=item.quality_score,
            )
            for index, item in enumerate(groups, start=1)
        ]
        LOGGER.info(
            "Detailed Tier 2 analysis selected %d crop(s) across overview images %s; "
            "removed %d alternate-photo duplicate(s)",
            len(crops),
            ", ".join(str(index) for index in selected_indexes),
            duplicates_removed,
        )
        return crops, selected_indexes, duplicates_removed

    def analyze_with_overviews(
        self,
        listing: SendicoListing,
        targets: list[WatchCard],
        *,
        preferred_image_indexes: list[int] | None = None,
        maximum_overview_images: int = 4,
    ) -> VisionResult:
        downloaded = self._download_images(listing.image_urls[: self.max_images])
        if not downloaded:
            raise RuntimeError("No listing images could be downloaded for Gemini analysis")
        LOGGER.info("Downloaded %d Sendico listing image(s)", len(downloaded))

        crops, overview_indexes, duplicates_removed = self._extract_multi_overview_crops(
            downloaded,
            preferred_image_indexes=preferred_image_indexes,
            maximum_overview_images=maximum_overview_images,
        )
        if not crops:
            return VisionResult(
                listing_type="unknown",
                target_present=False,
                target_confidence=0.0,
                cards=[],
                unidentified_card_count=0,
                notes=[
                    "Local preprocessing could not isolate card-shaped regions "
                    "from the selected overview photos; no detailed Gemini request was sent."
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
                "Gemini request budget reached before detailed Tier 2 analysis: "
                f"{remaining} request(s) remain, but {len(batches)} are planned"
            )

        identified = []
        unidentified = 0
        completed_requests = 0
        for batch_index, batch in enumerate(batches, start=1):
            LOGGER.info(
                "Sending detailed Tier 2 crop batch %d/%d to Gemini (%d crop(s))",
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
                f"Detailed Tier 2 analysis inspected overview images {overview_indexes}.",
                f"It isolated {len(crops)} crop(s) and removed {duplicates_removed} alternate-photo duplicate(s).",
                f"Gemini identification used {completed_requests} request(s) across {len(batches)} batch(es).",
                "Watchlist matching was applied locally after exact card identification.",
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
