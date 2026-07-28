from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_scan_workflow_requires_manual_search_inputs() -> None:
    workflow = (ROOT / ".github/workflows/scan.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "target_name:" in workflow
    assert "search_terms:" in workflow
    assert "pricecharting_url:" in workflow
    assert "results_per_term:" in workflow
    assert "screening_limit:" in workflow
    assert "detailed_limit:" in workflow
    assert "pokemon_deal_bot.manual_main" in workflow
    assert "GEMINI_API_KEY" in workflow
    assert "GROQ_API_KEY" not in workflow
    assert "OPENAI_API_KEY" not in workflow
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


def test_default_config_uses_bounded_manual_limits() -> None:
    import yaml

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    sendico = config["sendico"]
    tier2 = sendico["tier2_lot_search"]
    vision = config["vision"]

    assert sendico["prefilter_watchlist_relevance"] is True
    assert sendico["max_results_per_search"] == 15
    assert sendico["maximum_scroll_rounds"] == 5
    assert sendico["search_link_stop_limit"] == 30
    assert tier2["max_screenings_per_run"] == 15
    assert tier2["generic_screening_limit"] == 0
    assert tier2["max_detailed_analyses_per_run"] == 3
    assert vision["provider"] == "gemini"
    assert vision["max_listing_analyses_per_run"] == 20
    assert vision["max_vision_requests_per_run"] == 30
    assert vision["max_model_attempts_per_request"] == 2
    assert vision["models"] == [
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
    ]
    assert vision["api_version"] == "v1beta"
    assert vision["api_revision"] == "2026-05-20"
    assert vision["thinking_level"] == "low"
    assert config["discord"]["send_completion_summary"] is True
