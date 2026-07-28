from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(f"FAILED: {message}")


def main() -> int:
    config = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    sendico = config["sendico"]
    tier2 = sendico["tier2_lot_search"]
    vision = config["vision"]

    require(sendico["max_results_per_search"] == 25, "result limit is not 25")
    require(sendico["max_raw_links_per_search"] == 60, "raw link limit is not 60")
    require(sendico["search_terms"] == [], "config.yaml still contains search terms")
    require(sendico["use_legacy_config_search_terms"] is False, "legacy searches are enabled")
    require(tier2["screening_model"] == "gemini-3.5-flash-lite", "Flash-Lite screen missing")
    require(tier2["max_screenings_per_run"] == 40, "screening limit is not 40")
    require(tier2["max_detailed_analyses_per_run"] == 12, "detailed limit is not 12")
    require(vision["max_total_tokens_per_run"] == 125000, "token budget is not 125,000")
    require(vision["token_budget_reserve_per_request"] == 5000, "token reserve is not 5,000")

    watchlist = yaml.safe_load((ROOT / "data/watchlist.yaml").read_text(encoding="utf-8"))
    active = [card for card in watchlist.get("cards", []) if card.get("active", True)]
    require(bool(active), "watchlist has no active cards")
    for card in active:
        require("searches" in card, f"{card.get('id')} has no unified searches")
        searches = [item for item in card["searches"] if item.get("active", True)]
        require(1 <= len(searches) <= 4, f"{card.get('id')} needs 1-4 active searches")
        for legacy in (
            "search_terms",
            "lot_search_terms",
            "era_lot_search_terms",
            "generic_lot_search_terms",
        ):
            require(legacy not in card, f"{card.get('id')} still contains {legacy}")

    main_source = (ROOT / "src/pokemon_deal_bot/main.py").read_text(encoding="utf-8")
    gemini_source = (ROOT / "src/pokemon_deal_bot/gemini_vision.py").read_text(encoding="utf-8")
    sendico_source = (ROOT / "src/pokemon_deal_bot/sendico.py").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/scan.yml").read_text(encoding="utf-8")

    for marker in (
        "validate_watchlist_for_run(targets)",
        "no watchlist target was confirmed; pricing skipped",
        "Detailed Gemini confirmed a single-card listing",
        "remaining eligible Tier 2",
        "max_total_tokens_per_run=int(",
    ):
        require(marker in main_source, f"main.py marker missing: {marker}")
    require("Gemini token budget reached for this scan" in gemini_source, "hard token gate missing")
    require("_install_tier2_vision(GeminiLotVisionAnalyzer)" in gemini_source, "Tier 2 methods not installed")
    require("Reached raw-link search limit" in sendico_source, "bounded scrolling missing")
    require("python -m pokemon_deal_bot.main --config config.yaml" in workflow, "workflow is not using main.py")
    require("python -m pokemon_deal_bot.updated_main" not in workflow, "workflow still uses wrapper")

    print("Sendico v5 verification passed.")
    print("Configured Gemini target: 125,000 tokens with a 5,000-token request reserve.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
