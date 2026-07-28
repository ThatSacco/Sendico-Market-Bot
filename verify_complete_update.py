from __future__ import annotations

import argparse
import compileall
import subprocess
import sys
from pathlib import Path

import yaml


REQUIRED_EXISTING_FILES = (
    "pyproject.toml",
    "requirements.txt",
    "src/pokemon_deal_bot/main.py",
    "src/pokemon_deal_bot/gemini_vision.py",
    "src/pokemon_deal_bot/vision.py",
    "src/pokemon_deal_bot/sendico.py",
    "data/watchlist.yaml",
)

REQUIRED_UPDATE_FILES = (
    "src/pokemon_deal_bot/tier2_vision.py",
    "src/pokemon_deal_bot/updated_main.py",
    "tests/test_complete_update.py",
    ".github/workflows/scan.yml",
    "config.yaml",
)


def fail(message: str) -> None:
    raise RuntimeError(message)


def verify_structure(root: Path) -> None:
    missing = [
        relative
        for relative in (*REQUIRED_EXISTING_FILES, *REQUIRED_UPDATE_FILES)
        if not (root / relative).is_file()
    ]
    if missing:
        fail("Missing required repository file(s): " + ", ".join(missing))


def verify_references(root: Path) -> None:
    workflow = (root / ".github/workflows/scan.yml").read_text(encoding="utf-8")
    expected_command = "python -m pokemon_deal_bot.updated_main --config config.yaml"
    if expected_command not in workflow:
        fail(f"Workflow does not reference the updated entry point: {expected_command}")

    config = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8")) or {}
    vision = config.get("vision") or {}
    tier2 = ((config.get("sendico") or {}).get("tier2_lot_search") or {})
    if vision.get("pipeline_state_version") != "gemini-tier2-multi-overview-v3":
        fail("config.yaml does not contain the expected pipeline_state_version")
    if int(tier2.get("screening_max_overview_images", 0)) < 6:
        fail("Tier 2 screening must inspect at least six overview images")
    if int(tier2.get("detailed_max_overview_images", 0)) < 12:
        fail("Tier 2 detailed analysis must inspect up to 12 overview images")


def verify_compile(root: Path) -> None:
    success = compileall.compile_dir(
        str(root / "src"),
        quiet=1,
        force=True,
    ) and compileall.compile_dir(
        str(root / "tests"),
        quiet=1,
        force=True,
    )
    if not success:
        fail("Python compilation failed")


def verify_imports(root: Path) -> None:
    code = (
        "from pokemon_deal_bot.gemini_vision import GeminiLotVisionAnalyzer; "
        "assert callable(getattr(GeminiLotVisionAnalyzer, 'screen_listing', None)); "
        "assert callable(getattr(GeminiLotVisionAnalyzer, 'analyze_with_overviews', None)); "
        "from pokemon_deal_bot.updated_main import versioned_scan_signature; "
        "assert versioned_scan_signature('x', {'provider':'gemini'})"
    )
    subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        check=True,
    )


def run_tests(root: Path) -> None:
    subprocess.run(
        [sys.executable, "-m", "pytest", "-q"],
        cwd=root,
        check=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the Sendico GitHub update after copying it over the repository"
    )
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Run structure, reference, compile and import checks without pytest",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    verify_structure(root)
    verify_references(root)
    verify_compile(root)
    verify_imports(root)
    if not args.skip_tests:
        run_tests(root)
    print("Sendico complete update verification passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
