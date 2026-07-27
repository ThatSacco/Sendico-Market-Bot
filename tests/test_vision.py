from pokemon_deal_bot.models import WatchCard
from pokemon_deal_bot.vision import parse_vision_result


def test_parse_vision_target():
    target = WatchCard(
        id="v",
        active=True,
        japanese_name="ビクティニ",
        english_name="Victini",
        set_name="Pokemon Japanese Black Bolt",
        set_code="sv11B",
        card_number="097/086",
        rarity="AR",
    )
    result = parse_vision_result(
        {
            "listing_type": "lot",
            "target_present": True,
            "target_confidence": 0.98,
            "cards": [
                {
                    "name_en": "Victini",
                    "name_jp": "ビクティニ",
                    "set_name": "Pokemon Japanese Black Bolt",
                    "set_code": "sv11B",
                    "card_number": "097/086",
                    "rarity": "AR",
                    "language": "Japanese",
                    "quantity": 2,
                    "confidence": 0.97,
                }
            ],
            "unidentified_card_count": 3,
        },
        target,
    )
    assert result.cards[0].is_target
    assert result.cards[0].quantity == 2
