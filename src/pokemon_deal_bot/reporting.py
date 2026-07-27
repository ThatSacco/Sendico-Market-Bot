from __future__ import annotations

import csv
import json
from dataclasses import asdict
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
        "title",
        "url",
        "price_yen",
        "seller_positive_ratings",
        "listing_type",
        "target_confidence",
        "priced_card_entries",
        "unidentified_card_count",
        "acquisition_cost_aud",
        "identified_value_aud",
        "saving_aud",
        "saving_percent",
        "rejection_reasons",
    ]
    with (report_dir / "latest.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for item in assessments:
            writer.writerow(
                {
                    "qualifies": item.qualifies,
                    "title": item.listing.title,
                    "url": item.listing.url,
                    "price_yen": item.listing.price_yen,
                    "seller_positive_ratings": item.listing.seller_positive_ratings,
                    "listing_type": item.vision.listing_type,
                    "target_confidence": round(item.vision.target_confidence, 4),
                    "priced_card_entries": len(item.priced_cards),
                    "unidentified_card_count": item.vision.unidentified_card_count,
                    "acquisition_cost_aud": round(item.acquisition_cost_aud, 2),
                    "identified_value_aud": round(item.total_identified_value_aud, 2),
                    "saving_aud": round(item.saving_aud, 2),
                    "saving_percent": round(item.saving_percent, 2),
                    "rejection_reasons": "; ".join(item.rejection_reasons),
                }
            )
