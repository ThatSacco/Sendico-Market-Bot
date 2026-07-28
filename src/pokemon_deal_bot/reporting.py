from __future__ import annotations

import csv
import json
from pathlib import Path

from .models import DealAssessment


def write_reports(root: Path, assessments: list[DealAssessment]) -> None:
    report_dir = root / "reports"
    report_dir.mkdir(exist_ok=True)
    payload = [assessment.to_dict() for assessment in assessments]
    (report_dir / "latest.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    fields = [
        "qualifies",
        "provisional_qualifies",
        "title",
        "url",
        "price_yen",
        "seller_positive_ratings",
        "listing_type",
        "target_confidence",
        "identified_card_entries",
        "priced_card_entries",
        "unidentified_card_count",
        "listing_price_aud",
        "sendico_fee_aud",
        "acquisition_cost_aud",
        "pricecharting_lot_value_aud",
        "price_variance_aud",
        "price_variance_percent",
        "rejection_reasons",
    ]
    with (report_dir / "latest.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in assessments:
            writer.writerow(
                {
                    "qualifies": item.qualifies,
                    "provisional_qualifies": item.provisional_qualifies,
                    "title": item.listing.title,
                    "url": item.listing.url,
                    "price_yen": item.listing.price_yen,
                    "seller_positive_ratings": item.listing.seller_positive_ratings,
                    "listing_type": item.vision.listing_type,
                    "target_confidence": round(item.vision.target_confidence, 4),
                    "identified_card_entries": len(item.vision.cards),
                    "priced_card_entries": len(item.priced_cards),
                    "unidentified_card_count": item.vision.unidentified_card_count,
                    "listing_price_aud": round(item.listing_price_aud, 2),
                    "sendico_fee_aud": round(item.sendico_fee_aud, 2),
                    "acquisition_cost_aud": round(item.acquisition_cost_aud, 2),
                    "pricecharting_lot_value_aud": round(
                        item.total_identified_value_aud, 2
                    ),
                    "price_variance_aud": round(item.price_variance_aud, 2),
                    "price_variance_percent": round(
                        item.price_variance_percent, 2
                    ),
                    "rejection_reasons": "; ".join(item.rejection_reasons),
                }
            )
