import json
from pathlib import Path

from pokemon_deal_bot.models import SendicoListing
from pokemon_deal_bot.state import StateStore


def _listing(price: int = 1000) -> SendicoListing:
    return SendicoListing(
        code="m-retry",
        url="https://example.test/m-retry",
        title="Victini listing",
        price_yen=price,
        seller_positive_ratings=None,
        image_urls=["https://example.test/card.jpg"],
    )


def test_retryable_error_is_allowed_three_total_attempts(tmp_path: Path):
    state = StateStore(tmp_path / "seen.json")
    listing = _listing()

    assert not state.unchanged(listing, max_attempts=3)

    state.update(listing, False, "error: first failure")
    assert state.attempt_count(listing) == 1
    assert not state.unchanged(listing, max_attempts=3)

    state.update(listing, False, "error: second failure")
    assert state.attempt_count(listing) == 2
    assert not state.unchanged(listing, max_attempts=3)

    state.update(listing, False, "error: third failure")
    assert state.attempt_count(listing) == 3
    assert state.unchanged(listing, max_attempts=3)


def test_changed_listing_resets_attempt_counter(tmp_path: Path):
    state = StateStore(tmp_path / "seen.json")
    original = _listing(price=1000)
    changed = _listing(price=1200)

    state.update(original, False, "error: first failure")
    state.update(original, False, "error: second failure")
    state.update(original, False, "error: third failure")
    assert state.unchanged(original, max_attempts=3)

    assert not state.unchanged(changed, max_attempts=3)
    state.update(changed, False, "error: changed listing failure")
    assert state.attempt_count(changed) == 1


def test_successful_unchanged_listing_is_skipped_immediately(tmp_path: Path):
    state = StateStore(tmp_path / "seen.json")
    listing = _listing()

    state.update(listing, True, "qualifies")

    assert state.unchanged(listing, max_attempts=3)
    assert state.was_alerted(listing)


def test_legacy_failure_record_counts_as_first_attempt(tmp_path: Path):
    path = tmp_path / "seen.json"
    listing = _listing()
    fingerprint = StateStore.fingerprint(listing)
    path.write_text(
        json.dumps(
            {
                listing.code: {
                    "url": listing.url,
                    "fingerprint": fingerprint,
                    "last_outcome": "error: old failure",
                }
            }
        ),
        encoding="utf-8",
    )

    state = StateStore(path)
    assert state.attempt_count(listing) == 1
    assert not state.unchanged(listing, max_attempts=3)

    state.update(listing, False, "error: new failure")
    assert state.attempt_count(listing) == 2
