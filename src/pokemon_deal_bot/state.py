from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .models import SendicoListing


class StateStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self.data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.data = {}

    @staticmethod
    def fingerprint(listing: SendicoListing) -> str:
        payload = "|".join(
            [
                listing.code,
                str(listing.price_yen),
                listing.title,
                str(listing.seller_positive_ratings),
                "|".join(listing.image_urls),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def unchanged(self, listing: SendicoListing) -> bool:
        record = self.data.get(listing.code, {})
        if record.get("fingerprint") != self.fingerprint(listing):
            return False
        outcome = str(record.get("last_outcome", ""))
        alerted = record.get("alerted_fingerprint") == self.fingerprint(listing)
        # Retry transient failures, old rating-only rejections, and qualifying
        # results that could not yet be sent to Discord.
        if outcome.startswith("error:") or outcome == "seller rating unverified":
            return False
        if (outcome == "qualifies" or outcome.startswith("provisional deal")) and not alerted:
            return False
        return True

    def was_alerted(self, listing: SendicoListing) -> bool:
        record = self.data.get(listing.code, {})
        return record.get("alerted_fingerprint") == self.fingerprint(listing)

    def update(self, listing: SendicoListing, alerted: bool, outcome: str) -> None:
        previous = self.data.get(listing.code, {})
        fingerprint = self.fingerprint(listing)
        alerted_fingerprint = fingerprint if alerted else previous.get("alerted_fingerprint")
        self.data[listing.code] = {
            "url": listing.url,
            "fingerprint": fingerprint,
            "alerted_fingerprint": alerted_fingerprint,
            "last_outcome": outcome,
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }

    def save(self) -> None:
        self.path.write_text(json.dumps(self.data, indent=2, ensure_ascii=False), encoding="utf-8")
