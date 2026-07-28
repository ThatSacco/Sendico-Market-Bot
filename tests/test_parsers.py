from pathlib import Path

from pokemon_deal_bot.pricecharting import parse_ungraded_usd
from pokemon_deal_bot.sendico import parse_seller_positive_ratings, parse_yen


def test_parse_ungraded_price():
    html = Path("tests/fixtures/pricecharting_victini.html").read_text(encoding="utf-8")
    assert parse_ungraded_usd(html) == 17.84


def test_parse_yen():
    assert parse_yen("12,800 (A$131.22) Pokemon cards") == 12800
    assert parse_yen("Price ¥9,500") == 9500


def test_parse_seller_ratings():
    assert parse_seller_positive_ratings("Seller Positive ratings 1,428 Negative 2") == 1428
    assert parse_seller_positive_ratings("高評価 560") == 560
