from __future__ import annotations

import logging
from typing import Any

import httpx

from pokemon_deal_bot.groq_model_pool import GroqModelPool

logger = logging.getLogger(__name__)


class GroqVisionError(RuntimeError):
    pass


class GroqVisionClient:
    def __init__(
        self,
        api_key: str,
        preferred_models: list[str],
        auto_discover_models: bool = True,
        service_tier: str | None = "on_demand",
        max_model_attempts: int = 8,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.api_key = api_key
        self.service_tier = service_tier
        self.max_model_attempts = max_model_attempts
        self.timeout_seconds = timeout_seconds

        self.model_pool = GroqModelPool(
            api_key=api_key,
            preferred_models=preferred_models,
            auto_discover=auto_discover_models,
        )

    def analyse_images(
        self,
        messages: list[dict[str, Any]],
        temperature: float = 0.0,
        max_tokens: int = 1800,
    ) -> dict[str, Any]:
        candidates = self.model_pool.get_candidates()

        if not candidates:
            raise GroqVisionError(
                "No Groq models are available for image analysis."
            )

        errors: list[str] = []

        for model in candidates[: self.max_model_attempts]:
            logger.info("Trying Groq model: %s", model)

            try:
                result = self._request_model(
                    model=model,
                    messages=messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                )

                self.model_pool.mark_success(model)
                return result

            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                body = exc.response.text

                if self._is_service_tier_error(status, body):
                    logger.warning(
                        "Model %s rejected service tier; retrying without it",
                        model,
                    )

                    try:
                        result = self._request_model(
                            model=model,
                            messages=messages,
                            temperature=temperature,
                            max_tokens=max_tokens,
                            include_service_tier=False,
                        )

                        self.model_pool.mark_success(model)
                        return result

                    except httpx.HTTPStatusError as retry_exc:
                        status = retry_exc.response.status_code
                        body = retry_exc.response.text

                reason = self._classify_failure(status, body)
                errors.append(f"{model}: HTTP {status}: {reason}")

                if self._should_switch_model(status, body):
                    self.model_pool.disable_model(model, reason)
                    continue

                raise GroqVisionError(
                    f"Groq request failed using {model}: "
                    f"HTTP {status}: {body}"
                ) from exc

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                errors.append(f"{model}: temporary network error: {exc}")
                logger.warning(
                    "Temporary Groq failure for %s; trying next model: %s",
                    model,
                    exc,
                )
                continue

        joined_errors = "\n".join(errors)

        raise GroqVisionError(
            "All available Groq models failed or were unavailable.\n"
            f"{joined_errors}"
        )

    def _request_model(
        self,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float,
        max_tokens: int,
        include_service_tier: bool = True,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        if include_service_tier and self.service_tier:
            payload["service_tier"] = self.service_tier

        response = httpx.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self.timeout_seconds,
        )

        response.raise_for_status()
        return response.json()

    @staticmethod
    def _is_service_tier_error(status: int, body: str) -> bool:
        text = body.lower()

        return status == 400 and (
            "service_tier" in text
            or "service tier" in text
        )

    @staticmethod
    def _should_switch_model(status: int, body: str) -> bool:
        text = body.lower()

        if status in {403, 404, 429, 500, 502, 503, 504}:
            return True

        image_incompatible_messages = (
            "image input is not supported",
            "does not support image",
            "unsupported image",
            "multimodal is not supported",
            "invalid content type",
            "model_not_found",
            "model is not permitted",
            "model is blocked",
            "model is decommissioned",
            "model has been deprecated",
        )

        return any(message in text for message in image_incompatible_messages)

    @staticmethod
    def _classify_failure(status: int, body: str) -> str:
        text = body.lower()

        if status == 429:
            return "rate limit or quota reached"

        if status == 403:
            return "model is not permitted for this API key"

        if status == 404:
            return "model is unavailable or no longer exists"

        if "image" in text or "multimodal" in text:
            return "model does not appear to support image input"

        if status >= 500:
            return "temporary Groq server error"

        return body[:500]
