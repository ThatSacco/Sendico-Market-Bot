"""Sendico Japanese Pokemon card deal scanner."""

__version__ = "0.2.0"

# main.py and the repository tests already reference these Tier 2 methods on the
# existing GeminiLotVisionAnalyzer import path. Install them at package import so
# no external import or configuration reference needs to change.
from .gemini_vision import GeminiLotVisionAnalyzer  # noqa: E402
from .tier2_vision import install_on as _install_tier2_vision  # noqa: E402

_install_tier2_vision(GeminiLotVisionAnalyzer)
del _install_tier2_vision
