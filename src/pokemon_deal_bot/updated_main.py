from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from . import discord as discord_module
from . import main as legacy_main
from .config import load_config
from .deal import sendico_fee_jpy
from .gemini_vision import GeminiLotVisionAnalyzer
from .sendico import SendicoMercariScanner
from .vision import VisionRateLimitError, VisionRunBudgetReached

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class RuntimeTelemetry:
    """Run-level counters that the existing scanner does not currently expose."""

    search_attempts: int = 0
    search_errors: int = 0
    hydration_attempts: int = 0
    hydration_errors: int = 0
    screening_attempts: int = 0
    screening_successes: int = 0
    screening_errors: int = 0
    detailed_attempts: int = 0
    detailed_successes: int = 0
    detailed_errors: int = 0
    assessments: int = 0
    processing_errors: int = 0
    paused: bool = False

    @property
    def vision_attempts(self) -> int:
        return self.screening_attempts + self.detailed_attempts

    @property
    def vision_successes(self) -> int:
        return self.screening_successes + self.detailed_successes

    @property
    def total_errors(self) -> int:
        return (
            self.search_errors
            + self.hydration_errors
            + self.screening_errors
            + self.detailed_errors
            + self.processing_errors
        )


def versioned_scan_signature(base_signature: str, vision_config: dict[str, Any]) -> str:
    """Include the active vision pipeline in listing retry-state identity.

    The existing scanner hashes only the watchlist. That means failures recorded by
    an older provider or model can suppress retries after the implementation is
    replaced. Including a deliberately editable pipeline version makes scanner
    upgrades safe while retaining deduplication within the same implementation.
    """

    models_raw = vision_config.get("models") or []
    if isinstance(models_raw, str):
        models = [models_raw]
    else:
        models = [str(value).strip() for value in models_raw if str(value).strip()]
    legacy_model = str(vision_config.get("model") or "").strip()
    if legacy_model and legacy_model not in models:
        models.append(legacy_model)

    identity = {
        "watchlist_signature": base_signature,
        "pipeline_state_version": str(
            vision_config.get(
                "pipeline_state_version",
                "gemini-tier2-multi-overview-v3",
            )
        ),
        "provider": str(vision_config.get("provider", "gemini")),
        "models": models,
        "api_version": str(vision_config.get("api_version", "v1beta")),
    }
    serialized = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def systemic_failure_reason(
    telemetry: RuntimeTelemetry,
    *,
    has_direct_urls: bool,
) -> str | None:
    """Return a reason only when the run did not complete a reliable scan path."""

    if telemetry.paused:
        return None
    if (
        telemetry.search_attempts > 0
        and telemetry.search_errors == telemetry.search_attempts
        and not has_direct_urls
    ):
        return "Every Sendico search failed; no reliable marketplace scan completed."
    if (
        telemetry.hydration_attempts > 0
        and telemetry.hydration_errors == telemetry.hydration_attempts
    ):
        return "Every selected listing failed during detail-page hydration."
    if telemetry.vision_attempts > 0 and telemetry.vision_successes == 0:
        return "Every Gemini screening or detailed-analysis attempt failed."
    return None


def _replace_fee_text(value: Any, fee_jpy: int) -> Any:
    """Replace legacy literal fee wording throughout a Discord embed."""

    if isinstance(value, str):
        return value.replace("¥800", f"¥{fee_jpy:,}")
    if isinstance(value, list):
        return [_replace_fee_text(item, fee_jpy) for item in value]
    if isinstance(value, dict):
        return {key: _replace_fee_text(item, fee_jpy) for key, item in value.items()}
    return value


def decorate_summary_embed(
    embed: dict[str, Any],
    telemetry: RuntimeTelemetry,
    summary: dict[str, Any],
    *,
    has_direct_urls: bool,
) -> dict[str, Any]:
    """Add search reliability and truthful completion status to Discord."""

    telemetry.processing_errors = max(
        telemetry.processing_errors,
        int(summary.get("errors", 0) or 0),
    )
    stop_reason = str(summary.get("stop_reason") or "").strip()
    if stop_reason:
        telemetry.paused = True

    failure_reason = systemic_failure_reason(
        telemetry,
        has_direct_urls=has_direct_urls,
    )
    if stop_reason or telemetry.paused:
        embed["title"] = "SENDICO SCAN PAUSED"
        embed["color"] = 0xF1C40F
        if stop_reason:
            embed["description"] = stop_reason[:4000]
    elif failure_reason:
        embed["title"] = "SENDICO SCAN FAILED"
        embed["description"] = failure_reason[:4000]
        embed["color"] = 0xE74C3C
    elif telemetry.total_errors:
        embed["title"] = "SENDICO SCAN COMPLETED WITH ERRORS"
        embed["description"] = (
            "The scan completed, but one or more recoverable stages failed. "
            "Review the counters below before relying on the result."
        )
        embed["color"] = 0xE67E22

    fields = embed.get("fields")
    if isinstance(fields, list):
        for field in fields:
            if not isinstance(field, dict):
                continue
            if field.get("name") == "Listings":
                existing = str(field.get("value") or "")
                field["value"] = (
                    f"Searches attempted: **{telemetry.search_attempts}**\n"
                    f"Search failures: **{telemetry.search_errors}**\n"
                    f"Hydration failures: **{telemetry.hydration_errors}**\n"
                    f"{existing}"
                )[:1024]
            elif field.get("name") == "Gemini":
                existing = str(field.get("value") or "")
                field["value"] = (
                    f"Screening failures: **{telemetry.screening_errors}**\n"
                    f"Detailed failures: **{telemetry.detailed_errors}**\n"
                    f"{existing}"
                )[:1024]
    return embed


def _mark_pause(telemetry: RuntimeTelemetry, exc: BaseException) -> None:
    if isinstance(exc, (VisionRateLimitError, VisionRunBudgetReached)):
        telemetry.paused = True


@contextmanager
def _runtime_patches(
    *,
    config: Any,
    telemetry: RuntimeTelemetry,
) -> Iterator[None]:
    """Apply compatibility-safe fixes without changing the current main.py API."""

    vision_config = dict(config.raw.get("vision", {}) or {})
    test_config = dict(config.raw.get("test_mode", {}) or {})
    has_direct_urls = any(
        str(value).strip() for value in test_config.get("direct_listing_urls", [])
    )
    fee_jpy = sendico_fee_jpy(dict(config.raw.get("sendico_fee", {}) or {}))

    original_watchlist_signature = legacy_main.watchlist_signature
    original_search = SendicoMercariScanner.search
    original_hydrate = SendicoMercariScanner.hydrate
    original_screen = getattr(GeminiLotVisionAnalyzer, "screen_listing")
    original_analyze = GeminiLotVisionAnalyzer.analyze
    original_detailed = getattr(GeminiLotVisionAnalyzer, "analyze_with_overviews")
    original_assess = legacy_main.assess_deal
    original_build_embed = discord_module.build_embed
    original_build_test_embed = discord_module.build_test_embed
    original_build_summary = discord_module.build_scan_summary_embed

    def patched_watchlist_signature(targets: list[Any]) -> str:
        return versioned_scan_signature(
            original_watchlist_signature(targets),
            vision_config,
        )

    async def tracked_search(self: Any, *args: Any, **kwargs: Any) -> Any:
        telemetry.search_attempts += 1
        try:
            return await original_search(self, *args, **kwargs)
        except Exception:
            telemetry.search_errors += 1
            raise

    async def tracked_hydrate(self: Any, *args: Any, **kwargs: Any) -> Any:
        telemetry.hydration_attempts += 1
        try:
            return await original_hydrate(self, *args, **kwargs)
        except Exception:
            telemetry.hydration_errors += 1
            raise

    def tracked_screen(self: Any, *args: Any, **kwargs: Any) -> Any:
        telemetry.screening_attempts += 1
        try:
            result = original_screen(self, *args, **kwargs)
        except Exception as exc:
            telemetry.screening_errors += 1
            _mark_pause(telemetry, exc)
            raise
        telemetry.screening_successes += 1
        return result

    def tracked_analyze(self: Any, *args: Any, **kwargs: Any) -> Any:
        telemetry.detailed_attempts += 1
        try:
            result = original_analyze(self, *args, **kwargs)
        except Exception as exc:
            telemetry.detailed_errors += 1
            _mark_pause(telemetry, exc)
            raise
        telemetry.detailed_successes += 1
        return result

    def tracked_detailed(self: Any, *args: Any, **kwargs: Any) -> Any:
        telemetry.detailed_attempts += 1
        try:
            result = original_detailed(self, *args, **kwargs)
        except Exception as exc:
            telemetry.detailed_errors += 1
            _mark_pause(telemetry, exc)
            raise
        telemetry.detailed_successes += 1
        return result

    def tracked_assess(*args: Any, **kwargs: Any) -> Any:
        result = original_assess(*args, **kwargs)
        telemetry.assessments += 1
        return result

    def configured_embed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return _replace_fee_text(original_build_embed(*args, **kwargs), fee_jpy)

    def configured_test_embed(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return _replace_fee_text(original_build_test_embed(*args, **kwargs), fee_jpy)

    def truthful_summary(*args: Any, **kwargs: Any) -> dict[str, Any]:
        embed = original_build_summary(*args, **kwargs)
        return decorate_summary_embed(
            embed,
            telemetry,
            dict(kwargs),
            has_direct_urls=has_direct_urls,
        )

    replacements: list[tuple[Any, str, Any]] = [
        (legacy_main, "watchlist_signature", patched_watchlist_signature),
        (SendicoMercariScanner, "search", tracked_search),
        (SendicoMercariScanner, "hydrate", tracked_hydrate),
        (GeminiLotVisionAnalyzer, "screen_listing", tracked_screen),
        (GeminiLotVisionAnalyzer, "analyze", tracked_analyze),
        (GeminiLotVisionAnalyzer, "analyze_with_overviews", tracked_detailed),
        (legacy_main, "assess_deal", tracked_assess),
        (discord_module, "build_embed", configured_embed),
        (discord_module, "build_test_embed", configured_test_embed),
        (discord_module, "build_scan_summary_embed", truthful_summary),
    ]
    originals: list[tuple[Any, str, Any]] = []
    for owner, name, replacement in replacements:
        originals.append((owner, name, getattr(owner, name)))
        setattr(owner, name, replacement)

    try:
        yield
    finally:
        for owner, name, original in reversed(originals):
            setattr(owner, name, original)


async def run(config_path: str, dry_run: bool = False) -> int:
    """Run the existing scanner with the reliability update applied."""

    config = load_config(config_path)
    telemetry = RuntimeTelemetry()
    test_config = dict(config.raw.get("test_mode", {}) or {})
    has_direct_urls = any(
        str(value).strip() for value in test_config.get("direct_listing_urls", [])
    )

    with _runtime_patches(config=config, telemetry=telemetry):
        exit_code = await legacy_main.run(config_path, dry_run)

    failure_reason = systemic_failure_reason(
        telemetry,
        has_direct_urls=has_direct_urls,
    )
    if failure_reason:
        LOGGER.error("Systemic scan failure: %s", failure_reason)
        return 1
    return int(exit_code)


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Sendico Mercari Japanese Pokemon deal scanner (reliability update)"
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(asyncio.run(run(args.config, args.dry_run)))


if __name__ == "__main__":
    cli()
