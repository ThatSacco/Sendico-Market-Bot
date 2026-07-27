from pokemon_deal_bot.models import IdentifiedCard
from pokemon_deal_bot.pricecharting import strict_identity_match


def _card(number: str, set_name: str, set_code: str) -> IdentifiedCard:
    return IdentifiedCard(
        name_en="Victini",
        name_jp="ビクティニ",
        set_name=set_name,
        set_code=set_code,
        card_number=number,
        rarity="R",
        language="Japanese",
        quantity=1,
        confidence=0.98,
    )


def test_strict_match_requires_exact_number_and_set():
    card = _card("011/054", "Sky Legend", "SM10b")
    assert strict_identity_match(
        card,
        "Victini #11 Prices | Pokemon Japanese Sky Legend "
        "https://www.pricecharting.com/game/pokemon-japanese-sky-legend/victini-11",
    )


def test_strict_match_rejects_same_name_wrong_number():
    card = _card("011/054", "Sky Legend", "SM10b")
    assert not strict_identity_match(
        card,
        "Victini #7 Prices | Pokemon Japanese Sky Legend "
        "https://www.pricecharting.com/game/pokemon-japanese-sky-legend/victini-7",
    )


def test_strict_match_rejects_same_number_wrong_set():
    card = _card("011/054", "Sky Legend", "SM10b")
    assert not strict_identity_match(
        card,
        "Victini #11 Prices | Pokemon Japanese Tag All Stars "
        "https://www.pricecharting.com/game/pokemon-japanese-tag-all-stars/victini-11",
    )
