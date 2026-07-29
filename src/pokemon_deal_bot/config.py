from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml

from .models import WatchCard


# data/run_limits.yaml uses friendly names. These mappings preserve the existing
# runtime structure expected by main.py, sendico.py and the Gemini analyser.
_LIMIT_MAPPINGS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("retry", "max_attempts_per_listing"), ("retry_policy", "max_attempts_per_listing")),
    (("test_mode", "max_alerts_per_run"), ("test_mode", "max_alerts_per_run")),
    (("search", "results_per_term"), ("sendico", "max_results_per_search")),
    (("search", "results_per_term"), ("sendico", "tier2_lot_search", "max_results_per_search")),
    (("search", "total_listings_per_run"), ("sendico", "max_listings_per_run")),
    (("search", "raw_links_per_term"), ("sendico", "max_raw_links_per_search")),
    (("search", "page_timeout_ms"), ("sendico", "page_timeout_ms")),
    (("search", "max_scroll_rounds"), ("sendico", "maximum_scroll_rounds")),
    (("search", "stable_rounds_before_stop"), ("sendico", "stable_scroll_rounds_before_stop")),
    (("search", "scroll_pause_ms"), ("sendico", "scroll_pause_ms")),
    (("screening", "max_listings_per_run"), ("sendico", "tier2_lot_search", "max_screenings_per_run")),
    (("screening", "focused_lot_limit"), ("sendico", "tier2_lot_search", "era_set_screening_limit")),
    (("screening", "generic_lot_limit"), ("sendico", "tier2_lot_search", "generic_screening_limit")),
    (("screening", "max_overview_images"), ("sendico", "tier2_lot_search", "screening_max_overview_images")),
    (("screening", "max_image_dimension_px"), ("sendico", "tier2_lot_search", "screening_max_dimension_px")),
    (("screening", "jpeg_quality"), ("sendico", "tier2_lot_search", "screening_jpeg_quality")),
    (("detailed_analysis", "max_listings_per_run"), ("sendico", "tier2_lot_search", "max_detailed_analyses_per_run")),
    (("detailed_analysis", "max_listings_per_run"), ("vision", "max_listing_analyses_per_run")),
    (("detailed_analysis", "max_overview_images"), ("sendico", "tier2_lot_search", "detailed_max_overview_images")),
    (("detailed_analysis", "max_images_downloaded"), ("vision", "max_images_per_listing")),
    (("detailed_analysis", "max_card_crops_per_listing"), ("vision", "max_local_crops_per_listing")),
    (("detailed_analysis", "max_cards_to_price"), ("vision", "maximum_cards_to_price")),
    (("token_budget", "max_total_tokens_per_run"), ("vision", "max_total_tokens_per_run")),
    (("token_budget", "reserve_per_request"), ("vision", "token_budget_reserve_per_request")),
    (("token_budget", "max_requests_per_run"), ("vision", "max_vision_requests_per_run")),
    (("gemini_request", "max_model_attempts_per_request"), ("vision", "max_model_attempts_per_request")),
    (("gemini_request", "max_retries_per_model"), ("vision", "max_retries_per_model")),
    (("gemini_request", "retry_base_seconds"), ("vision", "retry_base_seconds")),
    (("gemini_request", "retry_max_seconds"), ("vision", "retry_max_seconds")),
    (("gemini_request", "request_timeout_seconds"), ("vision", "request_timeout_seconds")),
    (("gemini_request", "crop_batch_size"), ("vision", "crop_batch_size")),
    (("gemini_request", "request_spacing_seconds"), ("vision", "request_spacing_seconds")),
    (("gemini_request", "max_completion_tokens"), ("vision", "max_completion_tokens")),
    (("image_processing", "local_analysis_max_dimension_px"), ("vision", "local_analysis_max_dimension_px")),
    (("image_processing", "crop_max_dimension_px"), ("vision", "crop_max_dimension_px")),
    (("image_processing", "crop_jpeg_quality"), ("vision", "crop_jpeg_quality")),
    (("image_processing", "crop_padding_percent"), ("vision", "crop_padding_percent")),
    (("image_processing", "minimum_card_area_ratio"), ("vision", "minimum_card_area_ratio")),
    (("image_processing", "maximum_card_area_ratio"), ("vision", "maximum_card_area_ratio")),
    (("image_processing", "minimum_rectangularity"), ("vision", "minimum_rectangularity")),
    (("image_processing", "card_aspect_ratio_min"), ("vision", "card_aspect_ratio_min")),
    (("image_processing", "card_aspect_ratio_max"), ("vision", "card_aspect_ratio_max")),
    (("image_processing", "duplicate_phash_distance"), ("vision", "duplicate_phash_distance")),
    (("image_processing", "contact_sheet_max_dimension_px"), ("vision", "contact_sheet_max_dimension_px")),
    (("image_processing", "contact_sheet_jpeg_quality"), ("vision", "contact_sheet_jpeg_quality")),
)

# data/search_criteria.yaml controls filtering and qualification. Keeping this
# separate from run_limits.yaml means volume and quality can be tuned independently.
_CRITERIA_MAPPINGS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("seller", "minimum_positive_ratings"), ("minimum_seller_positive_ratings",)),
    (("seller", "analyse_unverified_sellers"), ("seller_verification", "analyse_unverified_sellers")),
    (("seller", "alert_provisional_deals"), ("seller_verification", "alert_provisional_deals")),
    (("discovery", "prefilter_watchlist_relevance"), ("sendico", "prefilter_watchlist_relevance")),
    (("discovery", "run_exact_searches"), ("sendico", "tier2_lot_search", "run_standard_watchlist_searches")),
    (("discovery", "allow_query_only_candidates"), ("sendico", "tier2_lot_search", "allow_query_only_candidates")),
    (("lot", "require_strong_lot_evidence"), ("sendico", "tier2_lot_search", "require_strong_lot_evidence")),
    (("lot", "evidence_terms"), ("sendico", "tier2_lot_search", "lot_evidence_terms")),
    (("screening", "minimum_target_probability"), ("sendico", "tier2_lot_search", "screening_confidence_threshold")),
    (("detailed_analysis", "minimum_card_confidence"), ("vision", "minimum_card_confidence")),
    (("detailed_analysis", "minimum_target_confidence"), ("vision", "minimum_target_confidence")),
    (("pricing", "minimum_match_confidence"), ("pricing", "minimum_match_confidence")),
    (("deal", "minimum_saving_percent"), ("minimum_saving_percent",)),
)

_ACTIVE_SEARCH_CRITERIA_SIGNATURE = ""


@dataclass(slots=True)
class AppConfig:
    raw: dict[str, Any]
    root: Path
    run_limits: dict[str, Any] = field(default_factory=dict)
    run_limits_path: Path | None = None
    search_criteria: dict[str, Any] = field(default_factory=dict)
    search_criteria_path: Path | None = None

    @property
    def minimum_seller_positive_ratings(self) -> int:
        return int(self.raw["minimum_seller_positive_ratings"])

    @property
    def minimum_saving_percent(self) -> float:
        return float(self.raw.get("minimum_saving_percent", 0.0))

    @property
    def discord_webhook_url(self) -> str | None:
        return os.getenv("DISCORD_WEBHOOK_URL")

    @property
    def gemini_api_key(self) -> str | None:
        return os.getenv("GEMINI_API_KEY")

    @property
    def groq_api_key(self) -> str | None:
        """Legacy compatibility for older checkouts; production uses Gemini."""
        return os.getenv("GROQ_API_KEY")

    def path(self, relative: str) -> Path:
        return self.root / relative


def _read_yaml_mapping(path: Path, *, label: str) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle) or {}
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a YAML mapping at the top level")
    return value


def _read_path(mapping: dict[str, Any], path: Iterable[str]) -> Any:
    current: Any = mapping
    traversed: list[str] = []
    for part in path:
        traversed.append(part)
        if not isinstance(current, dict) or part not in current:
            raise ValueError(
                "data/run_limits.yaml is missing required setting: "
                + ".".join(traversed)
            )
        current = current[part]
    return current


def _set_path(mapping: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    current = mapping
    for part in path[:-1]:
        child = current.get(part)
        if child is None:
            child = {}
            current[part] = child
        if not isinstance(child, dict):
            raise ValueError(
                f"config.yaml setting {'.'.join(path[:-1])} must be a mapping"
            )
        current = child
    current[path[-1]] = value


def _path_exists(mapping: dict[str, Any], path: tuple[str, ...]) -> bool:
    current: Any = mapping
    for part in path:
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _as_int(limits: dict[str, Any], path: tuple[str, ...], *, minimum: int = 0) -> int:
    value = _read_path(limits, path)
    if isinstance(value, bool):
        raise ValueError(f"{'.'.join(path)} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{'.'.join(path)} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{'.'.join(path)} must be at least {minimum}")
    return parsed


def _as_float(
    limits: dict[str, Any],
    path: tuple[str, ...],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = _read_path(limits, path)
    if isinstance(value, bool):
        raise ValueError(f"{'.'.join(path)} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{'.'.join(path)} must be numeric") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{'.'.join(path)} must be at least {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{'.'.join(path)} must be at most {maximum}")
    return parsed


def validate_run_limits(limits: dict[str, Any]) -> None:
    """Validate relationships without fixing values to one particular profile.

    This allows the user to tune data/run_limits.yaml without editing tests while
    still catching missing, negative or internally contradictory settings.
    """

    if int(limits.get("version", 0)) != 1:
        raise ValueError("data/run_limits.yaml version must be 1")

    # Search collection must remain bounded because zero can make Sendico scroll
    # through the entire result set before local filtering begins.
    results_per_term = _as_int(limits, ("search", "results_per_term"), minimum=1)
    total_listings = _as_int(
        limits, ("search", "total_listings_per_run"), minimum=1
    )
    raw_links = _as_int(limits, ("search", "raw_links_per_term"), minimum=1)
    _as_int(limits, ("search", "page_timeout_ms"), minimum=1000)
    _as_int(limits, ("search", "max_scroll_rounds"), minimum=1)
    _as_int(limits, ("search", "stable_rounds_before_stop"), minimum=1)
    _as_int(limits, ("search", "scroll_pause_ms"), minimum=0)
    if raw_links < results_per_term:
        raise ValueError("search.raw_links_per_term must be >= results_per_term")
    if total_listings < results_per_term:
        raise ValueError("search.total_listings_per_run must be >= results_per_term")

    screening_total = _as_int(limits, ("screening", "max_listings_per_run"))
    focused_limit = _as_int(limits, ("screening", "focused_lot_limit"))
    generic_limit = _as_int(limits, ("screening", "generic_lot_limit"))
    _as_int(limits, ("screening", "max_overview_images"), minimum=1)
    _as_int(limits, ("screening", "max_image_dimension_px"), minimum=100)
    screening_quality = _as_int(
        limits, ("screening", "jpeg_quality"), minimum=1
    )
    if screening_quality > 100:
        raise ValueError("screening.jpeg_quality must be at most 100")
    if screening_total > 0:
        for name, value in (
            ("screening.focused_lot_limit", focused_limit),
            ("screening.generic_lot_limit", generic_limit),
        ):
            if value > screening_total:
                raise ValueError(f"{name} cannot exceed screening.max_listings_per_run")

    detailed_total = _as_int(
        limits, ("detailed_analysis", "max_listings_per_run")
    )
    _as_int(limits, ("detailed_analysis", "max_overview_images"), minimum=1)
    _as_int(limits, ("detailed_analysis", "max_images_downloaded"), minimum=1)
    _as_int(
        limits, ("detailed_analysis", "max_card_crops_per_listing"), minimum=1
    )
    _as_int(limits, ("detailed_analysis", "max_cards_to_price"), minimum=1)
    if detailed_total > 0 and detailed_total > total_listings:
        raise ValueError(
            "detailed_analysis.max_listings_per_run cannot exceed "
            "search.total_listings_per_run"
        )

    max_tokens = _as_int(
        limits, ("token_budget", "max_total_tokens_per_run"), minimum=1000
    )
    reserve = _as_int(limits, ("token_budget", "reserve_per_request"), minimum=0)
    _as_int(limits, ("token_budget", "max_requests_per_run"), minimum=0)
    if reserve >= max_tokens:
        raise ValueError(
            "token_budget.reserve_per_request must be lower than "
            "max_total_tokens_per_run"
        )

    _as_int(limits, ("retry", "max_attempts_per_listing"), minimum=1)
    _as_int(limits, ("test_mode", "max_alerts_per_run"), minimum=1)
    _as_int(
        limits,
        ("gemini_request", "max_model_attempts_per_request"),
        minimum=1,
    )
    _as_int(limits, ("gemini_request", "max_retries_per_model"), minimum=0)
    _as_float(limits, ("gemini_request", "retry_base_seconds"), minimum=0.0)
    retry_max = _as_float(
        limits, ("gemini_request", "retry_max_seconds"), minimum=0.0
    )
    retry_base = float(_read_path(limits, ("gemini_request", "retry_base_seconds")))
    if retry_max < retry_base:
        raise ValueError(
            "gemini_request.retry_max_seconds must be >= retry_base_seconds"
        )
    _as_float(
        limits, ("gemini_request", "request_timeout_seconds"), minimum=10.0
    )
    _as_int(limits, ("gemini_request", "crop_batch_size"), minimum=1)
    _as_float(
        limits, ("gemini_request", "request_spacing_seconds"), minimum=0.0
    )
    _as_int(limits, ("gemini_request", "max_completion_tokens"), minimum=1)

    for key in (
        "local_analysis_max_dimension_px",
        "crop_max_dimension_px",
        "duplicate_phash_distance",
        "contact_sheet_max_dimension_px",
    ):
        _as_int(limits, ("image_processing", key), minimum=0 if "distance" in key else 100)
    for key in ("crop_jpeg_quality", "contact_sheet_jpeg_quality"):
        quality = _as_int(limits, ("image_processing", key), minimum=1)
        if quality > 100:
            raise ValueError(f"image_processing.{key} must be at most 100")
    for key in (
        "crop_padding_percent",
        "minimum_card_area_ratio",
        "maximum_card_area_ratio",
        "minimum_rectangularity",
        "card_aspect_ratio_min",
        "card_aspect_ratio_max",
    ):
        _as_float(limits, ("image_processing", key), minimum=0.0)



def _criteria_value(criteria: dict[str, Any], path: tuple[str, ...]) -> Any:
    current: Any = criteria
    traversed: list[str] = []
    for part in path:
        traversed.append(part)
        if not isinstance(current, dict) or part not in current:
            raise ValueError(
                "data/search_criteria.yaml is missing required setting: "
                + ".".join(traversed)
            )
        current = current[part]
    return current


def _criteria_bool(criteria: dict[str, Any], path: tuple[str, ...]) -> bool:
    value = _criteria_value(criteria, path)
    if not isinstance(value, bool):
        raise ValueError(f"{'.'.join(path)} must be true or false")
    return value


def _criteria_int(
    criteria: dict[str, Any],
    path: tuple[str, ...],
    *,
    minimum: int = 0,
) -> int:
    value = _criteria_value(criteria, path)
    if isinstance(value, bool):
        raise ValueError(f"{'.'.join(path)} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{'.'.join(path)} must be an integer") from exc
    if parsed < minimum:
        raise ValueError(f"{'.'.join(path)} must be at least {minimum}")
    return parsed


def _criteria_float(
    criteria: dict[str, Any],
    path: tuple[str, ...],
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    value = _criteria_value(criteria, path)
    if isinstance(value, bool):
        raise ValueError(f"{'.'.join(path)} must be numeric")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{'.'.join(path)} must be numeric") from exc
    if minimum is not None and parsed < minimum:
        raise ValueError(f"{'.'.join(path)} must be at least {minimum}")
    if maximum is not None and parsed > maximum:
        raise ValueError(f"{'.'.join(path)} must be at most {maximum}")
    return parsed


def validate_search_criteria(criteria: dict[str, Any]) -> None:
    """Validate user-adjustable filtering without enforcing one fixed profile."""

    if int(criteria.get("version", 0)) != 1:
        raise ValueError("data/search_criteria.yaml version must be 1")

    _criteria_int(criteria, ("seller", "minimum_positive_ratings"), minimum=0)
    _criteria_bool(criteria, ("seller", "analyse_unverified_sellers"))
    _criteria_bool(criteria, ("seller", "alert_provisional_deals"))

    _criteria_bool(criteria, ("discovery", "prefilter_watchlist_relevance"))
    _criteria_bool(criteria, ("discovery", "run_exact_searches"))
    _criteria_bool(criteria, ("discovery", "allow_query_only_candidates"))

    require_lot = _criteria_bool(
        criteria, ("lot", "require_strong_lot_evidence")
    )
    evidence_terms = _criteria_value(criteria, ("lot", "evidence_terms"))
    if not isinstance(evidence_terms, list):
        raise ValueError("lot.evidence_terms must be a YAML list")
    cleaned_terms = [str(value).strip() for value in evidence_terms if str(value).strip()]
    if require_lot and not cleaned_terms:
        raise ValueError(
            "lot.evidence_terms must contain at least one term when "
            "lot.require_strong_lot_evidence is true"
        )
    if len(cleaned_terms) != len(set(term.casefold() for term in cleaned_terms)):
        raise ValueError("lot.evidence_terms contains duplicates")

    _criteria_float(
        criteria,
        ("screening", "minimum_target_probability"),
        minimum=0.0,
        maximum=1.0,
    )
    _criteria_float(
        criteria,
        ("detailed_analysis", "minimum_card_confidence"),
        minimum=0.0,
        maximum=1.0,
    )
    _criteria_float(
        criteria,
        ("detailed_analysis", "minimum_target_confidence"),
        minimum=0.0,
        maximum=1.0,
    )
    _criteria_float(
        criteria,
        ("pricing", "minimum_match_confidence"),
        minimum=0.0,
        maximum=1.0,
    )
    _criteria_float(
        criteria,
        ("deal", "minimum_saving_percent"),
        minimum=0.0,
    )


def load_search_criteria(path: str | Path) -> dict[str, Any]:
    criteria_path = Path(path).resolve()
    criteria = _read_yaml_mapping(
        criteria_path, label="data/search_criteria.yaml"
    )
    validate_search_criteria(criteria)
    return criteria


def search_criteria_signature(criteria: dict[str, Any]) -> str:
    serialized = json.dumps(
        criteria,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _assert_no_duplicate_criteria(base: dict[str, Any]) -> None:
    duplicates = sorted(
        ".".join(destination)
        for _, destination in _CRITERIA_MAPPINGS
        if _path_exists(base, destination)
    )
    if duplicates:
        raise ValueError(
            "Search criteria must be edited only in data/search_criteria.yaml. "
            "Remove these duplicate settings from config.yaml: "
            + ", ".join(duplicates)
        )


def _apply_search_criteria(
    base: dict[str, Any],
    criteria: dict[str, Any],
) -> None:
    for source_path, destination in _CRITERIA_MAPPINGS:
        _set_path(base, destination, _criteria_value(criteria, source_path))


def load_run_limits(path: str | Path) -> dict[str, Any]:
    limits_path = Path(path).resolve()
    limits = _read_yaml_mapping(limits_path, label="data/run_limits.yaml")
    validate_run_limits(limits)
    return limits


def _assert_no_duplicate_limits(base: dict[str, Any]) -> None:
    duplicates = sorted(
        ".".join(destination)
        for _, destination in _LIMIT_MAPPINGS
        if _path_exists(base, destination)
    )
    if duplicates:
        raise ValueError(
            "Run limits must be edited only in data/run_limits.yaml. Remove these "
            "duplicate settings from config.yaml: "
            + ", ".join(duplicates)
        )


def _apply_run_limits(base: dict[str, Any], limits: dict[str, Any]) -> None:
    for source, destination in _LIMIT_MAPPINGS:
        _set_path(base, destination, _read_path(limits, source))


def load_config(path: str | Path = "config.yaml") -> AppConfig:
    global _ACTIVE_SEARCH_CRITERIA_SIGNATURE

    config_path = Path(path).resolve()
    raw = _read_yaml_mapping(config_path, label="config.yaml")

    limits: dict[str, Any] = {}
    limits_path: Path | None = None
    limits_reference = str(raw.get("run_limits_file") or "").strip()
    if limits_reference:
        _assert_no_duplicate_limits(raw)
        limits_path = (config_path.parent / limits_reference).resolve()
        if not limits_path.is_file():
            raise FileNotFoundError(
                f"Configured run limits file does not exist: {limits_path}"
            )
        limits = load_run_limits(limits_path)
        _apply_run_limits(raw, limits)

    criteria: dict[str, Any] = {}
    criteria_path: Path | None = None
    criteria_reference = str(raw.get("search_criteria_file") or "").strip()
    if criteria_reference:
        _assert_no_duplicate_criteria(raw)
        criteria_path = (config_path.parent / criteria_reference).resolve()
        if not criteria_path.is_file():
            raise FileNotFoundError(
                f"Configured search criteria file does not exist: {criteria_path}"
            )
        criteria = load_search_criteria(criteria_path)
        _apply_search_criteria(raw, criteria)
        _ACTIVE_SEARCH_CRITERIA_SIGNATURE = search_criteria_signature(criteria)
    else:
        _ACTIVE_SEARCH_CRITERIA_SIGNATURE = ""

    return AppConfig(
        raw=raw,
        root=config_path.parent,
        run_limits=limits,
        run_limits_path=limits_path,
        search_criteria=criteria,
        search_criteria_path=criteria_path,
    )


def load_watchlist(config: AppConfig) -> list[WatchCard]:
    watchlist_reference = str(
        config.raw.get("watchlist_file") or "data/watchlist.yaml"
    ).strip()
    path = config.path(watchlist_reference)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    cards = [
        WatchCard(**item)
        for item in data.get("cards", [])
        if item.get("active", True)
    ]
    duplicate_ids = sorted(
        card_id
        for card_id in {card.id for card in cards}
        if sum(card.id == card_id for card in cards) > 1
    )
    if duplicate_ids:
        raise ValueError(
            "Active watchlist ids must be unique: " + ", ".join(duplicate_ids)
        )
    if not cards:
        raise ValueError(f"{watchlist_reference} has no active watchlist entries")
    return cards


def validate_watchlist_for_run(targets: list[WatchCard]) -> None:
    """Fail before Sendico opens when the user-controlled watchlist is unsafe."""

    for target in targets:
        searches = target.active_searches
        if not searches:
            raise ValueError(
                f"Active watchlist entry {target.id!r} has no active searches"
            )
        if len(searches) > 4:
            raise ValueError(
                f"Active watchlist entry {target.id!r} has {len(searches)} active "
                "searches; the maximum is 4"
            )
        folded = [search.term.casefold() for search in searches]
        if len(folded) != len(set(folded)):
            raise ValueError(
                f"Active watchlist entry {target.id!r} contains duplicate search terms"
            )
        if target.match_mode == "exact_card" and not target.pricecharting_url:
            raise ValueError(
                f"Exact-card watchlist entry {target.id!r} requires pricecharting_url"
            )


def watchlist_search_terms(targets: list[WatchCard]) -> list[str]:
    """Return only user-entered active ``exact`` searches; never generate terms."""

    return _unique_terms(
        [
            search.term
            for target in targets
            for search in target.active_searches
            if search.mode == "exact"
        ]
    )


def _unique_terms(values: list[str]) -> list[str]:
    return list(dict.fromkeys(term.strip() for term in values if term.strip()))


def watchlist_era_lot_search_terms(targets: list[WatchCard]) -> list[str]:
    """Return user-entered active focused-lot searches."""

    return _unique_terms(
        [
            search.term
            for target in targets
            for search in target.active_searches
            if search.mode == "focused_lot"
        ]
    )


def watchlist_generic_lot_search_terms(targets: list[WatchCard]) -> list[str]:
    """Return user-entered active generic-lot searches."""

    return _unique_terms(
        [
            search.term
            for target in targets
            for search in target.active_searches
            if search.mode == "generic_lot"
        ]
    )


def watchlist_lot_search_terms(targets: list[WatchCard]) -> list[str]:
    return _unique_terms(
        [
            *watchlist_era_lot_search_terms(targets),
            *watchlist_generic_lot_search_terms(targets),
        ]
    )


def watchlist_signature(targets: list[WatchCard]) -> str:
    """Hash active targets, searches and criteria so edits permit a fresh rescan."""

    payload = {
        "targets": [
            asdict(target)
            for target in sorted(targets, key=lambda item: item.id)
        ],
        "search_criteria_signature": _ACTIVE_SEARCH_CRITERIA_SIGNATURE,
    }
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
