from pokemon_deal_bot.sendico import is_listing_image_url, parse_seller_positive_ratings, parse_yen


def test_listing_images_exclude_recommendations():
    assert is_listing_image_url("https://static.mercdn.net/thumb/item/jpeg/m50777952153_1.jpg?1", "m50777952153")
    assert not is_listing_image_url("https://static.mercdn.net/thumb/item/jpeg/m11111111111_1.jpg?1", "m50777952153")


def test_parsers():
    assert parse_yen("¥2,860") == 2860
    assert parse_seller_positive_ratings("Positive ratings 431") == 431
