from __future__ import annotations

import argparse
import asyncio
import logging
import unicodedata

from .config import (
    load_config,
    load_watchlist,
    watchlist_lot_search_terms,
    watchlist_search_terms,
    watchlist_signature,
)
from .deal import assess_deal
from .discord import (
    send_discord,
    send_discord_test,
    send_discord_test_error,
    send_discord_test_start,
    send_discord_summary,
)
from .fx import FxClient
from .models import DealAssessment, SendicoListing
from .pricecharting import PriceChartingClient
from .reporting import write_reports
from .sendico import SendicoMercariScanner
from .state import StateStore
from .gemini_vision import GeminiLotVisionAnalyzer
from .vision import VisionRateLimitError, VisionRunBudgetReached

LOGGER = logging.getLogger(__name__)


def _merge_listing(existing: SendicoListing, found: SendicoListing) -> SendicoListing:
    """Merge richer search data into an existing direct-test placeholder."""
    if found.title and (
        existing.title == "Direct test listing" or not existing.title.strip()
    ):
        existing.title = found.title
    if found.price_yen > 0:
        existing.price_yen = found.price_yen
    if found.image_urls:
        existing.image_urls = list(
            dict.fromkeys([*existing.image_urls, *found.image_urls])
        )
    if found.description:
        existing.description = found.description
    if found.raw_text:
        existing.raw_text = found.raw_text
    if found.seller_positive_ratings is not None:
        existing.seller_positive_ratings = found.seller_positive_ratings
    return existing


def _compact_search(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).casefold()
    return "".join(character for character in normalized if character.isalnum())


_LOT_MARKERS = (
    "lot",
    "collection",
    "bundle",
    "まとめ",
    "セット",
    "引退",
    "大量",
)


def _contains_lot_marker(haystack: str) -> bool:
    return any(_compact_search(term) in haystack for term in _LOT_MARKERS)


def _candidate_relevance_score(
    listing: SendicoListing,
    targets,
) -> int:
    """Score a search result before spending a Gemini request on it.

    The filter is intentionally based on explicit names, printed numbers and set
    references. A result with no local evidence for any active watchlist rule is
    skipped; direct test URLs bypass this filter in ``run``.
    """
    haystack = _compact_search(
        " ".join([listing.title, listing.raw_text, listing.description[:500]])
    )
    if not haystack:
        return 0

    best = 0
    lot_match = _contains_lot_marker(haystack)
    for target in targets:
        score = 0
        names = [
            *target.english_names,
            *target.japanese_names,
        ]
        name_match = any(
            compact_name and compact_name in haystack
            for compact_name in (_compact_search(name) for name in names)
        )
        if name_match:
            score += 60
            if lot_match:
                # Pokemon name plus an explicit lot marker is the intended
                # Tier 2 opportunity: broader than an exact card listing, but
                # still much more relevant than a generic collection.
                score += 40

        if target.match_mode == "exact_card" and target.card_number:
            full_number = _compact_search(target.card_number)
            numerator = _compact_search(str(target.card_number).split("/", 1)[0])
            if full_number and full_number in haystack:
                score += 100
            elif name_match and numerator and numerator in haystack:
                score += 20

        set_values = [
            target.set_name,
            target.set_code,
            *target.accepted_sets,
            *target.accepted_set_codes,
        ]
        if any(
            compact_set and compact_set in haystack
            for compact_set in (_compact_search(value) for value in set_values)
        ):
            score += 20

        if any(
            compact_term and compact_term in haystack
            for compact_term in (
                _compact_search(term) for term in target.search_terms
            )
        ):
            score += 30

        best = max(best, score)

    # Keep generic multi-card lots as low-priority candidates because the target
    # may be visible in the photos even when the seller did not name it. Strong
    # explicit matches are always ranked ahead of these fallback candidates.
    if best == 0 and lot_match:
        return 5
    return best


def _is_tier2_only(sources: set[str]) -> bool:
    return (
        "tier2_lot" in sources
        and "watchlist" not in sources
        and "direct" not in sources
    )


def _rank_candidate_pool(
    candidates: dict[str, SendicoListing],
    candidate_sources: dict[str, set[str]],
    targets,
    *,
    direct_codes: set[str],
    prefilter_enabled: bool,
    allow_tier2_query_only: bool,
) -> tuple[list[SendicoListing], int, int]:
    """Rank exact/watchlist results first and Tier 2-only lots second.

    A Tier 2 query can return a listing whose visible search-result text does not
    repeat the Pokemon name. When explicitly enabled, those query-only results are
    retained at the lowest priority so Gemini can inspect the photos. The Gemini
    analysis cap is applied later, after unchanged listings have been skipped, so
    additional Tier 2 candidates can rotate into subsequent runs.
    """
    regular_ranked: list[tuple[int, SendicoListing]] = []
    tier2_ranked: list[tuple[int, SendicoListing]] = []
    prefiltered_out = 0

    for candidate in candidates.values():
        sources = candidate_sources.get(candidate.code, set())
        if candidate.code in direct_codes:
            score = 10_000
        else:
            score = _candidate_relevance_score(candidate, targets)

        tier2_only = _is_tier2_only(sources)
        if score <= 0:
            if tier2_only and allow_tier2_query_only:
                score = 1
            elif prefilter_enabled:
                prefiltered_out += 1
                continue

        destination = tier2_ranked if tier2_only else regular_ranked
        destination.append((score, candidate))

    regular_ranked.sort(key=lambda item: item[0], reverse=True)
    tier2_ranked.sort(key=lambda item: item[0], reverse=True)

    selected = [candidate for _, candidate in regular_ranked]
    selected.extend(candidate for _, candidate in tier2_ranked)
    return selected, prefiltered_out, len(tier2_ranked)


async def run(config_path: str, dry_run: bool = False) -> int:
    config = load_config(config_path)
    targets = load_watchlist(config)
    targets_by_id = {target.id: target for target in targets}
    scan_signature = watchlist_signature(targets)
    LOGGER.info(
        "Loaded %d active watchlist rule(s): %s",
        len(targets),
        ", ".join(f"{target.id} ({target.match_mode})" for target in targets),
    )

    vision_cfg = config.raw["vision"]
    configured_models_raw = vision_cfg.get("models") or []
    if isinstance(configured_models_raw, str):
        configured_models = [configured_models_raw]
    else:
        configured_models = [
            str(value).strip()
            for value in configured_models_raw
            if str(value).strip()
        ]
    legacy_model = str(vision_cfg.get("model") or "").strip()
    if legacy_model and legacy_model not in configured_models:
        configured_models.append(legacy_model)
    if not configured_models:
        configured_models = ["gemini-3.6-flash", "gemini-3.5-flash-lite"]
    model_pool_label = ", ".join(configured_models)

    if vision_cfg.get("enabled", True) and not config.gemini_api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is required to identify cards in lot images"
        )

    seller_cfg = config.raw.get("seller_verification", {})
    analyse_unverified = bool(seller_cfg.get("analyse_unverified_sellers", True))
    alert_provisional = bool(seller_cfg.get("alert_provisional_deals", True))

    test_cfg = config.raw.get("test_mode", {})
    test_mode = bool(test_cfg.get("enabled", False))
    test_alert_limit = int(test_cfg.get("max_alerts_per_run", 3))
    ignore_seen_state = bool(test_cfg.get("ignore_seen_state", True))
    test_alerts_sent = 0

    retry_cfg = config.raw.get("retry_policy", {})
    max_retry_attempts = max(
        1,
        int(retry_cfg.get("max_attempts_per_listing", 3)),
    )

    if test_mode:
        LOGGER.warning(
            "TEST MODE ENABLED: seller, target and saving restrictions will not "
            "prevent diagnostic Discord alerts"
        )
        if not dry_run and config.discord_webhook_url:
            try:
                await asyncio.to_thread(
                    send_discord_test_start,
                    config.discord_webhook_url,
                    str(config.raw["discord"].get("username", "Pokemon Deal Scout")),
                    model_pool_label,
                    test_alert_limit,
                )
            except Exception:
                LOGGER.exception("Could not send test-mode startup message to Discord")

    fx_cfg = config.raw["pricing"]
    fx = FxClient(
        manual_usd_to_aud=float(fx_cfg["manual_usd_to_aud"]),
        manual_jpy_to_aud=float(fx_cfg["manual_jpy_to_aud"]),
    ).get_rates()
    LOGGER.info(
        "FX rates: USD/AUD %.4f, JPY/AUD %.6f (%s)",
        fx.usd_to_aud,
        fx.jpy_to_aud,
        fx.source,
    )

    price_client = PriceChartingClient(
        root=config.root,
        fx=fx,
        request_delay_seconds=float(fx_cfg.get("request_delay_seconds", 1.2)),
        cache_hours=int(fx_cfg.get("cache_hours", 12)),
        minimum_match_confidence=float(
            fx_cfg.get("minimum_match_confidence", 0.95)
        ),
    )
    vision = GeminiLotVisionAnalyzer(
        api_key=config.gemini_api_key or "",
        model=legacy_model or None,
        models=configured_models,
        max_model_attempts_per_request=int(
            vision_cfg.get("max_model_attempts_per_request", 2)
        ),
        thinking_level=str(vision_cfg.get("thinking_level", "low")),
        max_retries_per_model=int(
            vision_cfg.get("max_retries_per_model", 2)
        ),
        retry_base_seconds=float(
            vision_cfg.get("retry_base_seconds", 2.0)
        ),
        retry_max_seconds=float(
            vision_cfg.get("retry_max_seconds", 30.0)
        ),
        api_version=str(vision_cfg.get("api_version", "v1beta")),
        api_revision=str(vision_cfg.get("api_revision", "2026-05-20")),
        request_timeout_seconds=float(
            vision_cfg.get("request_timeout_seconds", 240.0)
        ),
        max_images=int(vision_cfg["max_images_per_listing"]),
        max_local_crops=int(vision_cfg.get("max_local_crops_per_listing", 40)),
        crop_batch_size=int(vision_cfg.get("crop_batch_size", 4)),
        request_spacing_seconds=float(
            vision_cfg.get("request_spacing_seconds", 1.0)
        ),
        max_completion_tokens=int(
            vision_cfg.get("max_completion_tokens", 1600)
        ),
        contact_sheet_max_dimension_px=int(
            vision_cfg.get("contact_sheet_max_dimension_px", 1100)
        ),
        contact_sheet_jpeg_quality=int(
            vision_cfg.get("contact_sheet_jpeg_quality", 82)
        ),
        analysis_max_dimension_px=int(
            vision_cfg.get("local_analysis_max_dimension_px", 2200)
        ),
        crop_max_dimension_px=int(
            vision_cfg.get("crop_max_dimension_px", 1400)
        ),
        crop_jpeg_quality=int(vision_cfg.get("crop_jpeg_quality", 86)),
        minimum_card_area_ratio=float(
            vision_cfg.get("minimum_card_area_ratio", 0.012)
        ),
        maximum_card_area_ratio=float(
            vision_cfg.get("maximum_card_area_ratio", 0.98)
        ),
        minimum_rectangularity=float(
            vision_cfg.get("minimum_rectangularity", 0.58)
        ),
        card_aspect_ratio_min=float(
            vision_cfg.get("card_aspect_ratio_min", 0.52)
        ),
        card_aspect_ratio_max=float(
            vision_cfg.get("card_aspect_ratio_max", 0.84)
        ),
        duplicate_phash_distance=int(
            vision_cfg.get("duplicate_phash_distance", 10)
        ),
        crop_padding_percent=float(
            vision_cfg.get("crop_padding_percent", 0.025)
        ),
        max_requests_per_run=int(
            vision_cfg.get("max_vision_requests_per_run", 150)
        ),
    )
    state = StateStore(config.path("data/seen.json"))
    candidates: dict[str, SendicoListing] = {}
    candidate_sources: dict[str, set[str]] = {}
    assessments: list[DealAssessment] = []
    direct_codes: set[str] = set()
    discovered_count = 0
    prefiltered_out = 0
    tier2_selected_count = 0
    tier2_analyses_started = 0
    tier2_held_count = 0
    hydrated_count = 0
    unchanged_skipped = 0
    seller_filtered = 0
    vision_analyses_started = 0
    alerts_sent = 0
    processing_errors = 0
    stop_reason: str | None = None

    try:
        async with SendicoMercariScanner(config.raw["sendico"]) as scanner:
            direct_urls = [
                str(url).strip()
                for url in test_cfg.get("direct_listing_urls", [])
                if str(url).strip()
            ]
            direct_codes = {
                url.rstrip("/").split("/")[-1] for url in direct_urls
            }
            for direct_url in direct_urls:
                code = direct_url.rstrip("/").split("/")[-1]
                candidates[code] = SendicoListing(
                    code=code,
                    url=direct_url,
                    title="Direct test listing",
                    price_yen=0,
                )
                candidate_sources.setdefault(code, set()).add("direct")
                LOGGER.info("Queued direct test listing: %s", direct_url)

            sendico_cfg = config.raw["sendico"]
            configured_terms = watchlist_search_terms(targets)
            if bool(sendico_cfg.get("use_legacy_config_search_terms", False)):
                configured_terms = list(
                    dict.fromkeys(
                        [
                            *configured_terms,
                            *(
                                str(term).strip()
                                for term in sendico_cfg.get("search_terms", [])
                                if str(term).strip()
                            ),
                        ]
                    )
                )

            tier2_cfg = sendico_cfg.get("tier2_lot_search", {}) or {}
            tier2_enabled = bool(tier2_cfg.get("enabled", False))
            tier2_terms = (
                watchlist_lot_search_terms(targets) if tier2_enabled else []
            )
            # A term already used by the normal watchlist search does not need a
            # second marketplace request. It remains classified as a normal result.
            tier2_terms = [
                term for term in tier2_terms if term not in set(configured_terms)
            ]
            if tier2_enabled and not tier2_terms:
                LOGGER.warning(
                    "Tier 2 lot search is enabled, but no active watchlist entry "
                    "contains lot_search_terms"
                )

            if not configured_terms and not tier2_terms and not direct_urls:
                raise RuntimeError(
                    "No Sendico search terms were produced by the active watchlist"
                )

            # A direct test URL can be hydrated from its own detail page. Skipping
            # the category search avoids a slow Sendico category page preventing
            # the actual test listing from being analysed.
            skip_search_for_direct_test = bool(
                test_mode
                and direct_urls
                and test_cfg.get("skip_search_when_direct_urls", True)
            )
            if skip_search_for_direct_test:
                search_plan: list[tuple[str, str]] = []
                LOGGER.info(
                    "Direct test mode: skipping category searches and hydrating "
                    "%d direct listing(s)",
                    len(direct_urls),
                )
            else:
                search_plan = [
                    *(("direct", code) for code in sorted(direct_codes)),
                    *(("watchlist", term) for term in configured_terms),
                    *(("tier2_lot", term) for term in tier2_terms),
                ]

            tier2_results_per_search = max(
                0,
                int(tier2_cfg.get("max_results_per_search", 30)),
            )
            search_labels = {
                "direct": "direct listing",
                "watchlist": "watchlist",
                "tier2_lot": "Tier 2 lot",
            }
            for source, term in search_plan:
                LOGGER.info(
                    "Searching Sendico Mercari [%s]: %s",
                    search_labels[source],
                    term,
                )
                try:
                    found_results = await scanner.search(term)
                except Exception as exc:  # noqa: BLE001 - a search must not abort a run
                    LOGGER.warning(
                        "Sendico search failed for %s; continuing with other "
                        "searches/direct listings: %s",
                        term,
                        exc,
                    )
                    continue

                if source == "tier2_lot" and tier2_results_per_search > 0:
                    found_results = found_results[:tier2_results_per_search]

                for found_listing in found_results:
                    existing = candidates.get(found_listing.code)
                    if existing is None:
                        candidates[found_listing.code] = found_listing
                    else:
                        _merge_listing(existing, found_listing)
                    candidate_sources.setdefault(found_listing.code, set()).add(source)

            discovered_count = len(candidates)
            prefilter_enabled = bool(
                sendico_cfg.get("prefilter_watchlist_relevance", True)
            )
            (
                listings_to_process,
                prefiltered_out,
                tier2_selected_count,
            ) = _rank_candidate_pool(
                candidates,
                candidate_sources,
                targets,
                direct_codes=direct_codes,
                prefilter_enabled=prefilter_enabled,
                allow_tier2_query_only=bool(
                    tier2_cfg.get("allow_query_only_candidates", True)
                ),
            )

            limit = int(sendico_cfg.get("max_listings_per_run", 0))
            if limit > 0:
                listings_to_process = listings_to_process[:limit]

            tier2_selected_count = sum(
                1
                for listing in listings_to_process
                if _is_tier2_only(candidate_sources.get(listing.code, set()))
            )
            tier2_analysis_limit = max(
                0,
                int(tier2_cfg.get("max_analyses_per_run", 20)),
            )

            LOGGER.info(
                "Search found %d unique listing(s); %d selected for processing "
                "including %d Tier 2 lot candidate(s); %d filtered before Gemini; "
                "Tier 2 Gemini analysis cap: %s",
                discovered_count,
                len(listings_to_process),
                tier2_selected_count,
                prefiltered_out,
                tier2_analysis_limit or "unlimited",
            )

            for listing_index, listing in enumerate(listings_to_process):
                try:
                    listing = await scanner.hydrate(listing)
                    hydrated_count += 1

                    if state.unchanged(
                        listing,
                        max_attempts=max_retry_attempts,
                        scan_signature=scan_signature,
                    ) and not (test_mode and ignore_seen_state):
                        attempts = state.attempt_count(listing, scan_signature)
                        LOGGER.info(
                            "Skipping unchanged listing %s (attempts: %d/%d; "
                            "already processed or retry limit reached)",
                            listing.code,
                            attempts,
                            max_retry_attempts,
                        )
                        unchanged_skipped += 1
                        continue

                    if test_mode:
                        LOGGER.warning(
                            "TEST MODE: bypassing seller-rating filter for %s",
                            listing.code,
                        )
                    else:
                        if (
                            listing.seller_positive_ratings is None
                            and not analyse_unverified
                        ):
                            LOGGER.info(
                                "Rejecting %s: seller rating unverified",
                                listing.code,
                            )
                            state.update(
                                listing,
                                False,
                                "seller rating unverified",
                                scan_signature,
                            )
                            seller_filtered += 1
                            continue

                        if listing.seller_positive_ratings is None:
                            LOGGER.warning(
                                "Continuing %s provisionally: seller rating requires "
                                "manual verification",
                                listing.code,
                            )
                        elif (
                            listing.seller_positive_ratings
                            < config.minimum_seller_positive_ratings
                        ):
                            outcome = (
                                f"seller rating {listing.seller_positive_ratings} "
                                "below threshold"
                            )
                            LOGGER.info("Rejecting %s: %s", listing.code, outcome)
                            state.update(listing, False, outcome, scan_signature)
                            seller_filtered += 1
                            continue

                    tier2_only = _is_tier2_only(
                        candidate_sources.get(listing.code, set())
                    )
                    if (
                        tier2_only
                        and tier2_analysis_limit > 0
                        and tier2_analyses_started >= tier2_analysis_limit
                    ):
                        tier2_held_count = sum(
                            1
                            for remaining in listings_to_process[listing_index:]
                            if _is_tier2_only(
                                candidate_sources.get(remaining.code, set())
                            )
                        )
                        LOGGER.info(
                            "Tier 2 Gemini analysis cap of %d reached; %d remaining "
                            "Tier 2 candidate(s) will be reconsidered on the next run",
                            tier2_analysis_limit,
                            tier2_held_count,
                        )
                        break

                    max_vision_listings = max(
                        0,
                        int(vision_cfg.get("max_listing_analyses_per_run", 10)),
                    )
                    if (
                        max_vision_listings > 0
                        and vision_analyses_started >= max_vision_listings
                    ):
                        stop_reason = (
                            "Stopped at the configured Gemini listing-analysis cap "
                            f"of {max_vision_listings}; remaining eligible listings "
                            "will be considered on the next run."
                        )
                        LOGGER.info(stop_reason)
                        break

                    vision_analyses_started += 1
                    if tier2_only:
                        tier2_analyses_started += 1
                    vision_result = await asyncio.to_thread(
                        vision.analyze,
                        listing,
                        targets,
                    )

                    raw_eligible = [
                        card
                        for card in vision_result.cards
                        if card.language.lower() == "japanese"
                        and card.confidence
                        >= float(vision_cfg["minimum_card_confidence"])
                    ]

                    # The same physical cards may appear in multiple listing photos.
                    # Keep the highest reported quantity per exact card instead of
                    # summing duplicate appearances across images.
                    by_key = {}
                    for card in raw_eligible:
                        existing = by_key.get(card.key)
                        if existing is None or card.quantity > existing.quantity:
                            by_key[card.key] = card

                    eligible_cards = list(by_key.values())[
                        : int(vision_cfg["maximum_cards_to_price"])
                    ]
                    priced = []
                    for card in eligible_cards:
                        matched_targets = [
                            targets_by_id[target_id]
                            for target_id in card.matched_watchlist_ids
                            if target_id in targets_by_id
                        ]
                        direct_target = next(
                            (
                                target
                                for target in matched_targets
                                if target.pricecharting_url
                            ),
                            None,
                        )
                        result = await asyncio.to_thread(
                            price_client.price_card,
                            card,
                            direct_target,
                        )
                        if result:
                            priced.append(result)

                    assessment = assess_deal(
                        listing=listing,
                        vision=vision_result,
                        priced_cards=priced,
                        fx=fx,
                        fee_config=config.raw["sendico_fee"],
                        minimum_seller_ratings=config.minimum_seller_positive_ratings,
                        minimum_target_confidence=float(
                            vision_cfg["minimum_target_confidence"]
                        ),
                    )
                    assessments.append(assessment)

                    if test_mode:
                        if test_alerts_sent >= test_alert_limit:
                            LOGGER.info(
                                "Test alert limit reached; not sending %s",
                                listing.code,
                            )
                        elif dry_run:
                            LOGGER.info(
                                "DRY RUN diagnostic result: %s",
                                listing.url,
                            )
                        elif not config.discord_webhook_url:
                            LOGGER.warning(
                                "Test result created but DISCORD_WEBHOOK_URL is unset"
                            )
                        else:
                            await asyncio.to_thread(
                                send_discord_test,
                                config.discord_webhook_url,
                                assessment,
                                str(
                                    config.raw["discord"].get(
                                        "username",
                                        "Pokemon Deal Scout",
                                    )
                                ),
                            )
                            test_alerts_sent += 1

                        state.update(
                            listing,
                            False,
                            "test mode analysed",
                            scan_signature,
                        )
                        continue

                    alert_eligible = assessment.qualifies or (
                        assessment.provisional_qualifies and alert_provisional
                    )
                    alerted = False
                    if alert_eligible and not state.was_alerted(
                        listing,
                        scan_signature,
                    ):
                        alert_kind = (
                            "qualifying" if assessment.qualifies else "provisional"
                        )
                        if dry_run or not config.raw["discord"].get("enabled", True):
                            LOGGER.info(
                                "DRY RUN %s deal: %s",
                                alert_kind,
                                listing.url,
                            )
                        elif not config.discord_webhook_url:
                            LOGGER.warning(
                                "%s deal found but DISCORD_WEBHOOK_URL is unset",
                                alert_kind,
                            )
                        else:
                            await asyncio.to_thread(
                                send_discord,
                                config.discord_webhook_url,
                                assessment,
                                str(
                                    config.raw["discord"].get(
                                        "username",
                                        "Pokemon Deal Scout",
                                    )
                                ),
                            )
                            alerted = True
                            alerts_sent += 1

                    if assessment.qualifies:
                        outcome = "qualifies"
                    elif assessment.provisional_qualifies:
                        outcome = (
                            "provisional deal; seller rating requires manual verification"
                        )
                    else:
                        outcome = "; ".join(assessment.rejection_reasons)
                    state.update(
                        listing,
                        alerted,
                        outcome,
                        scan_signature,
                    )

                except VisionRunBudgetReached as exc:
                    stop_reason = str(exc)
                    LOGGER.info(
                        "Stopping before another Gemini request would exceed the "
                        "configured per-run budget: %s",
                        exc,
                    )
                    break

                except VisionRateLimitError as exc:
                    stop_reason = f"Gemini capacity or rate limit reached: {exc}"
                    LOGGER.warning(
                        "Gemini capacity or rate limit reached; recording this attempt and "
                        "stopping the run so remaining listings can resume next "
                        "week: %s",
                        exc,
                    )
                    state.update(
                        listing,
                        False,
                        f"error: {exc}",
                        scan_signature,
                    )
                    break

                except Exception as exc:  # noqa: BLE001 - continue other listings
                    processing_errors += 1
                    LOGGER.exception(
                        "Listing processing failed for %s: %s",
                        listing.url,
                        exc,
                    )

                    if (
                        test_mode
                        and config.discord_webhook_url
                        and test_alerts_sent < test_alert_limit
                    ):
                        try:
                            await asyncio.to_thread(
                                send_discord_test_error,
                                config.discord_webhook_url,
                                listing,
                                str(exc),
                                str(
                                    config.raw["discord"].get(
                                        "username",
                                        "Pokemon Deal Scout",
                                    )
                                ),
                            )
                            test_alerts_sent += 1
                        except Exception:
                            LOGGER.exception(
                                "Could not send diagnostic error to Discord"
                            )

                    state.update(
                        listing,
                        False,
                        f"error: {exc}",
                        scan_signature,
                    )
    finally:
        price_client.close()
        state.save()
        write_reports(config.root, assessments)

    strict_count = sum(a.qualifies for a in assessments)
    provisional_count = sum(a.provisional_qualifies for a in assessments)

    if (
        not dry_run
        and config.raw["discord"].get("enabled", True)
        and config.raw["discord"].get("send_completion_summary", True)
        and config.discord_webhook_url
    ):
        try:
            await asyncio.to_thread(
                send_discord_summary,
                config.discord_webhook_url,
                str(
                    config.raw["discord"].get(
                        "username",
                        "Pokemon Deal Scout",
                    )
                ),
                discovered=discovered_count,
                prefiltered_out=prefiltered_out,
                hydrated=hydrated_count,
                tier2_selected=tier2_selected_count,
                tier2_analysed=tier2_analyses_started,
                tier2_held=tier2_held_count,
                unchanged_skipped=unchanged_skipped,
                seller_filtered=seller_filtered,
                analysed=vision_analyses_started,
                assessments=len(assessments),
                strict_matches=strict_count,
                provisional_matches=provisional_count,
                alerts_sent=alerts_sent,
                errors=processing_errors,
                vision_requests=vision.requests_sent,
                vision_models=vision.models_used_summary,
                vision_usage=vision.usage_summary,
                stop_reason=stop_reason,
            )
        except Exception:
            LOGGER.exception("Could not send the Discord scan-completion summary")

    LOGGER.info(
        "Completed: %d discovered, %d Tier 2 candidates, %d Tier 2 analysed, "
        "%d filtered before Gemini, %d assessments, %d strict qualifying, "
        "%d provisional, %d deal alerts, %d test alerts, %d Gemini requests%s",
        discovered_count,
        tier2_selected_count,
        tier2_analyses_started,
        prefiltered_out,
        len(assessments),
        strict_count,
        provisional_count,
        alerts_sent,
        test_alerts_sent,
        vision.requests_sent,
        f"; models used: {vision.models_used_summary}"
        + (f"; stopped: {stop_reason}" if stop_reason else ""),
    )
    return 0


def cli() -> None:
    parser = argparse.ArgumentParser(
        description="Sendico Mercari Japanese Pokemon deal scanner"
    )
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    raise SystemExit(asyncio.run(run(args.config, args.dry_run)))


if __name__ == "__main__":
    cli()
