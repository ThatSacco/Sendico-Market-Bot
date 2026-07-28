"""Sendico Japanese Pokemon card deal scanner."""

__version__ = "0.5.2"

# Install the two-pass methods, 125k token budget and result guards before the
# main runtime imports Gemini, PriceCharting or Discord functions.
from .tier2_vision import install_runtime_support as _install_runtime_support

_install_runtime_support()
del _install_runtime_support
