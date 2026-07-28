"""Compatibility entry point for older workflows and tests.

The consolidated v5 runtime lives directly in :mod:`pokemon_deal_bot.main`.
This module only re-exports that implementation; it does not patch or replace it.
"""

from .main import (
    _candidate_relevance_score as candidate_relevance_score,
    _extract_seller_description as extract_seller_description,
    _has_strong_lot_evidence as strong_lot_evidence,
    cli,
    run,
)

__all__ = [
    "candidate_relevance_score",
    "extract_seller_description",
    "strong_lot_evidence",
    "cli",
    "run",
]

if __name__ == "__main__":
    cli()
