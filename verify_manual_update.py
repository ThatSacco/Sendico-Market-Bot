from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parent


def require(path: str) -> Path:
    target = ROOT / path
    if not target.exists():
        raise SystemExit(f"Missing required update file: {path}")
    return target


def main() -> int:
    required = [
        ".github/workflows/scan.yml",
        ".github/workflows/tests.yml",
        "config.yaml",
        "src/pokemon_deal_bot/manual_main.py",
        "src/pokemon_deal_bot/updated_main.py",
        "src/pokemon_deal_bot/tier2_vision.py",
        "tests/test_manual_main.py",
        "tests/test_repository_integrity.py",
    ]
    for item in required:
        require(item)

    workflow = require(".github/workflows/scan.yml").read_text(encoding="utf-8")
    for token in [
        "workflow_dispatch:",
        "search_terms:",
        "pricecharting_url:",
        "pokemon_deal_bot.manual_main",
    ]:
        if token not in workflow:
            raise SystemExit(f"scan.yml is missing required token: {token}")
    if "schedule:" in workflow:
        raise SystemExit("scan.yml still contains a schedule; manual input would be bypassed")

    config = yaml.safe_load(require("config.yaml").read_text(encoding="utf-8"))
    sendico = config["sendico"]
    tier2 = sendico["tier2_lot_search"]
    if int(sendico["maximum_scroll_rounds"]) > 5:
        raise SystemExit("maximum_scroll_rounds is not safely bounded")
    if int(tier2["max_screenings_per_run"]) > 20:
        raise SystemExit("Gemini screening cap is above the manual hard limit")
    if int(tier2["max_detailed_analyses_per_run"]) > 5:
        raise SystemExit("Detailed analysis cap is above the manual hard limit")

    commands = [
        [sys.executable, "-m", "compileall", "-q", "src", "tests"],
        [sys.executable, "-m", "pytest", "-q"],
    ]
    for command in commands:
        print("Running:", " ".join(command))
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode:
            return completed.returncode

    print("Manual bounded-search update verified successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
