from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse


SEARCH_MODES = {"exact", "focused_lot", "generic_lot"}


@dataclass(slots=True)
class WatchSearch:
    """One user-approved Sendico query stored in data/watchlist.yaml."""

    term: str
    mode: str = "focused_lot"
    active: bool = True

    def __post_init__(self) -> None:
        self.term = str(self.term or "").strip()
        self.mode = str(self.mode or "focused_lot").strip().lower()
        self.active = bool(self.active)
        if not self.term:
            raise ValueError("Watchlist searches require a non-empty term")
        if self.mode not in SEARCH_MODES:
            raise ValueError(
                f"Unsupported watchlist search mode {self.mode!r}; use exact, "
                "focused_lot or generic_lot"
            )


@dataclass(slots=True)
class WatchCard:
    """One active watchlist rule and its explicitly approved searches.

    ``searches`` is the single source of truth. The four legacy term fields are
    retained only so older tests/checkouts can still construct WatchCard objects;
    when ``searches`` is present they are derived from it.
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
    searches: list[WatchSearch | dict[str, Any]] = field(default_factory=list)
    # Backwards-compatible constructor fields. Do not use these in watchlist.yaml.
    search_terms: list[str] = field(default_factory=list)
    lot_search_terms: list[str] = field(default_factory=list)
    era_lot_search_terms: list[str] = field(default_factory=list)
    generic_lot_search_terms: list[str] = field(default_factory=list)
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
        self.lot_search_terms = _clean_list(self.lot_search_terms)
        self.era_lot_search_terms = _clean_list(self.era_lot_search_terms)
        self.generic_lot_search_terms = _clean_list(self.generic_lot_search_terms)

        parsed_searches: list[WatchSearch] = []
        for item in self.searches or []:
            if isinstance(item, WatchSearch):
                parsed_searches.append(item)
            elif isinstance(item, dict):
                parsed_searches.append(WatchSearch(**item))
            else:
                raise ValueError(
                    f"Watchlist entry {self.id!r} searches must contain mappings"
                )

        # Migrate legacy in-memory objects into the unified representation. This
        # is compatibility only; repository YAML is validated to reject old keys.
        if not parsed_searches:
            parsed_searches.extend(
                WatchSearch(term=term, mode="exact") for term in self.search_terms
            )
            parsed_searches.extend(
                WatchSearch(term=term, mode="focused_lot")
                for term in [*self.era_lot_search_terms, *self.lot_search_terms]
            )
            parsed_searches.extend(
                WatchSearch(term=term, mode="generic_lot")
                for term in self.generic_lot_search_terms
            )
        self.searches = _dedupe_searches(parsed_searches)
        self._sync_legacy_search_fields()

        self.pricecharting_url = _clean_pricecharting_url(
            self.pricecharting_url,
            entry_id=self.id,
            match_mode=self.match_mode,
        )
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

    def _sync_legacy_search_fields(self) -> None:
        active = [search for search in self.searches if search.active]
        self.search_terms = [s.term for s in active if s.mode == "exact"]
        self.era_lot_search_terms = [
            s.term for s in active if s.mode == "focused_lot"
        ]
        self.generic_lot_search_terms = [
            s.term for s in active if s.mode == "generic_lot"
        ]
        self.lot_search_terms = [
            *self.era_lot_search_terms,
            *self.generic_lot_search_terms,
        ]

    @property
    def active_searches(self) -> list[WatchSearch]:
        return [search for search in self.searches if search.active]

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
    return list(
        dict.fromkeys(
            str(value).strip() for value in (values or []) if str(value).strip()
        )
    )


def _dedupe_searches(values: list[WatchSearch]) -> list[WatchSearch]:
    seen: set[tuple[str, str]] = set()
    result: list[WatchSearch] = []
    for search in values:
        key = (search.mode, search.term.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(search)
    return result


def normalize_card_number(value: str | None) -> str:
    """Normalise 27/81 and 027/081 to the same identity."""

    compact = re.sub(r"\s+", "", str(value or "")).casefold()
    match = re.fullmatch(r"0*(\d+)\s*/\s*0*(\d+)", compact)
    if match:
        return f"{int(match.group(1))}/{int(match.group(2))}"
    return compact


def _clean_pricecharting_url(
    value: str | None,
    *,
    entry_id: str,
    match_mode: str,
) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None
    if match_mode != "exact_card":
        raise ValueError(
            f"Watchlist entry {entry_id!r} may use pricecharting_url only with "
            "match_mode 'exact_card'"
        )
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or hostname not in {
        "pricecharting.com",
        "www.pricecharting.com",
    }:
        raise ValueError(
            f"Watchlist entry {entry_id!r} has an invalid pricecharting_url; "
            "use an HTTPS PriceCharting product-page URL"
        )
    if not parsed.path.startswith("/game/"):
        raise ValueError(
            f"Watchlist entry {entry_id!r} pricecharting_url must point to a "
            "PriceCharting /game/ product page"
        )
    return url


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
    grading_company: str | None = None
    grade: str | None = None
    grading_confidence: float = 0.0
    grading_source: str | None = None
    is_target: bool = False
    matched_watchlist_ids: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return "|".join(
            [
                self.language.lower().strip(),
                (self.set_code or self.set_name or "").lower().strip(),
                normalize_card_number(self.card_number),
                self.name_en.lower().strip(),
                self.variant.lower().strip(),
                (self.grading_company or "raw").lower().strip(),
                (self.grade or "ungraded").lower().strip(),
            ]
        )

    @property
    def is_graded(self) -> bool:
        return bool((self.grading_company or "").strip() and (self.grade or "").strip())

    @property
    def grade_label(self) -> str:
        if not self.is_graded:
            return "Ungraded"
        return f"{self.grading_company} {self.grade}".strip()


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
    price_tier: str = "Ungraded"

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
