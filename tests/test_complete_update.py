from __future__ import annotations

from pokemon_deal_bot.gemini_vision import GeminiLotVisionAnalyzer
from pokemon_deal_bot.updated_main import (
    RuntimeTelemetry,
    _replace_fee_text,
    decorate_summary_embed,
    systemic_failure_reason,
    versioned_scan_signature,
)


def test_tier2_methods_are_available_on_existing_import_path() -> None:
    assert callable(getattr(GeminiLotVisionAnalyzer, "screen_listing", None))
    assert callable(getattr(GeminiLotVisionAnalyzer, "analyze_with_overviews", None))
    assert callable(getattr(GeminiLotVisionAnalyzer, "_extract_multi_overview_crops", None))


def test_versioned_signature_changes_with_pipeline_identity() -> None:
    base = "watchlist-hash"
    first = versioned_scan_signature(
        base,
        {
            "provider": "gemini",
            "models": ["gemini-3.6-flash"],
            "api_version": "v1beta",
            "pipeline_state_version": "v3",
        },
    )
    same = versioned_scan_signature(
        base,
        {
            "provider": "gemini",
            "models": ["gemini-3.6-flash"],
            "api_version": "v1beta",
            "pipeline_state_version": "v3",
        },
    )
    changed = versioned_scan_signature(
        base,
        {
            "provider": "gemini",
            "models": ["gemini-3.6-flash"],
            "api_version": "v1beta",
            "pipeline_state_version": "v4",
        },
    )

    assert first == same
    assert first != changed


def test_every_search_failure_is_systemic_without_direct_urls() -> None:
    telemetry = RuntimeTelemetry(search_attempts=3, search_errors=3)
    assert systemic_failure_reason(telemetry, has_direct_urls=False)
    assert systemic_failure_reason(telemetry, has_direct_urls=True) is None


def test_every_vision_attempt_failure_is_systemic() -> None:
    telemetry = RuntimeTelemetry(
        screening_attempts=2,
        screening_errors=2,
    )
    assert systemic_failure_reason(telemetry, has_direct_urls=False)


def test_paused_run_is_not_relabelled_as_systemic_failure() -> None:
    telemetry = RuntimeTelemetry(
        screening_attempts=1,
        screening_errors=1,
        paused=True,
    )
    assert systemic_failure_reason(telemetry, has_direct_urls=False) is None


def test_summary_reports_partial_errors() -> None:
    telemetry = RuntimeTelemetry(
        search_attempts=4,
        search_errors=1,
        screening_attempts=3,
        screening_successes=2,
        screening_errors=1,
    )
    embed = {
        "title": "SENDICO SCAN COMPLETED",
        "description": "Completed normally",
        "color": 0,
        "fields": [
            {"name": "Listings", "value": "Found: **12**", "inline": True},
            {"name": "Gemini", "value": "Processing errors: **1**", "inline": True},
        ],
    }

    updated = decorate_summary_embed(
        embed,
        telemetry,
        {"errors": 1, "stop_reason": None},
        has_direct_urls=False,
    )

    assert updated["title"] == "SENDICO SCAN COMPLETED WITH ERRORS"
    assert "Search failures: **1**" in updated["fields"][0]["value"]
    assert "Screening failures: **1**" in updated["fields"][1]["value"]


def test_summary_reports_systemic_failure() -> None:
    telemetry = RuntimeTelemetry(search_attempts=2, search_errors=2)
    embed = {
        "title": "SENDICO SCAN COMPLETED",
        "description": "Completed normally",
        "color": 0,
        "fields": [],
    }

    updated = decorate_summary_embed(
        embed,
        telemetry,
        {"errors": 0, "stop_reason": None},
        has_direct_urls=False,
    )

    assert updated["title"] == "SENDICO SCAN FAILED"
    assert "Every Sendico search failed" in updated["description"]


def test_configured_fee_replaces_all_legacy_discord_wording() -> None:
    embed = {
        "fields": [
            {"value": "¥800 / A$8.16"},
            {"value": "Listing + ¥800 fee"},
        ]
    }
    updated = _replace_fee_text(embed, 1_000)
    assert updated["fields"][0]["value"] == "¥1,000 / A$8.16"
    assert updated["fields"][1]["value"] == "Listing + ¥1,000 fee"
