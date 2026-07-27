from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GROQ_BASE_URL = "https://api.groq.com/openai/v1"


@dataclass
class GroqModelPool:
    api_key: str
    preferred_models: list[str]
    auto_discover: bool = True
    timeout_seconds: float = 30.0

    _disabled_models: set[str] = field(default_factory=set)
    _last_successful_model: str | None = None
    _discovered_models: list[str] | None = None

    def get_candidates(self) -> list[str]:
        candidates: list[str] = []

        if self._last_successful_model:
            candidates.append(self._last_successful_model)

        candidates.extend(self.preferred_models)

        if self.auto_discover:
            candidates.extend(self.discover_models())

        return [
            model
            for model in self._deduplicate(candidates)
            if model not in self._disabled_models
        ]

    def discover_models(self) -> list[str]:
        if self._discovered_models is not None:
            return self._discovered_models

        try:
            response = httpx.get(
                f"{GROQ_BASE_URL}/models",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Accept": "application/json",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()

            payload = response.json()
            discovered = [
                item["id"]
                for item in payload.get("data", [])
                if isinstance(item, dict) and item.get("id")
            ]

            self._discovered_models = self._rank_models(discovered)

            logger.info(
                "Discovered %d Groq model(s)",
                len(self._discovered_models),
            )

        except Exception as exc:
            logger.warning(
                "Could not discover Groq models; using configured models only: %s",
                exc,
            )
            self._discovered_models = []

        return self._discovered_models

    def mark_success(self, model: str) -> None:
        self._last_successful_model = model
        logger.info("Groq model succeeded: %s", model)

    def disable_model(self, model: str, reason: str) -> None:
        self._disabled_models.add(model)
        logger.warning(
            "Disabled Groq model %s for this run: %s",
            model,
            reason,
        )

    @staticmethod
    def _deduplicate(models: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []

        for model in models:
            if model and model not in seen:
                seen.add(model)
                result.append(model)

        return result

    @staticmethod
    def _rank_models(models: list[str]) -> list[str]:
        """
        Put likely multimodal models first.

        Groq's Models endpoint returns available model IDs, but it should not
        be assumed that every returned model accepts images.
        """

        excluded_terms = (
            "whisper",
            "tts",
            "guard",
            "safeguard",
            "audio",
            "distil-whisper",
        )

        filtered = [
            model
            for model in models
            if not any(term in model.lower() for term in excluded_terms)
        ]

        likely_vision_terms = (
            "vision",
            "qwen",
            "vl",
            "maverick",
        )

        return sorted(
            filtered,
            key=lambda model: (
                not any(term in model.lower() for term in likely_vision_terms),
                model,
            ),
        )
