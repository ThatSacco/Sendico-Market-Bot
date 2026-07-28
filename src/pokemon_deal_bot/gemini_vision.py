from __future__ import annotations

import logging
import re
import time
from typing import Any

import httpx

from .vision import (
    LotVisionAnalyzer,
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
                "thinking_level": self.thinking_level,
                "max_output_tokens": self.max_completion_tokens,
            },
        }
        if output_mode == "schema":
            payload["response_format"] = {
                "type": "text",
                "mime_type": "application/json",
                "schema": _GEMINI_BATCH_RESPONSE_SCHEMA,
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

    def _generate(self, parts: list[dict[str, Any]]) -> dict[str, Any]:
        image_count = sum(1 for part in parts if part.get("inlineData"))
        if image_count != 1:
            raise RuntimeError(
                "Local-crop Gemini requests must contain exactly one "
                f"contact-sheet image; got {image_count}"
            )

        candidates = self._candidate_models()
        if not candidates:
            raise VisionModelPoolExhaustedError(
                "No configured Gemini model remains available for this scan"
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
                        "Trying Gemini model %s (output mode: %s)",
                        model,
                        output_mode,
                    )
                    response = self._post_model_request(
                        model,
                        parts,
                        output_mode=output_mode,
                    )
                    error_status, error_message = self._error_details(response)

                    if not response.is_error:
                        data = response.json()
                        # Successful HTTP responses are billable even if the model
                        # later produces unusable text, so record usage before parse.
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
                                    "Gemini model %s returned unusable JSON; "
                                    "retrying in %.1f seconds: %s",
                                    model,
                                    delay,
                                    exc,
                                )
                                if delay > 0:
                                    time.sleep(delay)
                                continue

                            if output_mode == "schema":
                                LOGGER.warning(
                                    "Gemini model %s exhausted structured-output "
                                    "retries; trying prompt-only JSON: %s",
                                    model,
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
                            "Gemini model %s succeeded; cumulative usage: %s",
                            model,
                            self.usage_summary,
                        )
                        return parsed

                    if self._is_output_format_error(
                        response.status_code,
                        error_message,
                    ):
                        if output_mode == "schema":
                            LOGGER.warning(
                                "Gemini model %s rejected structured output; "
                                "trying prompt-only JSON: %s",
                                model,
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
                            "Gemini model %s is unavailable; trying the next "
                            "configured model: %s",
                            model,
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
                                "Gemini model %s is rate-limited; retrying in "
                                "%.1f seconds (%d/%d)",
                                model,
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
                                "Gemini model %s returned HTTP %s; retrying in "
                                "%.1f seconds (%d/%d)",
                                model,
                                response.status_code,
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
                        f"({error_status}) from model {model}: {error_message}"
                    )

                if move_to_next_model:
                    break
                if advance_output_mode:
                    continue

            if move_to_next_model:
                continue

        if too_large_errors:
            raise VisionRequestTooLargeError(
                "All configured Gemini models rejected this request as too large: "
                + " | ".join(too_large_errors)
            )
        if rate_limit_errors:
            details = [*rate_limit_errors, *unavailable_errors]
            raise VisionModelPoolExhaustedError(
                "All configured Gemini models are rate-limited or unavailable: "
                + " | ".join(details)
            )
        if transient_errors:
            raise RuntimeError(
                "All configured Gemini models failed temporarily: "
                + " | ".join([*transient_errors, *unavailable_errors])
            )
        if unavailable_errors:
            raise VisionModelPoolExhaustedError(
                "No configured Gemini model is currently available: "
                + " | ".join(unavailable_errors)
            )
        raise VisionModelPoolExhaustedError(
            "No configured Gemini model could complete the vision request"
        )
