"""Sendico Japanese Pokemon card deal scanner."""

__version__ = "0.4.0"

# main.py expects these Tier 2 methods on GeminiLotVisionAnalyzer. Keep the
# existing import path and install the implementation at package import time.
from .gemini_vision import GeminiLotVisionAnalyzer  # noqa: E402
from .tier2_vision import install_on as _install_tier2_vision  # noqa: E402

_install_tier2_vision(GeminiLotVisionAnalyzer)
del _install_tier2_vision
