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

    @staticmethod
    def _is_retryable_outcome(outcome: str) -> bool:
        return outcome.startswith("error:") or outcome == "seller rating unverified"

    def attempt_count(self, listing: SendicoListing) -> int:
        record = self.data.get(listing.code, {})
        if record.get("fingerprint") != self.fingerprint(listing):
            return 0
        # Existing state files created before this update have no attempt_count.
        # Treat the stored check as attempt 1 so migration does not reset retries.
        return max(1, int(record.get("attempt_count", 1)))

    def unchanged(
        self,
        listing: SendicoListing,
        max_attempts: int = 3,
    ) -> bool:
        record = self.data.get(listing.code, {})
        if record.get("fingerprint") != self.fingerprint(listing):
            return False

        outcome = str(record.get("last_outcome", ""))
        if not self._is_retryable_outcome(outcome):
            # Successfully processed or permanently rejected unchanged listings
            # are skipped immediately, as before.
            return True

        attempts = self.attempt_count(listing)
        # False means process it again. True means it is unchanged and should be
        # skipped because all allowed attempts have already been used.
        return attempts >= max(1, max_attempts)

    def was_alerted(self, listing: SendicoListing) -> bool:
        record = self.data.get(listing.code, {})
        return record.get("alerted_fingerprint") == self.fingerprint(listing)

    def update(self, listing: SendicoListing, alerted: bool, outcome: str) -> None:
        previous = self.data.get(listing.code, {})
        fingerprint = self.fingerprint(listing)

        if previous.get("fingerprint") == fingerprint:
            # A legacy record without attempt_count already represents one prior
            # attempt, so the next attempt becomes number 2.
            attempt_count = max(1, int(previous.get("attempt_count", 1))) + 1
        else:
            attempt_count = 1

        alerted_fingerprint = (
            fingerprint if alerted else previous.get("alerted_fingerprint")
        )
        self.data[listing.code] = {
            "url": listing.url,
            "fingerprint": fingerprint,
            "alerted_fingerprint": alerted_fingerprint,
            "last_outcome": outcome,
            "attempt_count": attempt_count,
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }

    def save(self) -> None:
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
