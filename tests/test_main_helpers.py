from pokemon_deal_bot.main import _candidate_targets
from pokemon_deal_bot.models import ReferenceCard, SendicoListing


def _reference(target_id: str) -> ReferenceCard:
    from pathlib import Path

    return ReferenceCard(
        target_id=target_id,
        source_url="https://www.pricecharting.com/game/x/y",
        product_id=target_id,
        name=target_id,
        set_name="",
        card_number="",
        image_url="https://example.test/image.jpg",
        image_path=Path("image.jpg"),
    )


def test_search_association_prioritises_but_does_not_filter_targets():
    listing = SendicoListing(
        code="m1",
        url="https://sendico.test/m1",
        title="lot",
        price_yen=1000,
        candidate_target_ids=["ampharos"],
    )
    references = {
        "victini": _reference("victini"),
        "ampharos": _reference("ampharos"),
    }
    assert _candidate_targets(
        listing,
        references,
        compare_all=True,
    ) == ["ampharos", "victini"]
    assert _candidate_targets(
        listing,
        references,
        compare_all=False,
    ) == ["ampharos"]
