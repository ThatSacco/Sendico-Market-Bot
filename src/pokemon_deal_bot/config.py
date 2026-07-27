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
    def groq_api_key(self) -> str | None:
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
        card_id for card_id in {card.id for card in cards}
        if sum(card.id == card_id for card in cards) > 1
    )
    if duplicate_ids:
        raise ValueError(
            "Active watchlist ids must be unique: " + ", ".join(duplicate_ids)
        )
    if not cards:
        raise ValueError("data/watchlist.yaml has no active watchlist entries")
    return cards


def watchlist_search_terms(targets: list[WatchCard]) -> list[str]:
    """Return unique marketplace terms generated entirely from the watchlist."""
    terms: list[str] = []
    for target in targets:
        if target.search_terms:
            terms.extend(target.search_terms)
            continue

        if target.match_mode == "exact_card":
            number = str(target.card_number or "").strip()
            for name in [*target.japanese_names, *target.english_names]:
                terms.append(" ".join(part for part in [name, number] if part))
        else:
            terms.extend(target.japanese_names)
            terms.extend(f"{name} Japanese" for name in target.english_names)

    return list(dict.fromkeys(term.strip() for term in terms if term.strip()))


def watchlist_signature(targets: list[WatchCard]) -> str:
    """Hash active rules so a watchlist edit permits old listings to be rescanned."""
    serialized = json.dumps(
        [asdict(target) for target in sorted(targets, key=lambda item: item.id)],
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
