from __future__ import annotations

from pathlib import Path

import pytest

from pokemon_deal_bot.config import load_config, load_run_limits, load_search_criteria
from pokemon_deal_bot.gemini_vision import GeminiLotVisionAnalyzer
from pokemon_deal_bot.vision import VisionRunBudgetReached

ROOT = Path(__file__).resolve().parents[1]


def test_configuration_uses_watchlist_two_pass_central_token_budget() -> None:
    config = load_config(ROOT / "config.yaml")
    limits = load_run_limits(config.run_limits_path or ROOT / "data/run_limits.yaml")
    criteria = load_search_criteria(config.search_criteria_path or ROOT / "data/search_criteria.yaml")
    sendico = config.raw["sendico"]
    tier2 = sendico["tier2_lot_search"]
    vision = config.raw["vision"]

    assert sendico["use_legacy_config_search_terms"] is False
    assert sendico["search_terms"] == []
    assert tier2["allow_query_only_candidates"] == criteria["discovery"]["allow_query_only_candidates"]
    assert tier2["screening_enabled"] is True
    assert tier2["screening_model"] == "gemini-3.5-flash-lite"

    assert sendico["max_results_per_search"] == limits["search"]["results_per_term"]
    assert tier2["max_screenings_per_run"] == limits["screening"]["max_listings_per_run"]
    assert tier2["max_detailed_analyses_per_run"] == limits["detailed_analysis"]["max_listings_per_run"]
    assert vision["max_listing_analyses_per_run"] == limits["detailed_analysis"]["max_listings_per_run"]
    assert vision["max_total_tokens_per_run"] == limits["token_budget"]["max_total_tokens_per_run"]
    assert vision["token_budget_reserve_per_request"] == limits["token_budget"]["reserve_per_request"]
    assert vision["max_vision_requests_per_run"] == limits["token_budget"]["max_requests_per_run"]
    assert tier2["screening_confidence_threshold"] == criteria["screening"]["minimum_target_probability"]
    assert vision["minimum_card_confidence"] == criteria["detailed_analysis"]["minimum_card_confidence"]
    assert vision["minimum_target_confidence"] == criteria["detailed_analysis"]["minimum_target_confidence"]


def test_tier2_methods_are_installed_on_gemini_analyser() -> None:
    assert callable(getattr(GeminiLotVisionAnalyzer, "screen_listing", None))
    assert callable(getattr(GeminiLotVisionAnalyzer, "analyze_with_overviews", None))


def test_token_budget_stops_before_network_request() -> None:
    effective = load_config(ROOT / "config.yaml").raw["vision"]
    maximum = int(effective["max_total_tokens_per_run"])
    reserve = int(effective["token_budget_reserve_per_request"])
    analyser = GeminiLotVisionAnalyzer(
        api_key="test-key",
        model="gemini-3.6-flash",
        max_images=1,
        max_total_tokens_per_run=maximum,
        token_budget_reserve_per_request=reserve,
    )
    analyser.total_tokens = maximum - reserve + 1
    with pytest.raises(VisionRunBudgetReached, match="token budget"):
        analyser._post_model_request(
            "gemini-3.6-flash",
            [{"text": "do not send"}],
            output_mode="prompt",
        )
    assert analyser.requests_sent == 0


def test_runtime_support_contains_pricing_single_card_and_held_guards() -> None:
    source = (
        ROOT / "src/pokemon_deal_bot/tier2_vision.py"
    ).read_text(encoding="utf-8")
    assert "no watchlist target was confirmed; pricing skipped" in source
    assert "Detailed Gemini confirmed a single-card listing" in source
    assert "remaining eligible Tier 2" in source


def test_scan_workflow_runs_main_directly() -> None:
    workflow = (ROOT / ".github/workflows/scan.yml").read_text(encoding="utf-8")
    assert "python -m pokemon_deal_bot.main --config config.yaml" in workflow
    assert "python -m pokemon_deal_bot.updated_main" not in workflow
