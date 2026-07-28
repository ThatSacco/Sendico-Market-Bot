from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import yaml

from .models import WatchCard


@dataclass(slots=True)
class AppConfig:
    raw: dict[str, Any]
    root: Path

    @property
    def minimum_seller_positive_ratings(self) -> int:
        return int(self.raw["minimum_seller_positive_ratings"])

    @property
    def minimum_saving_percent(self) -> float:
        return float(self.raw.get("minimum_saving_percent", 0.0))

    @property
    def discord_webhook_url(self) -> str | None:
        return os.getenv("DISCORD_WEBHOOK_URL")

    @property
    def gemini_api_key(self) -> str | None:
        return os.getenv("GEMINI_API_KEY")

    @property
    def groq_api_key(self) -> str | None:
        """Legacy compatibility for older checkouts; production uses Gemini."""
        return os.getenv("GROQ_API_KEY")

    def path(self, relative: str) -> Path:
        return self.root / relative


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return AppConfig(raw=raw, root=config_path.parent)


def load_watchlist(config: AppConfig) -> list[WatchCard]:
    path = config.path("data/watchlist.yaml")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    cards = [
        WatchCard(**item)
        for item in data.get("cards", [])
        if item.get("active", True)
    ]
    duplicate_ids = sorted(
        card_id
        for card_id in {card.id for card in cards}
        if sum(card.id == card_id for card in cards) > 1
    )
    if duplicate_ids:
        raise ValueError(
            "Active watchlist ids must be unique: " + ", ".join(duplicate_ids)
        )
    if not cards:
        raise ValueError("data/watchlist.yaml has no active watchlist entries")
    return cards


def validate_watchlist_for_run(targets: list[WatchCard]) -> None:
    """Fail before Sendico opens when the user-controlled watchlist is unsafe."""

    for target in targets:
        searches = target.active_searches
        if not searches:
            raise ValueError(
                f"Active watchlist entry {target.id!r} has no active searches"
            )
        if len(searches) > 4:
            raise ValueError(
                f"Active watchlist entry {target.id!r} has {len(searches)} active "
                "searches; the maximum is 4"
            )
        folded = [search.term.casefold() for search in searches]
        if len(folded) != len(set(folded)):
            raise ValueError(
                f"Active watchlist entry {target.id!r} contains duplicate search terms"
            )
        if target.match_mode == "exact_card" and not target.pricecharting_url:
            raise ValueError(
                f"Exact-card watchlist entry {target.id!r} requires pricecharting_url"
            )


def watchlist_search_terms(targets: list[WatchCard]) -> list[str]:
    """Return only user-entered active ``exact`` searches; never generate terms."""

    return _unique_terms(
        [
            search.term
            for target in targets
            for search in target.active_searches
            if search.mode == "exact"
        ]
    )


def _unique_terms(values: list[str]) -> list[str]:
    return list(dict.fromkeys(term.strip() for term in values if term.strip()))


def watchlist_era_lot_search_terms(targets: list[WatchCard]) -> list[str]:
    """Return user-entered active focused-lot searches."""

    return _unique_terms(
        [
            search.term
            for target in targets
            for search in target.active_searches
            if search.mode == "focused_lot"
        ]
    )


def watchlist_generic_lot_search_terms(targets: list[WatchCard]) -> list[str]:
    """Return user-entered active generic-lot searches."""

    return _unique_terms(
        [
            search.term
            for target in targets
            for search in target.active_searches
            if search.mode == "generic_lot"
        ]
    )


def watchlist_lot_search_terms(targets: list[WatchCard]) -> list[str]:
    return _unique_terms(
        [
            *watchlist_era_lot_search_terms(targets),
            *watchlist_generic_lot_search_terms(targets),
        ]
    )


def watchlist_signature(targets: list[WatchCard]) -> str:
    """Hash all active rules and searches so edits permit a fresh rescan."""

    serialized = json.dumps(
        [asdict(target) for target in sorted(targets, key=lambda item: item.id)],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
