from pokemon_deal_bot.models import IdentifiedCard
from pokemon_deal_bot.pricecharting import (
    identity_match_confidence,
    strict_identity_match,
)


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
    text = (
        "Victini #11 Prices | Pokemon Japanese Sky Legend "
        "https://www.pricecharting.com/game/pokemon-japanese-sky-legend/victini-11"
    )
    assert strict_identity_match(card, text)
    assert identity_match_confidence(card, text) == 1.0


def test_95_percent_match_accepts_exact_name_number_and_half_set_tokens():
    card = _card("011/054", "Sun Moon Sky Legend", "")
    text = (
        "Victini #11 Prices | Pokemon Japanese Sky Legend "
        "https://www.pricecharting.com/game/pokemon-japanese-sky-legend/victini-11"
    )
    assert identity_match_confidence(card, text) >= 0.95


def test_match_rejects_same_name_wrong_number():
    card = _card("011/054", "Sky Legend", "SM10b")
    assert identity_match_confidence(
        card,
        "Victini #7 Prices | Pokemon Japanese Sky Legend "
        "https://www.pricecharting.com/game/pokemon-japanese-sky-legend/victini-7",
    ) == 0.0


def test_match_rejects_same_number_wrong_set():
    card = _card("011/054", "Sky Legend", "SM10b")
    score = identity_match_confidence(
        card,
        "Victini #11 Prices | Pokemon Japanese Tag All Stars "
        "https://www.pricecharting.com/game/pokemon-japanese-tag-all-stars/victini-11",
    )
    assert score < 0.95


def test_normal_holo_rejects_master_ball_price():
    card = _card("012/086", "Black Bolt", "sv11B")
    card.variant = "normal_holo"
    text = (
        "Victini [Master Ball] #12 Prices | Pokemon Japanese Black Bolt "
        "https://www.pricecharting.com/game/pokemon-japanese-black-bolt/victini-master-ball-12"
    )
    assert identity_match_confidence(card, text) == 0.0


def test_normal_holo_accepts_regular_or_standard_holo_price():
    card = _card("012/086", "Black Bolt", "sv11B")
    card.variant = "normal_holo"
    text = (
        "Victini #12 Prices | Pokemon Japanese Black Bolt "
        "https://www.pricecharting.com/game/pokemon-japanese-black-bolt/victini-12"
    )
    assert identity_match_confidence(card, text) == 1.0


def test_master_ball_requires_master_ball_price():
    card = _card("012/086", "Black Bolt", "sv11B")
    card.variant = "master_ball"
    regular = (
        "Victini #12 Prices | Pokemon Japanese Black Bolt "
        "https://www.pricecharting.com/game/pokemon-japanese-black-bolt/victini-12"
    )
    premium = (
        "Victini [Master Ball] #12 Prices | Pokemon Japanese Black Bolt "
        "https://www.pricecharting.com/game/pokemon-japanese-black-bolt/victini-master-ball-12"
    )
    assert identity_match_confidence(card, regular) == 0.0
    assert identity_match_confidence(card, premium) == 1.0
