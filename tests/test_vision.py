from pokemon_deal_bot.models import IdentifiedCard, WatchCard
from pokemon_deal_bot.vision import (
    CardCrop,
    CropRegion,
    LotVisionAnalyzer,
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


def _card(number: str, confidence: float = 0.95) -> IdentifiedCard:
    return IdentifiedCard(
        name_en="Victini",
        name_jp="ビクティニ",
        set_name="Black Bolt",
        set_code="sv11B",
        card_number=number,
        rarity="AR",
        language="Japanese",
        quantity=1,
        confidence=confidence,
        is_target=number == "097/086",
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


def test_crop_results_replace_overview_identities():
    overview_wrong = _card("007/049", 0.99)
    crop_correct = _card("011/054", 0.96)
    merged = _merge_cards([overview_wrong], [crop_correct])
    assert len(merged) == 1
    assert merged[0].card_number == "011/054"


def test_duplicate_physical_crop_cards_are_combined():
    crop_one = _card("097/086", 0.95)
    crop_two = _card("097/086", 0.96)
    merged = _merge_cards([], [crop_one, crop_two])
    assert len(merged) == 1
    assert merged[0].quantity == 2
    assert merged[0].confidence == 0.96


def test_only_one_identity_is_kept_per_crop():
    analyzer = LotVisionAnalyzer(
        api_key="test",
        model="test",
        max_images=1,
    )
    crops = [
        CardCrop(1, 1, "image/jpeg", b"a"),
        CardCrop(2, 1, "image/jpeg", b"b"),
    ]
    result = analyzer._parse_crop_result(
        {
            "cards": [
                {
                    "crop_index": 1,
                    "name_en": "Victini",
                    "set_name": "Black Bolt",
                    "set_code": "sv11B",
                    "card_number": "007/049",
                    "language": "Japanese",
                    "confidence": 0.70,
                },
                {
                    "crop_index": 1,
                    "name_en": "Victini",
                    "set_name": "Sky Legend",
                    "set_code": "SM10b",
                    "card_number": "011/054",
                    "language": "Japanese",
                    "confidence": 0.98,
                },
            ],
            "unrecognized_crop_indexes": [2],
        },
        _target(),
        crops,
    )
    assert len(result.cards) == 1
    assert result.cards[0].card_number == "011/054"
    assert result.unidentified_card_count == 1


def test_variant_defaults_to_normal_holo():
    result = parse_vision_result(
        {
            "listing_type": "single",
            "target_present": False,
            "target_confidence": 0.0,
            "cards": [
                {
                    "name_en": "Victini",
                    "set_name": "Black Bolt",
                    "set_code": "sv11B",
                    "card_number": "012/086",
                    "language": "Japanese",
                    "confidence": 0.95,
                }
            ],
            "unidentified_card_count": 0,
        },
        _target(),
    )
    assert result.cards[0].variant == "normal_holo"


def test_explicit_master_ball_variant_is_retained():
    result = parse_vision_result(
        {
            "listing_type": "single",
            "target_present": False,
            "target_confidence": 0.0,
            "cards": [
                {
                    "name_en": "Victini",
                    "set_name": "Black Bolt",
                    "set_code": "sv11B",
                    "card_number": "012/086",
                    "language": "Japanese",
                    "confidence": 0.98,
                    "variant": "master_ball",
                }
            ],
            "unidentified_card_count": 0,
        },
        _target(),
    )
    assert result.cards[0].variant == "master_ball"
