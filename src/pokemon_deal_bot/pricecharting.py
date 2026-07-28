from __future__ import annotations

import csv
import json
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote_plus, urljoin

import httpx
from bs4 import BeautifulSoup

from .fx import FxRates
from .models import CardPrice, IdentifiedCard, WatchCard

LOGGER = logging.getLogger(__name__)
BASE_URL = "https://www.pricecharting.com"

GENERIC_SET_TOKENS = {
    "pokemon",
    "japanese",
    "card",
    "cards",
    "tcg",
    "set",
    "series",
    "the",
}

VARIANT_QUERY_TERMS = {
    "master_ball": "Master Ball",
    "poke_ball": "Poke Ball",
    "reverse_holo": "Reverse Holo",
}


def _normalize_variant(value: str | None) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", (value or "").lower()).strip("_")
    aliases = {
        "": "normal_holo",
        "normal": "normal_holo",
        "regular": "normal_holo",
        "holo": "normal_holo",
        "standard": "normal_holo",
        "masterball": "master_ball",
        "pokeball": "poke_ball",
        "reverse": "reverse_holo",
        "reverse_foil": "reverse_holo",
    }
    normalized = aliases.get(text, text)
    return normalized if normalized in {
        "normal_holo", "master_ball", "poke_ball", "reverse_holo", "other"
    } else "normal_holo"


def detected_variant(text: str) -> str:
    haystack = text.lower().replace("poké", "poke")
    if re.search(r"\bmaster[ -]?ball\b", haystack):
        return "master_ball"
    if re.search(r"\bpoke[ -]?ball\b|\bpokeball\b", haystack):
        return "poke_ball"
    if re.search(r"\breverse(?:[ -](?:holo|foil))?\b", haystack):
        return "reverse_holo"
    return "normal_holo"


def variant_matches(card: IdentifiedCard, text: str) -> bool:
    expected = _normalize_variant(card.variant)
    actual = detected_variant(text)
    if expected == "other":
        # An unspecified premium/other variant is not safe to price automatically.
        return False
    return expected == actual


def _word_tokens(value: str | None) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", (value or "").lower())
        if token and token not in GENERIC_SET_TOKENS
    ]


def normalize_number(value: str) -> str:
    return value.lower().replace("#", "").replace(" ", "").lstrip("0")


def _card_numerator(card_number: str) -> str:
    return normalize_number(card_number.split("/", 1)[0])


def _candidate_numbers(text: str) -> set[str]:
    values = {
        normalize_number(match)
        for match in re.findall(r"#\s*0*([0-9]{1,3})(?=\D|$)", text, re.IGNORECASE)
    }
    values.update(
        normalize_number(match)
        for match in re.findall(
            r"/[^?#\s]+-0*([0-9]{1,3})(?:[/?#]|$)", text, re.IGNORECASE
        )
    )
    return {value for value in values if value}


def _set_similarity(card: IdentifiedCard, text: str) -> float:
    """Return a conservative set similarity score from 0 to 1.

    An exact set-code match is strongest. Otherwise, at least half of the
    meaningful set-name tokens must occur before a result can reach the 95%
    acceptance threshold used by this project.
    """
    haystack = text.lower()
    compact = re.sub(r"[^a-z0-9]", "", haystack)
    set_code = re.sub(r"[^a-z0-9]", "", (card.set_code or "").lower())
    if set_code and set_code in compact:
        return 1.0

    tokens = _word_tokens(card.set_name)
    if not tokens:
        return 0.0
    overlap = sum(token in haystack for token in tokens) / len(tokens)
    if overlap >= 0.75:
        return 1.0
    if overlap >= 0.50:
        return 0.80
    if overlap >= 0.25:
        return 0.50
    return 0.0


def identity_match_confidence(card: IdentifiedCard, text: str) -> float:
    """Score a PriceCharting candidate using name, number, set and finish variant.

    Weighting:
      - exact English name tokens: 40%
      - exact printed card-number numerator: 35%
      - set code/name similarity: 25%

    A 95% result therefore requires an exact name and card number plus a strong
    set match. This is less brittle than a binary exact match while still
    rejecting similarly named cards from another number or unrelated set.
    """
    if not variant_matches(card, text):
        return 0.0

    haystack = text.lower()
    name_tokens = [
        token for token in re.findall(r"[a-z0-9]+", card.name_en.lower()) if token
    ]
    if not name_tokens or not all(token in haystack for token in name_tokens):
        return 0.0

    numbers = _candidate_numbers(text)
    if _card_numerator(card.card_number) not in numbers:
        return 0.0

    return 0.40 + 0.35 + (0.25 * _set_similarity(card, text))


def strict_identity_match(card: IdentifiedCard, text: str) -> bool:
    """Backward-compatible exact-match helper used by tests and callers."""
    return identity_match_confidence(card, text) >= 0.999


def _parse_price_text(value: str | None) -> float | None:
    if not value or value.strip() == "-":
        return None
    match = re.search(r"\$\s*([0-9][0-9,]*\.?[0-9]*)", value)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def parse_price_guide_usd(html: str) -> dict[str, float]:
    """Extract current PriceCharting guide values by condition/grade.

    PriceCharting exposes a comparison table headed Ungraded, Grade 7 through
    Grade 9.5, and PSA 10. The selectors are used first for the two most common
    tiers, followed by a generic table parser so minor markup changes do not
    silently force a graded slab back to the ungraded value.
    """
    soup = BeautifulSoup(html, "html.parser")
    prices: dict[str, float] = {}

    selectors = {
        "Ungraded": "#used_price .price",
        "PSA 10": "#manual_only_price .price",
    }
    for label, selector in selectors.items():
        element = soup.select_one(selector)
        price = _parse_price_text(element.get_text(" ", strip=True) if element else None)
        if price is not None:
            prices[label] = price

    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row_index, header_row in enumerate(rows[:-1]):
            headers = [
                cell.get_text(" ", strip=True)
                for cell in header_row.find_all(["th", "td"])
            ]
            if not headers or not any(
                label.lower() in " ".join(headers).lower()
                for label in ("Ungraded", "Grade 9", "PSA 10")
            ):
                continue
            values = [
                cell.get_text(" ", strip=True)
                for cell in rows[row_index + 1].find_all(["th", "td"])
            ]
            if len(values) < len(headers):
                continue
            for label, value in zip(headers, values):
                normalized = re.sub(r"\s+", " ", label).strip()
                if normalized in {
                    "Ungraded",
                    "Grade 7",
                    "Grade 8",
                    "Grade 9",
                    "Grade 9.5",
                    "PSA 10",
                }:
                    price = _parse_price_text(value)
                    if price is not None:
                        prices.setdefault(normalized, price)

    # Backward-compatible text fallbacks for pages/fixtures without the table.
    text_content = " ".join(soup.stripped_strings)
    if "Ungraded" not in prices:
        for pattern in (
            re.compile(
                r"Full Price Guide:.*?Ungraded\s*\$([0-9][0-9,]*\.?[0-9]*)",
                re.IGNORECASE,
            ),
            re.compile(
                r"Ungraded\s*\|?\s*\$([0-9][0-9,]*\.?[0-9]*)",
                re.IGNORECASE,
            ),
            re.compile(
                r"Loose Price.*?\$([0-9][0-9,]*\.?[0-9]*)",
                re.IGNORECASE,
            ),
        ):
            match = pattern.search(text_content)
            if match:
                prices["Ungraded"] = float(match.group(1).replace(",", ""))
                break

    return prices


def parse_ungraded_usd(html: str) -> float | None:
    return parse_price_guide_usd(html).get("Ungraded")


def price_tier_for_card(card: IdentifiedCard) -> str | None:
    """Map a detected slab grade to PriceCharting's published guide columns."""
    if not card.is_graded:
        return "Ungraded"

    company = (card.grading_company or "").upper().strip()
    try:
        grade_value = float(card.grade or "")
    except ValueError:
        return None

    if company == "PSA" and grade_value == 10.0:
        return "PSA 10"
    if grade_value in {7.0, 8.0, 9.0, 9.5}:
        return f"Grade {grade_value:g}"

    # PriceCharting's main guide does not provide a safe equivalent for every
    # grading company/grade combination. Do not substitute PSA 10 for another
    # company's 10 or silently fall back to raw pricing.
    return None


def page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    return (
        h1.get_text(" ", strip=True)
        if h1
        else (soup.title.get_text(" ", strip=True) if soup.title else "")
    )


class PriceChartingClient:
    def __init__(
        self,
        root: Path,
        fx: FxRates,
        request_delay_seconds: float,
        cache_hours: int,
        minimum_match_confidence: float = 0.95,
    ) -> None:
        self.root = root
        self.fx = fx
        self.request_delay_seconds = request_delay_seconds
        self.cache_hours = cache_hours
        self.minimum_match_confidence = minimum_match_confidence
        self.cache_path = root / "data/price_cache.json"
        self.overrides = self._load_overrides(root / "data/price_overrides.csv")
        self.cache = self._load_cache()
        self.client = httpx.Client(
            timeout=30.0,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "Chrome/130 Safari/537.36"
                )
            },
        )

    def close(self) -> None:
        self.client.close()
        self._save_cache()

    def price_card(
        self, card: IdentifiedCard, target: WatchCard | None = None
    ) -> CardPrice | None:
        price_tier = price_tier_for_card(card)
        override = self.overrides.get(card.key)
        if override is not None:
            return CardPrice(
                card=card,
                unit_price_usd=override / self.fx.usd_to_aud,
                unit_price_aud=override,
                source_url="manual override",
                source_title="Manual AUD override",
                match_confidence=1.0,
                price_tier=price_tier or card.grade_label,
            )

        if price_tier is None:
            LOGGER.warning(
                "No safe PriceCharting guide tier for graded card %s (%s); "
                "leaving it unpriced instead of using the raw value",
                card.key,
                card.grade_label,
            )
            return None

        direct_url = None
        if (
            target is not None
            and target.match_mode == "exact_card"
            and target.pricecharting_url
            and card.is_target
            and target.id in card.matched_watchlist_ids
        ):
            direct_url = target.pricecharting_url

        # A watchlist product URL is preferred, but it is never trusted blindly.
        # The fetched page title and URL must still match the identified card at
        # the normal confidence threshold. If the page is unavailable or does not
        # match, the standard PriceCharting search remains as a safe fallback.
        if direct_url:
            direct_data = self._fetch_product(direct_url, price_tier)
            if direct_data:
                usd, title, fetched_tier = direct_data
                # The page title must independently identify the card. The URL
                # is user-supplied, so allowing it to prove the identity would
                # make a wrong pasted link appear valid.
                confidence = identity_match_confidence(card, title)
                if confidence >= self.minimum_match_confidence:
                    LOGGER.info(
                        "Used watchlist PriceCharting reference for %s: %s",
                        card.key,
                        direct_url,
                    )
                    return CardPrice(
                        card=card,
                        unit_price_usd=usd,
                        unit_price_aud=usd * self.fx.usd_to_aud,
                        source_url=direct_url,
                        source_title=title,
                        match_confidence=confidence,
                        price_tier=fetched_tier,
                    )
                LOGGER.warning(
                    "Watchlist PriceCharting reference did not match %s at %.0f%%: "
                    "%s (%.1f%%); falling back to search",
                    card.key,
                    self.minimum_match_confidence * 100,
                    direct_url,
                    confidence * 100,
                )
            else:
                LOGGER.warning(
                    "Watchlist PriceCharting reference could not be fetched for %s: "
                    "%s; falling back to search",
                    card.key,
                    direct_url,
                )

        candidate = self._find_product_url(card)
        if not candidate or not candidate[0]:
            return None
        url, search_confidence = candidate

        data = self._fetch_product(url, price_tier)
        if not data:
            return None
        usd, title, fetched_tier = data
        confidence = min(
            search_confidence,
            identity_match_confidence(card, f"{title} {url}"),
        )
        if confidence < self.minimum_match_confidence:
            LOGGER.warning(
                "Rejected PriceCharting match below %.0f%% for %s: %s (%.1f%%)",
                self.minimum_match_confidence * 100,
                card.key,
                title,
                confidence * 100,
            )
            return None

        return CardPrice(
            card=card,
            unit_price_usd=usd,
            unit_price_aud=usd * self.fx.usd_to_aud,
            source_url=url,
            source_title=title,
            match_confidence=confidence,
            price_tier=fetched_tier,
        )

    def _find_product_url(self, card: IdentifiedCard) -> tuple[str, float] | None:
        full_query = " ".join(
            filter(
                None,
                [
                    card.name_en,
                    card.card_number,
                    card.set_name,
                    card.set_code,
                    VARIANT_QUERY_TERMS.get(_normalize_variant(card.variant)),
                    "Pokemon Japanese",
                ],
            )
        )
        fallback_query = " ".join(
            filter(
                None,
                [
                    card.name_en,
                    card.card_number,
                    VARIANT_QUERY_TERMS.get(_normalize_variant(card.variant)),
                    "Pokemon Japanese",
                ],
            )
        )

        for query in dict.fromkeys([full_query, fallback_query]):
            search_url = (
                f"{BASE_URL}/search-products?type=prices&q={quote_plus(query)}"
            )
            response = self._get(search_url)
            if response is None:
                continue
            soup = BeautifulSoup(response, "html.parser")
            candidates: list[tuple[float, str]] = []
            for link in soup.select('a[href*="/game/pokemon-japanese-"]'):
                href = urljoin(BASE_URL, link.get("href", ""))
                text = link.get_text(" ", strip=True)
                match_text = f"{text} {href}"
                score = identity_match_confidence(card, match_text)
                if score >= self.minimum_match_confidence:
                    candidates.append((score, href))
            if candidates:
                candidates.sort(key=lambda item: item[0], reverse=True)
                return candidates[0][1], candidates[0][0]

        LOGGER.info(
            "No PriceCharting result at or above %.0f%% for %s",
            self.minimum_match_confidence * 100,
            card.key,
        )
        return None

    def _fetch_product(
        self,
        url: str,
        price_tier: str = "Ungraded",
    ) -> tuple[float, str, str] | None:
        cached = self.cache.get(url)
        if cached:
            fetched_at = cached.get("fetched_at")
            try:
                fetched = datetime.fromisoformat(str(fetched_at))
            except (TypeError, ValueError):
                fetched = datetime.min.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - fetched < timedelta(hours=self.cache_hours):
                prices = cached.get("prices_usd") or {}
                # Migrate the previous one-price cache format without breaking
                # existing repositories. It is valid only for the ungraded tier.
                if not prices and cached.get("price_usd") is not None:
                    prices = {"Ungraded": float(cached["price_usd"])}
                if price_tier in prices:
                    return (
                        float(prices[price_tier]),
                        str(cached.get("title") or ""),
                        price_tier,
                    )

        html = self._get(url)
        if html is None:
            return None
        prices = parse_price_guide_usd(html)
        title = page_title(html)
        self.cache[url] = {
            "prices_usd": prices,
            "title": title,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        price = prices.get(price_tier)
        if price is None:
            LOGGER.warning(
                "PriceCharting page %s has no published %s guide value",
                url,
                price_tier,
            )
            return None
        return price, title, price_tier

    def _get(self, url: str) -> str | None:
        try:
            time.sleep(self.request_delay_seconds)
            response = self.client.get(url)
            response.raise_for_status()
            return response.text
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("PriceCharting request failed for %s: %s", url, exc)
            return None

    def _load_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self) -> None:
        self.cache_path.write_text(
            json.dumps(self.cache, indent=2, ensure_ascii=False), encoding="utf-8"
        )

    @staticmethod
    def _load_overrides(path: Path) -> dict[str, float]:
        values: dict[str, float] = {}
        if not path.exists():
            return values
        with path.open("r", encoding="utf-8", newline="") as handle:
            rows = (line for line in handle if not line.lstrip().startswith("#"))
            reader = csv.DictReader(rows)
            for row in reader:
                if not row or not row.get("price_aud"):
                    continue
                key = row.get("key") or "|".join(
                    [
                        "japanese",
                        (row.get("set_code") or "").lower(),
                        (row.get("card_number") or "").lower().replace(" ", ""),
                        (row.get("name") or "").lower(),
                    ]
                )
                values[key] = float(row["price_aud"])
        return values
