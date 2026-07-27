from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class WatchCard:
    id: str
    active: bool
    japanese_name: str
    english_name: str
    set_name: str
    set_code: str
    card_number: str
    rarity: str
    language: str = "Japanese"
    pricecharting_url: str | None = None


@dataclass(slots=True)
class SendicoListing:
    code: str
    url: str
    title: str
    price_yen: int
    image_urls: list[str] = field(default_factory=list)
    description: str = ""
    seller_positive_ratings: int | None = None
    raw_text: str = ""


@dataclass(slots=True)
class IdentifiedCard:
    name_en: str
    name_jp: str | None
    set_name: str | None
    set_code: str | None
    card_number: str
    rarity: str | None
    language: str
    quantity: int
    confidence: float
    evidence_image_indexes: list[int] = field(default_factory=list)
    condition: str = "unknown"
    variant: str = "normal_holo"
    is_target: bool = False

    @property
    def key(self) -> str:
        return "|".join(
            [
                self.language.lower().strip(),
                (self.set_code or self.set_name or "").lower().strip(),
                self.card_number.lower().replace(" ", ""),
                self.name_en.lower().strip(),
                self.variant.lower().strip(),
            ]
        )


@dataclass(slots=True)
class VisionResult:
    listing_type: str
    target_present: bool
    target_confidence: float
    cards: list[IdentifiedCard]
    unidentified_card_count: int
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CardPrice:
    card: IdentifiedCard
    unit_price_usd: float
    unit_price_aud: float
    source_url: str
    source_title: str
    match_confidence: float

    @property
    def total_aud(self) -> float:
        return self.unit_price_aud * self.card.quantity


@dataclass(slots=True)
class DealAssessment:
    listing: SendicoListing
    vision: VisionResult
    priced_cards: list[CardPrice]
    acquisition_cost_aud: float
    listing_price_aud: float
    sendico_fee_aud: float
    total_identified_value_aud: float
    price_variance_aud: float
    price_variance_percent: float
    qualifies: bool
    rejection_reasons: list[str] = field(default_factory=list)

    @property
    def provisional_qualifies(self) -> bool:
        """True when only the unavailable seller rating blocks an alert."""
        if self.qualifies or not self.rejection_reasons:
            return False
        return all(
            reason == "seller positive rating could not be verified"
            for reason in self.rejection_reasons
        )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["provisional_qualifies"] = self.provisional_qualifies
        return payload
