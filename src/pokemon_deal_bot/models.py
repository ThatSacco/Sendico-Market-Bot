from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class WatchCard:
    """One active watchlist rule.

    ``exact_card`` matches a specific printed card number and Pokemon name.
    ``pokemon_general`` matches any identified card whose Pokemon name is in the
    configured aliases, with optional set restrictions.
    """

    id: str
    active: bool = True
    match_mode: str = "exact_card"
    japanese_name: str | None = None
    english_name: str | None = None
    japanese_names: list[str] = field(default_factory=list)
    english_names: list[str] = field(default_factory=list)
    set_name: str | None = None
    set_code: str | None = None
    card_number: str | None = None
    rarity: str | None = None
    language: str = "Japanese"
    accepted_sets: list[str] = field(default_factory=list)
    accepted_set_codes: list[str] = field(default_factory=list)
    search_terms: list[str] = field(default_factory=list)
    pricecharting_url: str | None = None

    def __post_init__(self) -> None:
        self.id = str(self.id).strip()
        self.match_mode = str(self.match_mode or "exact_card").strip().lower()
        if self.match_mode not in {"exact_card", "pokemon_general"}:
            raise ValueError(
                f"Watchlist entry {self.id!r} has unsupported match_mode "
                f"{self.match_mode!r}; use 'exact_card' or 'pokemon_general'"
            )
        if not self.id:
            raise ValueError("Every watchlist entry requires a non-empty id")

        self.japanese_names = _clean_list(self.japanese_names)
        self.english_names = _clean_list(self.english_names)
        self.accepted_sets = _clean_list(self.accepted_sets)
        self.accepted_set_codes = _clean_list(self.accepted_set_codes)
        self.search_terms = _clean_list(self.search_terms)

        if self.japanese_name and self.japanese_name.strip() not in self.japanese_names:
            self.japanese_names.insert(0, self.japanese_name.strip())
        if self.english_name and self.english_name.strip() not in self.english_names:
            self.english_names.insert(0, self.english_name.strip())

        if not self.japanese_names and not self.english_names:
            raise ValueError(
                f"Watchlist entry {self.id!r} requires at least one English or Japanese name"
            )
        if self.match_mode == "exact_card" and not str(self.card_number or "").strip():
            raise ValueError(
                f"Exact-card watchlist entry {self.id!r} requires card_number"
            )

    @property
    def display_name(self) -> str:
        base = (
            (self.english_names[0] if self.english_names else None)
            or (self.japanese_names[0] if self.japanese_names else None)
            or self.id
        )
        if self.match_mode == "exact_card" and self.card_number:
            return f"{base} {self.card_number}"
        return str(base)


def _clean_list(values: list[str] | None) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in (values or []) if str(value).strip()))


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
    matched_watchlist_ids: list[str] = field(default_factory=list)

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
    matched_watchlist_ids: list[str] = field(default_factory=list)


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
