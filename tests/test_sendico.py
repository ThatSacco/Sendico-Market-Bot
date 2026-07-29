from pokemon_deal_bot.sendico import (
    is_listing_image_url,
    listing_from_search_item,
    parse_seller_positive_ratings,
    parse_yen,
)


def test_listing_images_exclude_recommendations():
    assert is_listing_image_url(
        "https://static.mercdn.net/thumb/item/jpeg/m50777952153_1.jpg?1",
        "m50777952153",
    )
    assert not is_listing_image_url(
        "https://static.mercdn.net/thumb/item/jpeg/m11111111111_1.jpg?1",
        "m50777952153",
    )


def test_parsers():
    assert parse_yen("¥2,860") == 2860
    assert parse_seller_positive_ratings("Positive ratings 431") == 431


def test_search_item_without_price_is_retained_for_hydration():
    listing = listing_from_search_item(
        {
            "href": "https://sendico.com/shop/mercari/catalog/m50777952153",
            "text": "Victini Pokemon card lot",
            "title": "Victini lot",
            "image": (
                "https://static.mercdn.net/thumb/item/jpeg/"
                "m50777952153_1.jpg?1"
            ),
        }
    )

    assert listing is not None
    assert listing.code == "m50777952153"
    assert listing.price_yen == 0
    assert listing.title == "Victini lot"


def test_search_item_uses_result_price_when_available():
    listing = listing_from_search_item(
        {
            "href": "https://sendico.com/shop/mercari/catalog/m50777952153",
            "text": "Victini lot\n¥2,860",
            "title": "",
            "image": "",
        }
    )

    assert listing is not None
    assert listing.price_yen == 2860
    assert listing.title == "Victini lot"


def test_non_listing_catalog_links_are_rejected():
    assert (
        listing_from_search_item(
            {
                "href": (
                    "https://sendico.com/shop/mercari/catalog/categories/1289"
                ),
                "text": "Pokemon cards",
            }
        )
        is None
    )
