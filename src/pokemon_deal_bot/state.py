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
    def fingerprint(listing: SendicoListing, scan_signature: str = "") -> str:
        payload = "|".join(
            [
                listing.code,
                str(listing.price_yen),
                listing.title,
                str(listing.seller_positive_ratings),
                "|".join(listing.image_urls),
                scan_signature,
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def _is_retryable_outcome(outcome: str) -> bool:
        return outcome.startswith("error:") or outcome == "seller rating unverified"

    def attempt_count(
        self,
        listing: SendicoListing,
        scan_signature: str = "",
    ) -> int:
        record = self.data.get(listing.code, {})
        if record.get("fingerprint") != self.fingerprint(listing, scan_signature):
            return 0
        # Existing state files created before the retry update have no
        # attempt_count. Treat their stored check as attempt 1.
        return max(1, int(record.get("attempt_count", 1)))

    def unchanged(
        self,
        listing: SendicoListing,
        max_attempts: int = 3,
        scan_signature: str = "",
    ) -> bool:
        record = self.data.get(listing.code, {})
        if record.get("fingerprint") != self.fingerprint(listing, scan_signature):
            return False

        outcome = str(record.get("last_outcome", ""))
        if not self._is_retryable_outcome(outcome):
            return True

        attempts = self.attempt_count(listing, scan_signature)
        return attempts >= max(1, max_attempts)

    def was_alerted(
        self,
        listing: SendicoListing,
        scan_signature: str = "",
    ) -> bool:
        record = self.data.get(listing.code, {})
        return record.get("alerted_fingerprint") == self.fingerprint(
            listing,
            scan_signature,
        )

    def update(
        self,
        listing: SendicoListing,
        alerted: bool,
        outcome: str,
        scan_signature: str = "",
    ) -> None:
        previous = self.data.get(listing.code, {})
        fingerprint = self.fingerprint(listing, scan_signature)

        if previous.get("fingerprint") == fingerprint:
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
            "scan_signature": scan_signature,
            "last_checked": datetime.now(timezone.utc).isoformat(),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
