from __future__ import annotations

import csv
from pathlib import Path

import yaml

from pokemon_deal_bot.config import load_config, load_run_limits

ROOT = Path(__file__).resolve().parents[1]


def test_scan_workflow_is_manual_and_uses_watchlist_runtime() -> None:
    workflow = (ROOT / ".github/workflows/scan.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" in workflow
    assert "GEMINI_API_KEY" in workflow
    assert "GROQ_API_KEY" not in workflow
    assert "python -m pokemon_deal_bot.main --config config.yaml" in workflow
    assert "SENDICO_SEARCH_TERMS" not in workflow
    assert "actions/checkout@v7" in workflow
    assert "actions/setup-python@v7" in workflow


def test_push_workflow_runs_compile_and_tests() -> None:
    workflow = (ROOT / ".github/workflows/tests.yml").read_text(encoding="utf-8")
    assert "push:" in workflow
    assert "pull_request:" in workflow
    assert "python -m compileall -q src" in workflow
    assert "pytest -q" in workflow


def test_price_override_file_is_valid_csv() -> None:
    path = ROOT / "data/price_overrides.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
        assert handle.closed is False
    assert rows == []
    assert path.read_text(encoding="utf-8").splitlines()[0] == (
        "key,name,set_code,card_number,price_aud"
    )


def test_run_limits_are_central_and_internally_consistent() -> None:
    base = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    assert base["run_limits_file"] == "data/run_limits.yaml"
    limits = load_run_limits(ROOT / base["run_limits_file"])
    config = load_config(ROOT / "config.yaml").raw

    sendico = config["sendico"]
    tier2 = sendico["tier2_lot_search"]
    vision = config["vision"]

    assert sendico["prefilter_watchlist_relevance"] is True
    assert sendico["use_legacy_config_search_terms"] is False
    assert sendico["search_terms"] == []
    assert tier2["allow_query_only_candidates"] is False
    assert tier2["screening_enabled"] is True
    assert tier2["screening_model"] == "gemini-3.5-flash-lite"
    assert vision["provider"] == "gemini"
    assert vision["models"] == ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    assert config["discord"]["send_completion_summary"] is True

    # Tests validate relationships, not a particular tuning profile. The user can
    # change any central value without modifying Python tests.
    assert 1 <= sendico["max_results_per_search"] <= sendico["max_raw_links_per_search"]
    assert sendico["max_listings_per_run"] >= sendico["max_results_per_search"]
    if tier2["max_screenings_per_run"] > 0:
        assert tier2["era_set_screening_limit"] <= tier2["max_screenings_per_run"]
        assert tier2["generic_screening_limit"] <= tier2["max_screenings_per_run"]
    assert tier2["max_detailed_analyses_per_run"] == vision["max_listing_analyses_per_run"]
    assert vision["max_total_tokens_per_run"] > vision["token_budget_reserve_per_request"]
    assert vision["max_total_tokens_per_run"] == limits["token_budget"]["max_total_tokens_per_run"]
