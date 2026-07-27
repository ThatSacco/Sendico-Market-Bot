from __future__ import annotations

import os
from dataclasses import dataclass
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
    def discord_webhook_url(self) -> str | None:
        return os.getenv("DISCORD_WEBHOOK_URL")

    @property
    def gemini_api_key(self) -> str | None:
        return os.getenv("GEMINI_API_KEY")

    def path(self, relative: str) -> Path:
        return self.root / relative


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    config_path = Path(path).resolve()
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    return AppConfig(raw=raw, root=config_path.parent)


def load_watchlist(config: AppConfig) -> list[WatchCard]:
    path = config.path("data/watchlist.yaml")
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    return [WatchCard(**item) for item in data.get("cards", []) if item.get("active", True)]
