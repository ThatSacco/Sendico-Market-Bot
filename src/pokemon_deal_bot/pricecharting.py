from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
import time
from dataclasses import asdict
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


def _word_tokens(value: str | None) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]+", (value or "").lower())
        if token and token not in GENERIC_SET_TOKENS
    ]


def _card_numerator(card_number: str) -> str:
    return normalize_number(card_number.split("/", 1)[0])


def _candidate_numbers(text: str) -> set[str]:
    values = {
        normalize_number(match)
        for match in re.findall(r"#\s*0*([0-9]{1,3})(?=\D|$)", text, re.IGNORECASE)
    }
    values.update(
        normalize_number(match)
        for match in re.findall(r"/[^?#\s]+-0*([0-9]{1,3})(?:[/?#]|$)", text, re.IGNORECASE)
    )
    return {value for value in values if value}


def _set_matches(card: IdentifiedCard, text: str) -> bool:
    haystack = text.lower()
    compact = re.sub(r"[^a-z0-9]", "", haystack)
    set_code = re.sub(r"[^a-z0-9]", "", (card.set_code or "").lower())
    if set_code and set_code in compact:
        return True

    tokens = _word_tokens(card.set_name)
    if not tokens:
        return False
    matched = sum(token in haystack for token in tokens)
    required = 1 if len(tokens) == 1 else max(2, (len(tokens) + 1) // 2)
    return matched >= required


def strict_identity_match(card: IdentifiedCard, text: str) -> bool:
    """Require card name, exact printed numerator and matching Japanese set."""
    haystack = text.lower()
    name_tokens = [token for token in re.findall(r"[a-z0-9]+", card.name_en.lower()) if token]
    if not name_tokens or not all(token in haystack for token in name_tokens):
        return False

    numbers = _candidate_numbers(text)
    if _card_numerator(card.card_number) not in numbers:
        return False

    return _set_matches(card, text)


def normalize_number(value: str) -> str:
    return value.lower().replace("#", "").replace(" ", "").lstrip("0")


def parse_ungraded_usd(html: str) -> float | None:
    soup = BeautifulSoup(html, "html.parser")
    text = " ".join(soup.stripped_strings)
    patterns = [
        re.compile(r"Full Price Guide:.*?Ungraded\s*\$([0-9][0-9,]*\.?[0-9]*)", re.IGNORECASE),
        re.compile(r"Ungraded\s*\|?\s*\$([0-9][0-9,]*\.?[0-9]*)", re.IGNORECASE),
        re.compile(r"Loose Price.*?\$([0-9][0-9,]*\.?[0-9]*)", re.IGNORECASE),
    ]
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return float(match.group(1).replace(",", ""))
    return None


def page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = h1.get_text(" ", strip=True) if h1 else (soup.title.get_text(" ", strip=True) if soup.title else "")
    return title


class PriceChartingClient:
    def __init__(
        self,
        root: Path,
        fx: FxRates,
        request_delay_seconds: float,
        cache_hours: int,
    ) -> None:
        self.root = root
        self.fx = fx
        self.request_delay_seconds = request_delay_seconds
        self.cache_hours = cache_hours
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

    def price_card(self, card: IdentifiedCard, target: WatchCard | None = None) -> CardPrice | None:
        override = self.overrides.get(card.key)
        if override is not None:
            return CardPrice(
                card=card,
                unit_price_usd=override / self.fx.usd_to_aud,
                unit_price_aud=override,
                source_url="manual override",
                source_title="Manual AUD override",
                match_confidence=1.0,
            )
        direct_url = target.pricecharting_url if target and card.is_target else None
        url = direct_url or self._find_product_url(card)
        if not url:
            return None
        data = self._fetch_product(url)
        if not data:
            return None
        usd, title = data
        match_text = f"{title} {url}"
        confidence = self._title_confidence(card, match_text)
        if not direct_url and confidence < 1.0:
            LOGGER.warning(
                "Rejected non-exact PriceCharting match for %s: %s",
                card.key,
                title,
            )
            return None
        return CardPrice(
            card=card,
            unit_price_usd=usd,
            unit_price_aud=usd * self.fx.usd_to_aud,
            source_url=url,
            source_title=title,
            match_confidence=1.0 if direct_url else confidence,
        )

    def _find_product_url(self, card: IdentifiedCard) -> str | None:
        query = " ".join(
            filter(
                None,
                [card.name_en, card.card_number, card.set_name, card.set_code, "Pokemon Japanese"],
            )
        )
        search_url = f"{BASE_URL}/search-products?type=prices&q={quote_plus(query)}"
        response = self._get(search_url)
        if response is None:
            return None
        soup = BeautifulSoup(response, "html.parser")
        candidates: list[tuple[float, str]] = []
        for link in soup.select('a[href*="/game/pokemon-japanese-"]'):
            href = urljoin(BASE_URL, link.get("href", ""))
            text = link.get_text(" ", strip=True)
            match_text = text + " " + href
            if not strict_identity_match(card, match_text):
                continue
            score = self._candidate_score(card, match_text)
            candidates.append((score, href))
        if not candidates:
            LOGGER.info("No exact PriceCharting result for %s", card.key)
            return None
        candidates.sort(reverse=True)
        return candidates[0][1]

    def _fetch_product(self, url: str) -> tuple[float, str] | None:
        cached = self.cache.get(url)
        if cached:
            fetched = datetime.fromisoformat(cached["fetched_at"])
            if datetime.now(timezone.utc) - fetched < timedelta(hours=self.cache_hours):
                return float(cached["price_usd"]), str(cached["title"])
        html = self._get(url)
        if html is None:
            return None
        price = parse_ungraded_usd(html)
        if price is None:
            return None
        title = page_title(html)
        self.cache[url] = {
            "price_usd": price,
            "title": title,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        return price, title

    def _get(self, url: str) -> str | None:
        try:
            time.sleep(self.request_delay_seconds)
            response = self.client.get(url)
            response.raise_for_status()
            return response.text
        except Exception as exc:  # noqa: BLE001
            LOGGER.warning("PriceCharting request failed for %s: %s", url, exc)
            return None

    @staticmethod
    def _candidate_score(card: IdentifiedCard, text: str) -> float:
        return 1.0 if strict_identity_match(card, text) else 0.0

    @classmethod
    def _title_confidence(cls, card: IdentifiedCard, title: str) -> float:
        return cls._candidate_score(card, title)

    def _load_cache(self) -> dict:
        if not self.cache_path.exists():
            return {}
        try:
            return json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _save_cache(self) -> None:
        self.cache_path.write_text(json.dumps(self.cache, indent=2, ensure_ascii=False), encoding="utf-8")

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
