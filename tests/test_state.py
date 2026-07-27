from pokemon_deal_bot.models import SendicoListing
from pokemon_deal_bot.state import StateStore


def test_old_unverified_rejection_is_reprocessed(tmp_path):
    path = tmp_path / "seen.json"
    listing = SendicoListing("m1", "https://example.test/m1", "title", 1000)
    store = StateStore(path)
    store.update(listing, False, "seller rating unverified")
    assert not store.unchanged(listing)


def test_alerted_provisional_result_is_not_repeated(tmp_path):
    path = tmp_path / "seen.json"
    listing = SendicoListing("m1", "https://example.test/m1", "title", 1000)
    store = StateStore(path)
    store.update(listing, True, "provisional deal; seller rating requires manual verification")
    assert store.unchanged(listing)
