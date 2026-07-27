from pokemon_deal_bot.models import IdentifiedCard, WatchCard
from pokemon_deal_bot.vision import (
    CropRegion,
    _merge_cards,
    dedupe_crop_regions,
    parse_crop_regions,
    parse_vision_result,
)


def _target() -> WatchCard:
    return WatchCard(
        id="v",
        active=True,
        japanese_name="ビクティニ",
        english_name="Victini",
        set_name="Pokemon Japanese Black Bolt",
        set_code="sv11B",
        card_number="097/086",
        rarity="AR",
    )


def test_parse_vision_target():
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
        _target(),
    )
    assert result.cards[0].is_target
    assert result.cards[0].quantity == 2


def test_parse_and_dedupe_regions():
    regions = parse_crop_regions(
        {
            "crop_regions": [
                {
                    "image_index": 1,
                    "box_2d": [100, 100, 400, 300],
                    "confidence": 0.95,
                },
                {
                    "image_index": 1,
                    "box_2d": [105, 105, 395, 295],
                    "confidence": 0.80,
                },
                {
                    "image_index": 1,
                    "box_2d": [450, 100, 800, 300],
                    "confidence": 0.90,
                },
            ]
        },
        minimum_confidence=0.5,
    )
    assert len(regions) == 2
    assert regions[0].box_2d == (100, 100, 400, 300)


def test_regions_on_different_images_are_not_duplicates():
    regions = dedupe_crop_regions(
        [
            CropRegion(1, (100, 100, 400, 300), 0.9),
            CropRegion(2, (100, 100, 400, 300), 0.9),
        ]
    )
    assert len(regions) == 2


def test_crop_cards_are_summed_and_override_overview_quantity():
    overview = IdentifiedCard(
        name_en="Victini",
        name_jp="ビクティニ",
        set_name="Black Bolt",
        set_code="sv11B",
        card_number="097/086",
        rarity="AR",
        language="Japanese",
        quantity=1,
        confidence=0.8,
        is_target=True,
    )
    crop_one = IdentifiedCard(
        name_en="Victini",
        name_jp="ビクティニ",
        set_name="Black Bolt",
        set_code="sv11B",
        card_number="097/086",
        rarity="AR",
        language="Japanese",
        quantity=1,
        confidence=0.95,
        is_target=True,
    )
    crop_two = IdentifiedCard(
        name_en="Victini",
        name_jp="ビクティニ",
        set_name="Black Bolt",
        set_code="sv11B",
        card_number="097/086",
        rarity="AR",
        language="Japanese",
        quantity=1,
        confidence=0.96,
        is_target=True,
    )
    merged = _merge_cards([overview], [crop_one, crop_two])
    assert len(merged) == 1
    assert merged[0].quantity == 2
    assert merged[0].confidence == 0.96
