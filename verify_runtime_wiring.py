from __future__ import annotations

import importlib
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parent
    required = [
        root / "src/pokemon_deal_bot/__init__.py",
        root / "src/pokemon_deal_bot/updated_main.py",
        root / "src/pokemon_deal_bot/tier2_vision.py",
    ]
    missing = [str(path.relative_to(root)) for path in required if not path.exists()]
    if missing:
        raise SystemExit("Missing hotfix files: " + ", ".join(missing))

    module = importlib.import_module("pokemon_deal_bot.manual_main")
    analyzer_module = importlib.import_module("pokemon_deal_bot.gemini_vision")
    analyzer = analyzer_module.GeminiLotVisionAnalyzer
    if not callable(getattr(module.updated_main, "run", None)):
        raise SystemExit("updated_main.run is not available")
    if not callable(getattr(analyzer, "screen_listing", None)):
        raise SystemExit("GeminiLotVisionAnalyzer.screen_listing is not installed")
    if not callable(getattr(analyzer, "analyze_with_overviews", None)):
        raise SystemExit("GeminiLotVisionAnalyzer.analyze_with_overviews is not installed")
    print("Runtime wiring hotfix is installed correctly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
