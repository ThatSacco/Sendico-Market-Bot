from __future__ import annotations

import csv
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_scan_workflow_is_manual_and_uses_watchlist_runtime() -> None:
    workflow = (ROOT / ".github/workflows/scan.yml").read_text(encoding="utf-8")
    assert "workflow_dispatch:" in workflow
    assert "schedule:" not in workflow
    assert "GEMINI_API_KEY" in workflow
    assert "GROQ_API_KEY" not in workflow
    assert "python -m pokemon_deal_bot.updated_main --config config.yaml" in workflow
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


def test_default_config_uses_bounded_limits() -> None:
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    sendico = config["sendico"]
    tier2 = sendico["tier2_lot_search"]
    vision = config["vision"]
    assert sendico["prefilter_watchlist_relevance"] is True
    assert sendico["max_results_per_search"] == 15
    assert sendico["max_raw_links_per_search"] == 40
    assert tier2["max_screenings_per_run"] == 15
    assert tier2["max_detailed_analyses_per_run"] == 3
    assert vision["provider"] == "gemini"
    assert vision["max_listing_analyses_per_run"] == 3
    assert vision["max_vision_requests_per_run"] == 30
    assert vision["models"] == ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    assert config["discord"]["send_completion_summary"] is True
