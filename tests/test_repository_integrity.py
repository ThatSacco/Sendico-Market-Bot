from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_scan_workflow_uses_groq_and_weekly_sydney_schedule() -> None:
    workflow = (ROOT / ".github/workflows/scan.yml").read_text(encoding="utf-8")

    assert "GROQ_API_KEY" in workflow
    assert "OPENAI_API_KEY" not in workflow
    assert 'cron: "0 13 * * 3"' in workflow
    assert 'cron: "0 14 * * 3"' in workflow
    assert "Australia/Sydney" in workflow
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


def test_reliability_guards_are_enabled_in_default_config() -> None:
    import yaml

    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))

    assert config["sendico"]["prefilter_watchlist_relevance"] is True
    assert config["vision"]["max_listing_analyses_per_run"] == 10
    assert config["vision"]["max_groq_requests_per_run"] == 12
    assert config["vision"]["auto_discover_models"] is True
    assert config["vision"]["max_model_attempts_per_request"] >= 2
    assert config["vision"]["models"]
    assert config["discord"]["send_completion_summary"] is True
