from __future__ import annotations

from datetime import date

from .fx import FxRates
from .models import CardPrice, DealAssessment, SendicoListing, VisionResult


def sendico_fee_jpy(config: dict, today: date | None = None) -> int:
    today = today or date.today()
    if today >= date(2026, 8, 1):
        return int(config["from_2026_08_01_jpy"])
    return int(config["before_2026_08_01_jpy"])


def assess_deal(
    listing: SendicoListing,
    vision: VisionResult,
    priced_cards: list[CardPrice],
    fx: FxRates,
    fee_config: dict,
    minimum_saving_percent: float,
    minimum_seller_ratings: int,
    minimum_target_confidence: float,
) -> DealAssessment:
    reasons: list[str] = []
    fee_jpy = sendico_fee_jpy(fee_config)
    listing_price_aud = listing.price_yen * fx.jpy_to_aud
    fee_aud = fee_jpy * fx.jpy_to_aud
    acquisition = listing_price_aud + fee_aud
    value = sum(item.total_aud for item in priced_cards)
    saving = value - acquisition
    saving_percent = (saving / value * 100.0) if value > 0 else -100.0

    if listing.seller_positive_ratings is None:
        reasons.append("seller positive rating could not be verified")
    elif listing.seller_positive_ratings < minimum_seller_ratings:
        reasons.append(
            f"seller has {listing.seller_positive_ratings} positive ratings; minimum is {minimum_seller_ratings}"
        )
    if not vision.target_present:
        reasons.append("target card was not confirmed")
    if vision.target_confidence < minimum_target_confidence:
        reasons.append("target-card confidence is below threshold")
    if not any(item.card.is_target for item in priced_cards):
        reasons.append("target card could not be priced")
    if value <= 0:
        reasons.append("no cards were priced")
    if saving_percent < minimum_saving_percent:
        reasons.append(
            f"saving is {saving_percent:.1f}%; minimum is {minimum_saving_percent:.1f}%"
        )

    return DealAssessment(
        listing=listing,
        vision=vision,
        priced_cards=priced_cards,
        acquisition_cost_aud=acquisition,
        listing_price_aud=listing_price_aud,
        sendico_fee_aud=fee_aud,
        total_identified_value_aud=value,
        saving_aud=saving,
        saving_percent=saving_percent,
        qualifies=not reasons,
        rejection_reasons=reasons,
    )
