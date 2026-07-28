from __future__ import annotations


def test_manual_runner_runtime_modules_are_installed() -> None:
    from pokemon_deal_bot import updated_main
    from pokemon_deal_bot.gemini_vision import GeminiLotVisionAnalyzer

    assert callable(updated_main.run)
    assert callable(GeminiLotVisionAnalyzer.screen_listing)
    assert callable(GeminiLotVisionAnalyzer.analyze_with_overviews)
