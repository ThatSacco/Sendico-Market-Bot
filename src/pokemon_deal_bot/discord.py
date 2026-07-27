from __future__ import annotations

import logging

import httpx

from .models import CardPrice, DealAssessment, SendicoListing, VisionResult

LOGGER = logging.getLogger(__name__)


def money(value: float) -> str:
    return f"A${value:,.2f}"


def build_embed(assessment: DealAssessment) -> dict:
    listing = assessment.listing
    vision = assessment.vision
    priced_lines = []
    for priced in sorted(
        assessment.priced_cards,
        key=lambda item: item.total_aud,
        reverse=True,
    )[:15]:
        card = priced.card
        priced_lines.append(
            f"• {card.quantity}× **{card.name_en} {card.card_number}** — "
            f"{money(priced.total_aud)}"
        )
    if len(assessment.priced_cards) > 15:
        priced_lines.append(
            f"• …and {len(assessment.priced_cards) - 15} more priced entries"
        )
    coverage = (
        f"{len(assessment.priced_cards)} priced card entries; "
        f"{vision.unidentified_card_count} visible cards unpriced"
    )

    provisional = assessment.provisional_qualifies and not assessment.qualifies
    if provisional:
        title = (
            "MANUAL SELLER CHECK — "
            f"{assessment.saving_percent:.1f}% below identified value"
        )
        color = 0xF1C40F
        status = "Provisional deal — seller rating must be verified manually"
        seller_value = "Unverified — confirm at least 301 positive ratings before buying"
    else:
        title = f"{assessment.saving_percent:.1f}% below identified value — Victini lot"
        color = 0x2ECC71
        status = "Qualified deal"
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
                "value": money(assessment.listing_price_aud),
                "inline": True,
            },
            {
                "name": "Sendico fee",
                "value": money(assessment.sendico_fee_aud),
                "inline": True,
            },
            {
                "name": "Cost used",
                "value": money(assessment.acquisition_cost_aud),
                "inline": True,
            },
            {
                "name": "Identified lot value",
                "value": money(assessment.total_identified_value_aud),
                "inline": True,
            },
            {
                "name": "Apparent saving",
                "value": money(assessment.saving_aud),
                "inline": True,
            },
            {"name": "Seller positives", "value": seller_value, "inline": True},
            {
                "name": "Cards valued",
                "value": "\n".join(priced_lines)[:1024] or "None",
                "inline": False,
            },
            {"name": "Coverage", "value": coverage, "inline": False},
            {
                "name": "Important",
                "value": (
                    "Verify the seller has at least 301 positive ratings before "
                    "purchase. Shipping, domestic freight, GST and condition "
                    "discounts are excluded. Verify card identity, authenticity "
                    "and condition."
                    if provisional
                    else "Shipping, domestic freight, GST and condition discounts "
                    "are excluded. Verify card identity and condition before purchase."
                ),
                "inline": False,
            },
        ],
        "thumbnail": {"url": listing.image_urls[0]} if listing.image_urls else None,
        "footer": {
            "text": f"Target confidence {vision.target_confidence:.0%} • "
            f"{vision.listing_type}"
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
            "saving restrictions."
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


def send_discord_test(
    webhook_url: str,
    listing: SendicoListing,
    vision: VisionResult,
    priced_cards: list[CardPrice],
    username: str,
) -> None:
    identified_lines = []
    for card in vision.cards[:15]:
        identified_lines.append(
            f"• {card.quantity}× **{card.name_en} {card.card_number}** "
            f"({card.confidence:.0%})"
        )
    if len(vision.cards) > 15:
        identified_lines.append(
            f"• …and {len(vision.cards) - 15} more identified entries"
        )

    priced_lines = []
    for priced in sorted(
        priced_cards,
        key=lambda item: item.total_aud,
        reverse=True,
    )[:15]:
        priced_lines.append(
            f"• {priced.card.quantity}× **{priced.card.name_en} "
            f"{priced.card.card_number}** — {money(priced.total_aud)}"
        )
    if len(priced_cards) > 15:
        priced_lines.append(f"• …and {len(priced_cards) - 15} more priced entries")

    seller_value = (
        str(listing.seller_positive_ratings)
        if listing.seller_positive_ratings is not None
        else "Unverified"
    )

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
                "value": f"¥{listing.price_yen:,}",
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
                "name": "Victini detected",
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
                "name": "Cards identified by Gemini",
                "value": "\n".join(identified_lines)[:1024]
                or "No exact cards identified",
                "inline": False,
            },
            {
                "name": "Cards matched to prices",
                "value": "\n".join(priced_lines)[:1024]
                or "No cards successfully priced",
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

    _post_embed(webhook_url, username, embed)
    LOGGER.info("Diagnostic Discord result sent for %s", listing.url)


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
