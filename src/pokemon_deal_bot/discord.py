from __future__ import annotations

import logging

import httpx

from .models import DealAssessment, SendicoListing

LOGGER = logging.getLogger(__name__)


def money(value: float) -> str:
    return f"A${value:,.2f}"


def signed_money(value: float) -> str:
    sign = "+" if value > 0 else ("-" if value < 0 else "")
    return f"{sign}A${abs(value):,.2f}"


def _variance_wording(assessment: DealAssessment) -> str:
    if assessment.price_variance_aud > 0:
        return (
            f"{signed_money(assessment.price_variance_aud)} value above Sendico cost "
            f"({assessment.price_variance_percent:+.1f}%)"
        )
    if assessment.price_variance_aud < 0:
        return (
            f"{signed_money(assessment.price_variance_aud)} value below Sendico cost "
            f"({assessment.price_variance_percent:+.1f}%)"
        )
    return "No price variance (0.0%)"


def _target_name(assessment: DealAssessment) -> str:
    for priced in assessment.priced_cards:
        if priced.card.is_target:
            return f"{priced.card.name_en} {priced.card.card_number}"
    for card in assessment.vision.cards:
        if card.is_target:
            return f"{card.name_en} {card.card_number}"
    return "Target card"


def _priced_lines(assessment: DealAssessment, limit: int = 15) -> list[str]:
    lines: list[str] = []
    for priced in sorted(
        assessment.priced_cards,
        key=lambda item: item.total_aud,
        reverse=True,
    )[:limit]:
        card = priced.card
        lines.append(
            f"• {card.quantity}× **{card.name_en} {card.card_number}** — "
            f"{money(priced.total_aud)} "
            f"({priced.match_confidence:.0%} price match)"
        )
    if len(assessment.priced_cards) > limit:
        lines.append(
            f"• …and {len(assessment.priced_cards) - limit} more priced entries"
        )
    return lines


def build_embed(assessment: DealAssessment) -> dict:
    listing = assessment.listing
    vision = assessment.vision
    priced_lines = _priced_lines(assessment)
    unpriced_identified = max(0, len(vision.cards) - len(assessment.priced_cards))
    coverage = (
        f"{len(vision.cards)} cards identified at the configured confidence; "
        f"{len(assessment.priced_cards)} priced at ≥95% match confidence; "
        f"{unpriced_identified} identified cards unpriced; "
        f"{vision.unidentified_card_count} visible cards unidentified"
    )

    provisional = assessment.provisional_qualifies and not assessment.qualifies
    target = _target_name(assessment)
    variance = _variance_wording(assessment)

    if assessment.price_variance_aud > 0:
        color = 0x2ECC71
    elif assessment.price_variance_aud < 0:
        color = 0xE67E22
    else:
        color = 0x95A5A6

    if provisional:
        title = f"MANUAL SELLER CHECK — {target}"
        status = "Target found; seller rating must be verified manually"
        seller_value = "Unverified — confirm at least 301 positive ratings before buying"
        color = 0xF1C40F
    else:
        title = f"TARGET FOUND — {target}"
        status = "Target listing found — review price variance"
        seller_value = str(listing.seller_positive_ratings or "Unverified")

    return {
        "title": title,
        "url": listing.url,
        "description": listing.title[:4000],
        "color": color,
        "fields": [
            {"name": "Status", "value": status, "inline": False},
            {
                "name": "Mercari price",
                "value": f"¥{listing.price_yen:,} / {money(assessment.listing_price_aud)}",
                "inline": True,
            },
            {
                "name": "Sendico fee",
                "value": f"¥800 / {money(assessment.sendico_fee_aud)}",
                "inline": True,
            },
            {
                "name": "Total Sendico cost",
                "value": money(assessment.acquisition_cost_aud),
                "inline": True,
            },
            {
                "name": "PriceCharting lot value",
                "value": money(assessment.total_identified_value_aud),
                "inline": True,
            },
            {
                "name": "Price variance",
                "value": variance,
                "inline": True,
            },
            {"name": "Seller positives", "value": seller_value, "inline": True},
            {
                "name": "Lot value comparison",
                "value": (
                    f"PriceCharting value: **{money(assessment.total_identified_value_aud)}**\n"
                    f"Sendico cost: **{money(assessment.acquisition_cost_aud)}** "
                    f"(¥{listing.price_yen:,} listing + ¥800 fee)\n"
                    f"Variance: **{variance}**"
                ),
                "inline": False,
            },
            {
                "name": "Cards priced at ≥95% match",
                "value": "\n".join(priced_lines)[:1024] or "None",
                "inline": False,
            },
            {"name": "Coverage", "value": coverage[:1024], "inline": False},
            {
                "name": "Important",
                "value": (
                    "Verify the seller has at least 301 positive ratings before purchase. "
                    "Shipping, domestic freight, GST and condition adjustments are excluded. "
                    "Verify card identity, authenticity and condition."
                    if provisional
                    else "Shipping, domestic freight, GST and condition adjustments are "
                    "excluded. Verify card identity, authenticity and condition."
                ),
                "inline": False,
            },
        ],
        "thumbnail": {"url": listing.image_urls[0]} if listing.image_urls else None,
        "footer": {
            "text": f"Target confidence {vision.target_confidence:.0%} • "
            f"{vision.listing_type} • no minimum variance filter"
        },
    }


def _post_embed(webhook_url: str, username: str, embed: dict) -> None:
    if embed.get("thumbnail") is None:
        embed.pop("thumbnail", None)
    response = httpx.post(
        webhook_url,
        params={"wait": "true"},
        json={"username": username, "embeds": [embed]},
        timeout=30.0,
    )
    response.raise_for_status()


def send_discord(webhook_url: str, assessment: DealAssessment, username: str) -> None:
    _post_embed(webhook_url, username, build_embed(assessment))
    LOGGER.info("Discord alert sent for %s", assessment.listing.url)


def send_discord_test_start(
    webhook_url: str,
    username: str,
    model: str,
    listing_limit: int,
) -> None:
    embed = {
        "title": "TEST MODE STARTED",
        "description": (
            "GitHub Actions reached Discord successfully. The bot will now try to "
            "scan and analyse Sendico listings without seller, target-card or "
            "price-variance restrictions."
        ),
        "color": 0x5865F2,
        "fields": [
            {"name": "Gemini model", "value": model, "inline": True},
            {
                "name": "Maximum listing alerts",
                "value": str(listing_limit),
                "inline": True,
            },
        ],
        "footer": {"text": "Diagnostic mode — not a purchase recommendation"},
    }
    _post_embed(webhook_url, username, embed)
    LOGGER.info("Diagnostic startup message sent to Discord")


def build_test_embed(assessment: DealAssessment) -> dict:
    listing = assessment.listing
    vision = assessment.vision

    identified_lines: list[str] = []
    for card in vision.cards[:15]:
        identified_lines.append(
            f"• {card.quantity}× **{card.name_en} {card.card_number}** "
            f"({card.confidence:.0%})"
        )
    if len(vision.cards) > 15:
        identified_lines.append(
            f"• …and {len(vision.cards) - 15} more identified entries"
        )

    priced_lines = _priced_lines(assessment)
    seller_value = (
        str(listing.seller_positive_ratings)
        if listing.seller_positive_ratings is not None
        else "Unverified"
    )
    variance = _variance_wording(assessment)

    embed = {
        "title": "TEST MODE — Listing analysed",
        "url": listing.url,
        "description": listing.title[:4000],
        "color": 0x3498DB,
        "fields": [
            {
                "name": "Test status",
                "value": (
                    "Restrictions ignored. This confirms Sendico, Gemini, pricing "
                    "and Discord reached the result stage."
                ),
                "inline": False,
            },
            {
                "name": "Mercari price",
                "value": f"¥{listing.price_yen:,} / {money(assessment.listing_price_aud)}",
                "inline": True,
            },
            {"name": "Seller positives", "value": seller_value, "inline": True},
            {
                "name": "Listing images found",
                "value": str(len(listing.image_urls)),
                "inline": True,
            },
            {
                "name": "Gemini listing type",
                "value": vision.listing_type,
                "inline": True,
            },
            {
                "name": "Target detected",
                "value": (
                    f"{'Yes' if vision.target_present else 'No'} "
                    f"({vision.target_confidence:.0%})"
                ),
                "inline": True,
            },
            {
                "name": "Visible cards not identified",
                "value": str(vision.unidentified_card_count),
                "inline": True,
            },
            {
                "name": "Lot value and variance",
                "value": (
                    f"PriceCharting lot value: **"
                    f"{money(assessment.total_identified_value_aud)}**\n"
                    f"Sendico lot cost: **{money(assessment.acquisition_cost_aud)}** "
                    f"(¥{listing.price_yen:,} + ¥800 fee)\n"
                    f"Variance: **{variance}**"
                ),
                "inline": False,
            },
            {
                "name": "Cards identified by Gemini",
                "value": "\n".join(identified_lines)[:1024]
                or "No cards identified at the configured confidence",
                "inline": False,
            },
            {
                "name": "Cards matched to prices at ≥95%",
                "value": "\n".join(priced_lines)[:1024]
                or "No cards reached 95% pricing-match confidence",
                "inline": False,
            },
            {
                "name": "Vision notes",
                "value": "\n".join(vision.notes)[:1024] or "No notes",
                "inline": False,
            },
        ],
        "footer": {"text": "Diagnostic mode — not a purchase recommendation"},
    }

    if listing.image_urls:
        embed["thumbnail"] = {"url": listing.image_urls[0]}
    return embed


def send_discord_test(
    webhook_url: str,
    assessment: DealAssessment,
    username: str,
) -> None:
    _post_embed(webhook_url, username, build_test_embed(assessment))
    LOGGER.info("Diagnostic Discord result sent for %s", assessment.listing.url)


def send_discord_test_error(
    webhook_url: str,
    listing: SendicoListing,
    error: str,
    username: str,
) -> None:
    embed = {
        "title": "TEST MODE — Listing processing error",
        "url": listing.url,
        "description": listing.title[:4000],
        "color": 0xE74C3C,
        "fields": [
            {"name": "Error", "value": error[:1024], "inline": False},
            {
                "name": "What this means",
                "value": (
                    "Sendico found the listing, but a later stage failed. The error "
                    "above identifies the next component to fix."
                ),
                "inline": False,
            },
        ],
        "footer": {"text": "Diagnostic mode"},
    }

    if listing.image_urls:
        embed["thumbnail"] = {"url": listing.image_urls[0]}

    _post_embed(webhook_url, username, embed)
    LOGGER.info("Diagnostic Discord error sent for %s", listing.url)
