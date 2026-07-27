import io

import pytest
from PIL import Image, ImageDraw

from pokemon_deal_bot.image_processing import (
    CardCrop,
    DownloadedImage,
    LocalCardExtractor,
)
from pokemon_deal_bot.models import IdentifiedCard, SendicoListing, WatchCard
from pokemon_deal_bot.vision import (
    LotVisionAnalyzer,
    VisionRateLimitError,
    VisionRequestTooLargeError,
    _merge_cards,
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


def _single_card_jpeg(width: int = 500, height: int = 700) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, width - 10, height - 10), outline="black", width=10)
    draw.rectangle((45, 70, width - 45, height // 2), fill="steelblue")
    draw.rectangle((45, height // 2 + 30, width - 45, height - 90), outline="black", width=4)
    draw.text((55, height - 65), "097/086", fill="black")
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


def _four_card_grid_jpeg() -> bytes:
    image = Image.new("RGB", (1200, 900), (80, 80, 80))
    draw = ImageDraw.Draw(image)
    for index, (x, y) in enumerate(((80, 80), (360, 80), (640, 80), (920, 80))):
        draw.rounded_rectangle(
            (x, y, x + 200, y + 280),
            radius=8,
            fill=(245, 245, 240),
            outline=(10, 10, 10),
            width=8,
        )
        draw.rectangle(
            (x + 18, y + 30, x + 182, y + 150),
            fill=(80 + index * 30, 120, 180),
            outline=(20, 20, 20),
            width=3,
        )
        draw.rectangle(
            (x + 20, y + 180, x + 180, y + 245),
            outline=(30, 30, 30),
            width=3,
        )
        draw.text((x + 25, y + 255), f"{index + 1}/100", fill="black")
    output = io.BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


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


def test_variant_defaults_to_normal_holo():
    result = parse_vision_result(
        {
            "listing_type": "single",
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
        },
        _target(),
    )
    assert result.cards[0].variant == "normal_holo"


def test_explicit_master_ball_variant_is_retained():
    result = parse_vision_result(
        {
            "listing_type": "single",
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
        },
        _target(),
    )
    assert result.cards[0].variant == "master_ball"


def test_physical_duplicate_cards_are_combined_after_identification():
    first = _card("097/086", 0.95)
    second = _card("097/086", 0.97)
    merged = _merge_cards([first, second])
    assert len(merged) == 1
    assert merged[0].quantity == 2
    assert merged[0].confidence == 0.97


def test_local_extractor_detects_four_card_grid():
    extractor = LocalCardExtractor(minimum_card_area_ratio=0.01)
    crops = extractor.extract(
        [DownloadedImage(1, "", "image/jpeg", _four_card_grid_jpeg())]
    )
    assert len(crops) == 4
    assert [crop.crop_index for crop in crops] == [1, 2, 3, 4]


def test_local_extractor_detects_single_card_closeup():
    extractor = LocalCardExtractor()
    crops = extractor.extract(
        [DownloadedImage(1, "", "image/jpeg", _single_card_jpeg())]
    )
    assert len(crops) == 1
    assert crops[0].data.startswith(b"\xff\xd8")


def test_alternate_photo_is_removed_but_same_image_count_is_preserved():
    data = _single_card_jpeg()
    extractor = LocalCardExtractor(duplicate_phash_distance=10)
    alternate_views = extractor.extract(
        [
            DownloadedImage(1, "", "image/jpeg", data),
            DownloadedImage(2, "", "image/jpeg", data),
        ]
    )
    assert len(alternate_views) == 1

    same_photo = extractor.extract(
        [DownloadedImage(1, "", "image/jpeg", _four_card_grid_jpeg())]
    )
    assert len(same_photo) == 4


def test_contact_sheet_is_one_small_jpeg():
    analyzer = LotVisionAnalyzer(
        api_key="test",
        model="qwen/qwen3.6-27b",
        max_images=12,
        request_spacing_seconds=0,
    )
    crops = [
        CardCrop(index, 1, "image/jpeg", _single_card_jpeg())
        for index in range(1, 5)
    ]
    sheet = analyzer._make_contact_sheet(crops)
    assert sheet.startswith(b"\xff\xd8")
    with Image.open(io.BytesIO(sheet)) as image:
        assert max(image.size) <= 1100


def test_only_one_identity_is_kept_per_crop():
    analyzer = LotVisionAnalyzer(
        api_key="test",
        model="test",
        max_images=1,
        request_spacing_seconds=0,
    )
    crops = [
        CardCrop(1, 1, "image/jpeg", _single_card_jpeg()),
        CardCrop(2, 1, "image/jpeg", _single_card_jpeg()),
    ]
    result = analyzer._parse_batch_result(
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
    assert result.unidentified_count == 1


def test_groq_request_uses_one_image_bearer_auth_and_json_mode(monkeypatch):
    analyzer = LotVisionAnalyzer(
        api_key="secret-key",
        model="qwen/qwen3.6-27b",
        max_images=3,
        request_spacing_seconds=0,
    )
    captured = {}

    class FakeResponse:
        status_code = 200
        is_error = False
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": '{"cards":[]}'}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr("pokemon_deal_bot.vision.httpx.post", fake_post)
    result = analyzer._generate(
        [
            {"text": "Return JSON"},
            analyzer._inline_part("image/jpeg", _single_card_jpeg()),
        ]
    )
    assert result["cards"] == []
    assert captured["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"
    assert captured["json"]["model"] == "qwen/qwen3.6-27b"
    assert captured["json"]["response_format"] == {"type": "json_object"}
    image_parts = [
        part
        for part in captured["json"]["messages"][0]["content"]
        if part["type"] == "image_url"
    ]
    assert len(image_parts) == 1


def test_listing_description_is_not_sent_to_groq(monkeypatch):
    analyzer = LotVisionAnalyzer(
        api_key="test",
        model="test",
        max_images=1,
        request_spacing_seconds=0,
    )
    captured = {}

    def fake_generate(parts):
        captured["parts"] = parts
        return {"cards": [], "unrecognized_crop_indexes": [1]}

    monkeypatch.setattr(analyzer, "_generate", fake_generate)
    listing = SendicoListing(
        code="m1",
        url="https://example.test/m1",
        title="Victini lot",
        price_yen=1000,
        description="DO_NOT_SEND_" * 1000,
    )
    analyzer._request_batch(
        listing,
        _target(),
        [CardCrop(1, 1, "image/jpeg", _single_card_jpeg())],
        compact=False,
    )
    prompt = captured["parts"][0]["text"]
    assert "Victini lot" in prompt
    assert "DO_NOT_SEND" not in prompt


def test_http_413_token_request_is_detected_as_too_large(monkeypatch):
    analyzer = LotVisionAnalyzer(
        api_key="secret-key",
        model="qwen/qwen3.6-27b",
        max_images=3,
        request_spacing_seconds=0,
    )

    class FakeResponse:
        status_code = 413
        is_error = True
        text = "request too large"

        @staticmethod
        def json():
            return {
                "error": {
                    "message": "Request too large: Requested 17614 tokens per minute",
                    "code": "rate_limit_exceeded",
                }
            }

    monkeypatch.setattr(
        "pokemon_deal_bot.vision.httpx.post",
        lambda *args, **kwargs: FakeResponse(),
    )
    with pytest.raises(VisionRequestTooLargeError):
        analyzer._generate(
            [
                {"text": "Return JSON"},
                analyzer._inline_part("image/jpeg", _single_card_jpeg()),
            ]
        )


def test_http_429_raises_rate_limit_error(monkeypatch):
    analyzer = LotVisionAnalyzer(
        api_key="secret-key",
        model="qwen/qwen3.6-27b",
        max_images=3,
        request_spacing_seconds=0,
    )

    class FakeResponse:
        status_code = 429
        is_error = True
        text = "rate limit reached"

        @staticmethod
        def json():
            return {"error": {"message": "rate limit reached", "code": "rate_limit_exceeded"}}

    monkeypatch.setattr(
        "pokemon_deal_bot.vision.httpx.post",
        lambda *args, **kwargs: FakeResponse(),
    )
    with pytest.raises(VisionRateLimitError):
        analyzer._generate(
            [
                {"text": "Return JSON"},
                analyzer._inline_part("image/jpeg", _single_card_jpeg()),
            ]
        )


def test_oversized_batch_is_split_automatically(monkeypatch):
    analyzer = LotVisionAnalyzer(
        api_key="test",
        model="test",
        max_images=3,
        crop_batch_size=4,
        request_spacing_seconds=0,
    )
    calls = []

    def fake_request(listing, target, crops, *, compact):
        calls.append((len(crops), compact))
        if len(crops) > 1:
            raise VisionRequestTooLargeError("too large")
        return {
            "cards": [],
            "unrecognized_crop_indexes": [crops[0].crop_index],
        }

    monkeypatch.setattr(analyzer, "_request_batch", fake_request)
    crops = [
        CardCrop(index, 1, "image/jpeg", _single_card_jpeg())
        for index in range(1, 5)
    ]
    results, successful_requests = analyzer._identify_with_size_fallback(
        SendicoListing("m1", "https://example.test", "lot", 1000),
        _target(),
        crops,
    )
    assert successful_requests == 4
    assert len(results) == 4
    assert calls[0] == (4, False)
    assert all(size == 1 for size, _ in calls if size == 1)
