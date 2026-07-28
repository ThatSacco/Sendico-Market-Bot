from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from pokemon_deal_bot.gemini_vision import GeminiLotVisionAnalyzer
from pokemon_deal_bot.vision import VisionRunBudgetReached

ROOT = Path(__file__).resolve().parents[1]


def test_v5_configuration_uses_watchlist_two_pass_token_budget() -> None:
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    sendico = config["sendico"]
    tier2 = sendico["tier2_lot_search"]
    vision = config["vision"]

    assert sendico["use_legacy_config_search_terms"] is False
    assert sendico["search_terms"] == []
    assert sendico["max_results_per_search"] == 25
    assert sendico["max_raw_links_per_search"] == 60
    assert tier2["allow_query_only_candidates"] is False
    assert tier2["screening_enabled"] is True
    assert tier2["screening_model"] == "gemini-3.5-flash-lite"
    assert tier2["max_screenings_per_run"] == 40
    assert tier2["max_detailed_analyses_per_run"] == 12
    assert vision["max_total_tokens_per_run"] == 125000
    assert vision["token_budget_reserve_per_request"] == 5000
    assert vision["max_vision_requests_per_run"] == 80


def test_tier2_methods_are_installed_on_gemini_analyser() -> None:
    assert callable(getattr(GeminiLotVisionAnalyzer, "screen_listing", None))
    assert callable(getattr(GeminiLotVisionAnalyzer, "analyze_with_overviews", None))


def test_token_budget_stops_before_network_request() -> None:
    analyser = GeminiLotVisionAnalyzer(
        api_key="test-key",
        model="gemini-3.6-flash",
        max_images=1,
        max_total_tokens_per_run=125000,
        token_budget_reserve_per_request=5000,
    )
    analyser.total_tokens = 120001

    with pytest.raises(VisionRunBudgetReached, match="token budget"):
        analyser._post_model_request(
            "gemini-3.6-flash",
            [{"text": "do not send"}],
            output_mode="prompt",
        )
    assert analyser.requests_sent == 0


def test_main_pipeline_guards_pricing_and_counts_held_candidates() -> None:
    source = (ROOT / "src/pokemon_deal_bot/main.py").read_text(encoding="utf-8")
    assert "no watchlist target was confirmed; pricing skipped" in source
    assert "Detailed Gemini confirmed a single-card listing" in source
    assert "remaining eligible Tier 2" in source


def test_scan_workflow_runs_main_directly() -> None:
    workflow = (ROOT / ".github/workflows/scan.yml").read_text(encoding="utf-8")
    assert "python -m pokemon_deal_bot.main --config config.yaml" in workflow
    assert "python -m pokemon_deal_bot.updated_main" not in workflow
