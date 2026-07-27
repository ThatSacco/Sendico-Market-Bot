from __future__ import annotations

import logging

import httpx

from .models import DealAssessment

LOGGER = logging.getLogger(__name__)


def money(value: float) -> str:
    return f"A${value:,.2f}"


def build_embed(assessment: DealAssessment) -> dict:
    listing = assessment.listing
    vision = assessment.vision
    priced_lines = []
    for priced in sorted(assessment.priced_cards, key=lambda item: item.total_aud, reverse=True)[:15]:
        card = priced.card
        priced_lines.append(
            f"• {card.quantity}× **{card.name_en} {card.card_number}** — {money(priced.total_aud)}"
        )
    if len(assessment.priced_cards) > 15:
        priced_lines.append(f"• …and {len(assessment.priced_cards) - 15} more priced entries")
    coverage = (
        f"{len(assessment.priced_cards)} priced card entries; "
        f"{vision.unidentified_card_count} visible cards unpriced"
    )

    provisional = assessment.provisional_qualifies and not assessment.qualifies
    if provisional:
        title = f"MANUAL SELLER CHECK — {assessment.saving_percent:.1f}% below identified value"
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
            {"name": "Mercari price", "value": money(assessment.listing_price_aud), "inline": True},
            {"name": "Sendico fee", "value": money(assessment.sendico_fee_aud), "inline": True},
            {"name": "Cost used", "value": money(assessment.acquisition_cost_aud), "inline": True},
            {"name": "Identified lot value", "value": money(assessment.total_identified_value_aud), "inline": True},
            {"name": "Apparent saving", "value": money(assessment.saving_aud), "inline": True},
            {"name": "Seller positives", "value": seller_value, "inline": True},
            {"name": "Cards valued", "value": "\n".join(priced_lines)[:1024] or "None", "inline": False},
            {"name": "Coverage", "value": coverage, "inline": False},
            {
                "name": "Important",
                "value": (
                    "Verify the seller has at least 301 positive ratings before purchase. "
                    "Shipping, domestic freight, GST and condition discounts are excluded. "
                    "Verify card identity, authenticity and condition."
                    if provisional
                    else "Shipping, domestic freight, GST and condition discounts are excluded. Verify card identity and condition before purchase."
                ),
                "inline": False,
            },
        ],
        "thumbnail": {"url": listing.image_urls[0]} if listing.image_urls else None,
        "footer": {"text": f"Target confidence {vision.target_confidence:.0%} • {vision.listing_type}"},
    }


def send_discord(webhook_url: str, assessment: DealAssessment, username: str) -> None:
    embed = build_embed(assessment)
    if embed.get("thumbnail") is None:
        embed.pop("thumbnail", None)
    response = httpx.post(
        webhook_url,
        params={"wait": "true"},
        json={"username": username, "embeds": [embed]},
        timeout=30.0,
    )
    response.raise_for_status()
    LOGGER.info("Discord alert sent for %s", assessment.listing.url)
