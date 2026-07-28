from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import tempfile
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse

import yaml

from . import main as legacy_main
from . import updated_main
from .models import WatchCard
from .sendico import SendicoMercariScanner

LOGGER = logging.getLogger(__name__)

_MAX_SEARCH_TERMS = 4
_MAX_RESULTS_PER_TERM = 20
_MAX_SCREENINGS = 20
_MAX_DETAILED = 5


@dataclass(frozen=True, slots=True)
class ManualScanRequest:
    target_name: str
    japanese_name: str
    card_number: str
    set_name: str
    set_code: str
    pricecharting_url: str
    search_terms: tuple[str, ...]
    results_per_term: int = 15
    screening_limit: int = 15
    detailed_limit: int = 3

    @classmethod
    def from_environment(cls) -> "ManualScanRequest":
        return cls(
            target_name=_required_env("SENDICO_TARGET_NAME"),
            japanese_name=os.getenv("SENDICO_JAPANESE_NAME", "").strip(),
            card_number=_required_env("SENDICO_CARD_NUMBER"),
            set_name=_required_env("SENDICO_SET_NAME"),
            set_code=os.getenv("SENDICO_SET_CODE", "").strip(),
            pricecharting_url=_required_env("SENDICO_PRICECHARTING_URL"),
            search_terms=tuple(
                parse_search_terms(_required_env("SENDICO_SEARCH_TERMS"))
            ),
            results_per_term=_bounded_int_env(
                "SENDICO_RESULTS_PER_TERM",
                default=15,
                minimum=5,
                maximum=_MAX_RESULTS_PER_TERM,
            ),
            screening_limit=_bounded_int_env(
                "SENDICO_SCREENING_LIMIT",
                default=15,
                minimum=5,
                maximum=_MAX_SCREENINGS,
            ),
            detailed_limit=_bounded_int_env(
                "SENDICO_DETAILED_LIMIT",
                default=3,
                minimum=1,
                maximum=_MAX_DETAILED,
            ),
        ).validated()

    def validated(self) -> "ManualScanRequest":
        if not self.target_name.strip():
            raise ValueError("Target card name is required")
        if not self.card_number.strip():
            raise ValueError("Printed card number is required")
        if not self.set_name.strip():
            raise ValueError("Set name is required")
        validate_pricecharting_url(self.pricecharting_url)
        if not self.search_terms:
            raise ValueError("At least one Sendico search term is required")
        if len(self.search_terms) > _MAX_SEARCH_TERMS:
            raise ValueError(
                f"Use no more than {_MAX_SEARCH_TERMS} search terms per run"
            )
        if self.detailed_limit > self.screening_limit:
            raise ValueError("Detailed-analysis limit cannot exceed screening limit")
        return self

    @property
    def candidate_limit(self) -> int:
        return min(
            _MAX_SEARCH_TERMS * _MAX_RESULTS_PER_TERM,
            len(self.search_terms) * self.results_per_term,
        )

    @property
    def raw_link_stop_limit(self) -> int:
        # Search cards can include links without a usable price. Stop at roughly
        # twice the requested result count, but never permit an open-ended scroll.
        return min(40, max(15, self.results_per_term * 2))


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(f"Missing required workflow input: {name}")
    return value


def _bounded_int_env(
    name: str,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a whole number") from exc
    if value < minimum or value > maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def parse_search_terms(raw: str) -> list[str]:
    values = re.split(r"[\n,;、]+", str(raw or ""))
    terms: list[str] = []
    for value in values:
        term = " ".join(value.strip().split())
        if not term or term in terms:
            continue
        if len(term) > 120:
            raise ValueError("Each search term must be 120 characters or fewer")
        terms.append(term)
    if len(terms) > _MAX_SEARCH_TERMS:
        raise ValueError(
            f"Use no more than {_MAX_SEARCH_TERMS} search terms per run"
        )
    return terms


def validate_pricecharting_url(value: str) -> None:
    parsed = urlparse(str(value or "").strip())
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or hostname not in {
        "pricecharting.com",
        "www.pricecharting.com",
    }:
        raise ValueError("PriceCharting URL must use https://www.pricecharting.com")
    if not parsed.path.startswith("/game/"):
        raise ValueError("PriceCharting URL must be a direct /game/ product page")


def build_watch_card(request: ManualScanRequest) -> WatchCard:
    safe_id = re.sub(r"[^a-z0-9]+", "_", request.target_name.casefold()).strip("_")
    return WatchCard(
        id=f"manual_{safe_id or 'target'}_{request.card_number.replace('/', '_')}",
        active=True,
        match_mode="exact_card",
        english_name=request.target_name,
        japanese_name=request.japanese_name or None,
        set_name=request.set_name,
        set_code=request.set_code or None,
        card_number=request.card_number,
        language="Japanese",
        pricecharting_url=request.pricecharting_url,
        search_terms=[],
    )


def build_runtime_config(
    base_config: dict[str, Any],
    request: ManualScanRequest,
) -> dict[str, Any]:
    # Round-trip through JSON to make a plain deep copy without retaining YAML
    # parser objects or mutating the checked-in configuration.
    config = json.loads(json.dumps(base_config))

    sendico = config.setdefault("sendico", {})
    sendico["max_results_per_search"] = request.results_per_term
    sendico["max_listings_per_run"] = request.candidate_limit
    sendico["maximum_scroll_rounds"] = 5
    sendico["stable_scroll_rounds_before_stop"] = 2
    sendico["scroll_pause_ms"] = 900
    sendico["search_link_stop_limit"] = request.raw_link_stop_limit
    sendico["prefilter_watchlist_relevance"] = True
    sendico["use_legacy_config_search_terms"] = False
    sendico["search_terms"] = []

    tier2 = sendico.setdefault("tier2_lot_search", {})
    tier2["enabled"] = True
    tier2["run_standard_watchlist_searches"] = False
    tier2["max_results_per_search"] = request.results_per_term
    tier2["allow_query_only_candidates"] = True
    tier2["screening_enabled"] = True
    tier2["max_screenings_per_run"] = min(
        request.screening_limit,
        request.candidate_limit,
    )
    tier2["era_set_screening_limit"] = min(
        request.screening_limit,
        request.candidate_limit,
    )
    tier2["generic_screening_limit"] = 0
    tier2["max_detailed_analyses_per_run"] = min(
        request.detailed_limit,
        request.screening_limit,
    )
    tier2["screening_max_overview_images"] = 3
    tier2["screening_max_dimension_px"] = 1100
    tier2["screening_jpeg_quality"] = 72
    tier2["detailed_max_overview_images"] = 8
    tier2["require_strong_lot_evidence"] = True

    vision = config.setdefault("vision", {})
    vision["pipeline_state_version"] = "gemini-manual-bounded-search-v1"
    vision["max_images_per_listing"] = 8
    vision["max_local_crops_per_listing"] = 24
    vision["max_listing_analyses_per_run"] = min(
        request.screening_limit,
        _MAX_SCREENINGS,
    )
    # Screening is normally one request per listing. Detailed positives can use
    # several crop batches, so retain headroom without allowing an unlimited run.
    vision["max_vision_requests_per_run"] = min(
        40,
        request.screening_limit + (request.detailed_limit * 5),
    )
    vision["contact_sheet_max_dimension_px"] = 900
    vision["contact_sheet_jpeg_quality"] = 76
    vision["max_completion_tokens"] = 1200
    vision["maximum_cards_to_price"] = 40

    config.setdefault("discord", {})["send_completion_summary"] = True
    config.setdefault("test_mode", {})["enabled"] = False
    return config


async def _bounded_scroll_search_results(self: Any, page: Any) -> None:
    """Stop loading Sendico results as soon as the configured raw-link cap is met."""

    maximum_rounds = max(1, int(self.config.get("maximum_scroll_rounds", 5)))
    stable_rounds_required = max(
        1,
        int(self.config.get("stable_scroll_rounds_before_stop", 2)),
    )
    scroll_pause_ms = max(250, int(self.config.get("scroll_pause_ms", 900)))
    raw_link_limit = max(
        1,
        int(
            self.config.get(
                "search_link_stop_limit",
                self.config.get("max_results_per_search", 20),
            )
        ),
    )

    previous_count = -1
    stable_rounds = 0
    for round_number in range(maximum_rounds + 1):
        current_count = await page.locator(
            'a[href*="/shop/mercari/catalog/"]'
        ).evaluate_all(
            """
            (anchors) => new Set(
              anchors
                .map((a) => a.href || '')
                .filter((href) => href && !href.includes('/categories/'))
            ).size
            """
        )
        LOGGER.info(
            "Bounded Sendico search round %d: %d unique links (stop at %d)",
            round_number,
            current_count,
            raw_link_limit,
        )

        if current_count >= raw_link_limit:
            LOGGER.info(
                "Stopping Sendico result loading at the configured raw-link cap"
            )
            return

        if current_count <= previous_count:
            stable_rounds += 1
        else:
            stable_rounds = 0
        if stable_rounds >= stable_rounds_required:
            LOGGER.info("Sendico results stabilised at %d unique links", current_count)
            return
        if round_number >= maximum_rounds:
            LOGGER.info("Reached bounded Sendico scroll limit of %d rounds", maximum_rounds)
            return

        previous_count = current_count
        load_more = page.get_by_role(
            "button",
            name=re.compile(
                r"load more|show more|more results|もっと見る",
                re.IGNORECASE,
            ),
        ).first
        try:
            if await load_more.count() and await load_more.is_visible():
                await load_more.click()
        except Exception:  # noqa: BLE001 - scrolling can still continue
            pass
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await page.wait_for_timeout(scroll_pause_ms)


@contextmanager
def manual_runtime_patches(request: ManualScanRequest) -> Iterator[None]:
    target = build_watch_card(request)
    original_load_watchlist = legacy_main.load_watchlist
    original_standard_terms = legacy_main.watchlist_search_terms
    original_era_terms = legacy_main.watchlist_era_lot_search_terms
    original_generic_terms = legacy_main.watchlist_generic_lot_search_terms
    original_scroll = SendicoMercariScanner._scroll_search_results

    def load_manual_watchlist(_config: Any) -> list[WatchCard]:
        return [target]

    def no_standard_terms(_targets: list[WatchCard]) -> list[str]:
        return []

    def manual_era_terms(_targets: list[WatchCard]) -> list[str]:
        return list(request.search_terms)

    def no_generic_terms(_targets: list[WatchCard]) -> list[str]:
        return []

    legacy_main.load_watchlist = load_manual_watchlist
    legacy_main.watchlist_search_terms = no_standard_terms
    legacy_main.watchlist_era_lot_search_terms = manual_era_terms
    legacy_main.watchlist_generic_lot_search_terms = no_generic_terms
    SendicoMercariScanner._scroll_search_results = _bounded_scroll_search_results
    try:
        yield
    finally:
        legacy_main.load_watchlist = original_load_watchlist
        legacy_main.watchlist_search_terms = original_standard_terms
        legacy_main.watchlist_era_lot_search_terms = original_era_terms
        legacy_main.watchlist_generic_lot_search_terms = original_generic_terms
        SendicoMercariScanner._scroll_search_results = original_scroll


@contextmanager
def runtime_config_file(
    config_path: str | Path,
    request: ManualScanRequest,
) -> Iterator[Path]:
    base_path = Path(config_path).resolve()
    with base_path.open("r", encoding="utf-8") as handle:
        base_config = yaml.safe_load(handle) or {}
    runtime_config = build_runtime_config(base_config, request)

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".manual_sendico_",
        suffix=".yaml",
        dir=base_path.parent,
        text=True,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    try:
        with temporary_path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(
                runtime_config,
                handle,
                allow_unicode=True,
                sort_keys=False,
            )
        yield temporary_path
    finally:
        temporary_path.unlink(missing_ok=True)


def _discord_start_payload(request: ManualScanRequest) -> dict[str, Any]:
    terms = "\n".join(f"• {term}" for term in request.search_terms)
    return {
        "username": "Pokemon Deal Scout",
        "embeds": [
            {
                "title": "SENDICO MANUAL SCAN STARTED",
                "description": (
                    f"Searching for **{request.target_name} {request.card_number}** "
                    "using only the terms entered in GitHub Actions."
                ),
                "color": 0x5865F2,
                "fields": [
                    {
                        "name": "Search terms",
                        "value": terms[:1024],
                        "inline": False,
                    },
                    {
                        "name": "Hard limits",
                        "value": (
                            f"Results per term: **{request.results_per_term}**\n"
                            f"Total candidate cap: **{request.candidate_limit}**\n"
                            f"Gemini screening cap: **{request.screening_limit}**\n"
                            f"Detailed-analysis cap: **{request.detailed_limit}**"
                        ),
                        "inline": False,
                    },
                    {
                        "name": "Price reference",
                        "value": f"[Open PriceCharting product page]({request.pricecharting_url})",
                        "inline": False,
                    },
                ],
            }
        ],
    }


def send_discord_start(webhook_url: str, request: ManualScanRequest) -> None:
    data = json.dumps(_discord_start_payload(request)).encode("utf-8")
    http_request = urllib.request.Request(
        webhook_url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=20) as response:  # noqa: S310
            if response.status >= 300:
                raise RuntimeError(f"Discord returned HTTP {response.status}")
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        LOGGER.warning("Could not send Discord start notification: %s", exc)


def request_summary(request: ManualScanRequest) -> str:
    return (
        f"Target: {request.target_name} {request.card_number} | "
        f"Set: {request.set_name} {request.set_code or ''} | "
        f"Terms: {list(request.search_terms)} | "
        f"Results/term: {request.results_per_term} | "
        f"Screenings: {request.screening_limit} | "
        f"Detailed: {request.detailed_limit}"
    )


async def run(
    config_path: str,
    *,
    dry_run: bool = False,
    validate_only: bool = False,
) -> int:
    request = ManualScanRequest.from_environment()
    LOGGER.info("Validated manual scan request: %s", request_summary(request))

    if validate_only:
        return 0

    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if webhook_url and not dry_run:
        await asyncio.to_thread(send_discord_start, webhook_url, request)

    with runtime_config_file(config_path, request) as generated_config:
        with manual_runtime_patches(request):
            return await updated_main.run(str(generated_config), dry_run)


def cli() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run a bounded Sendico scan using required GitHub/manual inputs instead "
            "of the checked-in broad watchlist searches"
        )
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        exit_code = asyncio.run(
            run(
                args.config,
                dry_run=args.dry_run,
                validate_only=args.validate_only,
            )
        )
    except ValueError as exc:
        LOGGER.error("Invalid manual scan input: %s", exc)
        exit_code = 2
    raise SystemExit(exit_code)


if __name__ == "__main__":
    cli()
