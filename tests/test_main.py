from pokemon_deal_bot.main import _merge_listing
from pokemon_deal_bot.models import SendicoListing


def test_merge_listing_enriches_direct_placeholder():
    existing = SendicoListing(
        code="m10381389468",
        url="https://sendico.com/shop/mercari/catalog/m10381389468",
        title="Direct test listing",
        price_yen=0,
    )
    found = SendicoListing(
        code="m10381389468",
        url=existing.url,
        title="Pokemon cards Sun & Moon R rarity bundle sale",
        price_yen=700,
        image_urls=["https://example.test/lot.webp"],
        raw_text="search result text",
    )

    merged = _merge_listing(existing, found)

    assert merged is existing
    assert merged.title == found.title
    assert merged.price_yen == 700
    assert merged.image_urls == found.image_urls
    assert merged.raw_text == found.raw_text
