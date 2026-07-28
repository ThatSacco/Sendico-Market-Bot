from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Callable

import yaml

ROOT_FILES = {
    "config.yaml",
    "pyproject.toml",
    "src",
    "data",
}


def fail(message: str) -> "NoReturn":
    raise RuntimeError(message)


def locate_root(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if all((candidate / name).exists() for name in ROOT_FILES):
            return candidate
    fail(
        "Could not locate the Sendico-Market-Bot repository root. Run this script "
        "from the repository root or extract the package there."
    )


def backup_files(root: Path, relative_paths: list[str]) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_root = root / ".update_backups" / f"v5-{stamp}"
    for relative in relative_paths:
        source = root / relative
        if source.exists():
            target = backup_root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    return backup_root


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        fail(f"Could not safely update {label}: expected one exact block, found {count}.")
    return text.replace(old, new, 1)


def replace_regex(
    text: str,
    pattern: str,
    replacement: str,
    label: str,
    *,
    flags: int = re.DOTALL,
) -> str:
    compiled = re.compile(pattern, flags)
    matches = list(compiled.finditer(text))
    if len(matches) != 1:
        fail(f"Could not safely update {label}: expected one matching block, found {len(matches)}.")
    return compiled.sub(lambda _match: replacement, text, count=1)


def migrate_watchlist(path: Path) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cards = data.get("cards") or []
    if not isinstance(cards, list) or not cards:
        fail("data/watchlist.yaml must contain a non-empty cards list")

    changed = False
    for card in cards:
        if not isinstance(card, dict):
            fail("Every watchlist card must be a YAML mapping")
        if "searches" in card:
            searches = card.get("searches") or []
        else:
            changed = True
            exact = [str(value).strip() for value in card.get("search_terms", []) if str(value).strip()]
            focused = [
                str(value).strip()
                for key in ("era_lot_search_terms", "lot_search_terms")
                for value in card.get(key, [])
                if str(value).strip()
            ]
            generic = [
                str(value).strip()
                for value in card.get("generic_lot_search_terms", [])
                if str(value).strip()
            ]

            set_code = str(card.get("set_code") or "").casefold()
            set_name = str(card.get("set_name") or "").casefold()

            def focus_score(term: str) -> tuple[int, int]:
                folded = term.casefold()
                score = int(bool(set_code and set_code in folded)) * 2
                score += int(bool(set_name and set_name in folded))
                score += int("まとめ売り" in term or "セット販売" in term)
                return (-score, len(term))

            focused = sorted(dict.fromkeys(focused), key=focus_score)
            ordered: list[dict[str, object]] = []
            ordered.extend({"term": term, "mode": "focused_lot", "active": True} for term in focused)
            ordered.extend({"term": term, "mode": "exact", "active": True} for term in exact)
            ordered.extend({"term": term, "mode": "generic_lot", "active": False} for term in generic)
            searches = ordered[:4]
            card["searches"] = searches

        for legacy in (
            "search_terms",
            "lot_search_terms",
            "era_lot_search_terms",
            "generic_lot_search_terms",
        ):
            if legacy in card:
                card.pop(legacy, None)
                changed = True

        active_searches = [
            item for item in searches
            if isinstance(item, dict) and item.get("active", True)
        ]
        if card.get("active", True) and not active_searches:
            fail(f"Active watchlist card {card.get('id')!r} has no active searches")
        if len(active_searches) > 4:
            fail(f"Active watchlist card {card.get('id')!r} has more than four active searches")

    if changed:
        header = """# WATCHLIST-ONLY SEARCH CONTROL\n#\n# Edit this file to change cards, PriceCharting references and Sendico terms.\n# Search modes: exact, focused_lot, generic_lot.\n# Each active card must have between one and four active searches.\n"""
        rendered = yaml.safe_dump(
            {"cards": cards},
            allow_unicode=True,
            sort_keys=False,
            width=100,
        )
        path.write_text(header + rendered, encoding="utf-8")


def patch_main(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    if "validate_watchlist_for_run" not in text:
        text = replace_once(
            text,
            "    load_watchlist,\n",
            "    load_watchlist,\n    validate_watchlist_for_run,\n",
            "main.py config import",
        )

    if "normalize_card_number" not in "\n".join(text.splitlines()[:50]):
        text = replace_once(
            text,
            "from .models import DealAssessment, SendicoListing\n",
            "from .models import DealAssessment, SendicoListing, normalize_card_number\n",
            "main.py model import",
        )

    if "validate_watchlist_for_run(targets)" not in text:
        text = replace_once(
            text,
            "    targets = load_watchlist(config)\n",
            "    targets = load_watchlist(config)\n    validate_watchlist_for_run(targets)\n",
            "main.py watchlist validation",
        )

    text = re.sub(
        r"scan_signature = watchlist_signature\(targets\)",
        'scan_signature = "watchlist-two-pass-token-budget-v5:" + watchlist_signature(targets)',
        text,
        count=1,
    )

    candidate_block = r'''def _candidate_relevance_score(
    listing: SendicoListing,
    targets,
) -> int:
    """Rank title-confirmed lots ahead of likely single-card listings."""

    title = str(listing.title or "")
    result_text = str(listing.raw_text or "")[:700]
    description = _extract_seller_description(
        str(listing.description or listing.raw_text or ""),
        title,
    )[:500]
    haystack = _compact_search(" ".join([title, result_text, description]))
    if not haystack:
        return 0

    title_lot = _contains_lot_marker(_compact_search(title))
    description_lot = _contains_lot_marker(_compact_search(description))
    title_numbers = _number_tokens(title)
    all_numbers = _number_tokens(" ".join([title, result_text]))
    best = 0

    for target in targets:
        score = 0
        names = [*target.english_names, *target.japanese_names]
        name_match = any(
            compact_name and compact_name in haystack
            for compact_name in (_compact_search(name) for name in names)
        )
        if name_match:
            score += 60

        target_number = normalize_card_number(target.card_number)
        number_match = bool(target_number and target_number in all_numbers)
        if target.match_mode == "exact_card" and number_match:
            score += 100

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
            score += 25

        if title_lot:
            score += 90
        elif description_lot:
            score += 25

        # A title naming one printed number without lot wording is usually a
        # single-card listing and should not consume an early detailed slot.
        if title_numbers and not title_lot:
            score -= 90
        if name_match and number_match and not title_lot:
            score -= 60

        best = max(best, score)

    if best <= 0 and title_lot:
        return 10
    return max(0, best)
'''

    helper_prelude = r'''def _number_tokens(value: str | None) -> set[str]:
    normalized = unicodedata.normalize("NFKC", str(value or ""))
    return {
        normalize_card_number(match.group(0))
        for match in re.finditer(r"\b\d{1,3}\s*/\s*\d{1,3}\b", normalized)
    }


def _extract_seller_description(body_text: str, title: str = "") -> str:
    """Isolate seller-authored description text from Sendico page boilerplate."""

    lines = [line.strip() for line in str(body_text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    starts = {"item description", "description", "商品説明", "商品の説明"}
    ends = {
        "seller", "出品者", "shipping", "配送", "comments", "コメント",
        "recommended", "おすすめ", "related items", "商品の情報", "category",
    }
    start: int | None = None
    for index, line in enumerate(lines):
        folded = line.casefold().rstrip(":：")
        if folded in starts:
            start = index + 1
            break
    title_folded = str(title or "").strip().casefold()
    if start is None and title_folded:
        for index, line in enumerate(lines):
            if line.casefold() == title_folded:
                start = index + 1
                break
    if start is None:
        return ""

    captured: list[str] = []
    for line in lines[start:]:
        folded = line.casefold().rstrip(":：")
        if folded in ends:
            break
        if title_folded and line.casefold() == title_folded:
            continue
        captured.append(line)
        if sum(len(item) for item in captured) >= 3000:
            break
    return "\n".join(captured).strip()[:3000]
'''

    lot_block = r'''def _has_strong_lot_evidence(
    listing: SendicoListing,
    configured_terms: list[str] | tuple[str, ...] | None = None,
) -> bool:
    """Use only title and isolated seller description for lot evidence."""

    description = _extract_seller_description(
        str(listing.description or listing.raw_text or ""),
        str(listing.title or ""),
    )
    haystack = " ".join([str(listing.title or ""), description[:2000]])
    normalized = unicodedata.normalize("NFKC", haystack).casefold()

    explicit_single = bool(
        re.search(r"(?:カード\s*)?1\s*枚|one\s+card|single\s+card", normalized)
    )
    explicit_multiple = bool(
        re.search(r"(?:^|\D)(?:[2-9]|[1-9]\d{1,3})\s*(?:枚|cards?)(?:\D|$)", normalized)
    )
    if explicit_single and not explicit_multiple:
        return False

    default_terms = (
        "まとめ売り", "大量", "引退品", "引退", "詰め合わせ", "セット販売",
        "lot", "bundle", "collection", "bulk", "assorted",
    )
    terms = [str(term).strip() for term in (configured_terms or default_terms) if str(term).strip()]
    compact = _compact_search(haystack)
    if any(_compact_search(term) in compact for term in terms):
        return True
    return explicit_multiple
'''

    # Insert helper functions before the candidate scorer, then replace both
    # candidate scoring and lot-evidence functions with the consolidated logic.
    if "def _number_tokens(" not in text:
        text = text.replace("def _candidate_relevance_score(\n", helper_prelude + "\n\ndef _candidate_relevance_score(\n", 1)

    text = replace_regex(
        text,
        r"def _candidate_relevance_score\(.*?\n(?=def _is_tier2_only)",
        candidate_block + "\n",
        "main.py candidate relevance",
    )

    text = replace_regex(
        text,
        r"def _has_strong_lot_evidence\(.*?\n(?=def _rank_candidate_pool)",
        lot_block + "\n",
        "main.py lot evidence",
    )

    # Ensure the direct Gemini constructor receives the hard token budget.
    constructor_old = '''        max_requests_per_run=int(\n            vision_cfg.get("max_vision_requests_per_run", 150)\n        ),\n    )'''
    constructor_new = '''        max_requests_per_run=int(\n            vision_cfg.get("max_vision_requests_per_run", 80)\n        ),\n        max_total_tokens_per_run=int(\n            vision_cfg.get("max_total_tokens_per_run", 125000)\n        ),\n        token_budget_reserve_per_request=int(\n            vision_cfg.get("token_budget_reserve_per_request", 5000)\n        ),\n    )'''
    if "max_total_tokens_per_run=int(" not in text:
        text = replace_once(text, constructor_old, constructor_new, "main.py Gemini token args")

    # Correct the global listing cap summary so remaining Tier 2 candidates are held.
    cap_old = '''                        stop_reason = (\n                            "Stopped at the configured Gemini detailed-analysis cap "\n                            f"of {max_vision_listings}; remaining eligible listings "\n                            "will be considered on the next run."\n                        )\n                        LOGGER.info(stop_reason)\n                        break'''
    cap_new = '''                        remaining_tier2 = sum(\n                            1\n                            for remaining in listings_to_process[listing_index:]\n                            if _is_tier2_only(\n                                candidate_sources.get(remaining.code, set())\n                            )\n                        )\n                        tier2_held_count += remaining_tier2\n                        stop_reason = (\n                            "Stopped at the configured Gemini detailed-analysis cap "\n                            f"of {max_vision_listings}; {remaining_tier2} remaining "\n                            "eligible Tier 2 listing(s) will be considered on the next run."\n                        )\n                        LOGGER.info(stop_reason)\n                        break'''
    if "remaining_tier2 = sum(" not in text:
        text = replace_once(text, cap_old, cap_new, "main.py held count")

    # Detailed analysis must confirm a real lot and the target before any pricing.
    gate_marker = "                    raw_eligible = [\n"
    if "Detailed Gemini confirmed a single-card listing" not in text:
        gate = '''                    if tier2_only and str(vision_result.listing_type).lower() == "single":\n                        tier2_non_lot_filtered += 1\n                        outcome = "Detailed Gemini confirmed a single-card listing"\n                        LOGGER.info("Skipping %s: %s", listing.code, outcome)\n                        state.update(listing, False, outcome, scan_signature)\n                        continue\n\n                    if not vision_result.target_present:\n                        assessment = assess_deal(\n                            listing=listing,\n                            vision=vision_result,\n                            priced_cards=[],\n                            fx=fx,\n                            fee_config=config.raw["sendico_fee"],\n                            minimum_seller_ratings=config.minimum_seller_positive_ratings,\n                            minimum_target_confidence=float(\n                                vision_cfg["minimum_target_confidence"]\n                            ),\n                        )\n                        assessments.append(assessment)\n                        outcome = "no watchlist target was confirmed; pricing skipped"\n                        LOGGER.info("Skipping pricing for %s: %s", listing.code, outcome)\n                        state.update(listing, False, outcome, scan_signature)\n                        continue\n\n'''
        text = replace_once(text, gate_marker, gate + gate_marker, "main.py target-before-pricing gate")

    budget_old = '                except VisionRunBudgetReached as exc:\n                    stop_reason = str(exc)\n                    LOGGER.info(\n                        "Stopping before another Gemini request would exceed the "\n                        "configured per-run budget: %s",\n                        exc,\n                    )\n                    break'
    budget_new = '                except VisionRunBudgetReached as exc:\n                    remaining_tier2 = sum(\n                        1\n                        for remaining in listings_to_process[listing_index:]\n                        if _is_tier2_only(\n                            candidate_sources.get(remaining.code, set())\n                        )\n                    )\n                    tier2_held_count += remaining_tier2\n                    stop_reason = (\n                        f"{exc} {remaining_tier2} remaining eligible Tier 2 "\n                        "listing(s) will be considered on the next run."\n                    )\n                    LOGGER.info(\n                        "Stopping before another Gemini request would exceed the "\n                        "configured per-run budget: %s",\n                        stop_reason,\n                    )\n                    break'
    if "remaining eligible Tier 2" not in text[text.find("except VisionRunBudgetReached"):text.find("except VisionRateLimitError")]:
        text = replace_once(
            text, budget_old, budget_new, "main.py token-budget held count"
        )

    path.write_text(text, encoding="utf-8")


def patch_gemini(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    if "max_total_tokens_per_run: int" not in text:
        text = replace_once(
            text,
            "        max_requests_per_run: int = 150,\n    ) -> None:\n",
            "        max_requests_per_run: int = 150,\n"
            "        max_total_tokens_per_run: int = 125000,\n"
            "        token_budget_reserve_per_request: int = 5000,\n"
            "    ) -> None:\n",
            "gemini_vision.py token signature",
        )

    if "self.max_total_tokens_per_run" not in text:
        text = replace_once(
            text,
            "        self.total_tokens = 0\n",
            "        self.total_tokens = 0\n"
            "        self.max_total_tokens_per_run = max(0, int(max_total_tokens_per_run))\n"
            "        self.token_budget_reserve_per_request = max(0, int(token_budget_reserve_per_request))\n",
            "gemini_vision.py token fields",
        )

    budget_check = '''        if (\n            self.max_total_tokens_per_run > 0\n            and self.total_tokens + self.token_budget_reserve_per_request\n            > self.max_total_tokens_per_run\n        ):\n            raise VisionRunBudgetReached(\n                "Gemini token budget reached for this scan: "\n                f"{self.total_tokens:,} tokens used; "\n                f"{self.token_budget_reserve_per_request:,} reserved for the next request; "\n                f"limit {self.max_total_tokens_per_run:,}."\n            )\n'''
    if "Gemini token budget reached for this scan" not in text:
        marker = "    def _post_model_request(\n"
        index = text.find(marker)
        if index < 0:
            fail("Could not locate Gemini _post_model_request")
        body_start = text.find("        if (\n", index)
        if body_start < 0:
            fail("Could not locate Gemini request-budget check")
        text = text[:body_start] + budget_check + text[body_start:]

    install = '''\n\n# Install the Tier 2 helpers when this module is imported. The workflow now runs\n# pokemon_deal_bot.main directly; no external runtime wrapper is required.\nfrom .tier2_vision import install_on as _install_tier2_vision\n\n_install_tier2_vision(GeminiLotVisionAnalyzer)\ndel _install_tier2_vision\n'''
    if "_install_tier2_vision(GeminiLotVisionAnalyzer)" not in text:
        text = text.rstrip() + install

    path.write_text(text, encoding="utf-8")


def patch_sendico(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    bounded = '''    async def _scroll_search_results(self, page: Page) -> None:\n        """Load only the bounded raw-link pool required for this search."""\n\n        result_limit = max(1, int(self.config.get("max_results_per_search", 25)))\n        configured_raw_limit = int(\n            self.config.get("max_raw_links_per_search", 0) or 0\n        )\n        raw_limit = configured_raw_limit or min(60, max(30, result_limit * 2))\n        maximum_rounds = max(1, int(self.config.get("maximum_scroll_rounds", 6)))\n        stable_required = max(\n            1, int(self.config.get("stable_scroll_rounds_before_stop", 2))\n        )\n        pause_ms = max(250, int(self.config.get("scroll_pause_ms", 1200)))\n\n        previous_count = -1\n        stable_rounds = 0\n        for round_number in range(maximum_rounds + 1):\n            current_count = await page.locator(\n                'a[href*="/shop/mercari/catalog/"]'\n            ).evaluate_all(\n                """\n                (anchors) => new Set(\n                  anchors.map((a) => a.href || '')\n                    .filter((href) => href && !href.includes('/categories/'))\n                ).size\n                """\n            )\n            LOGGER.info(\n                "Sendico bounded load round %d: %d unique links (stop at %d)",\n                round_number,\n                current_count,\n                raw_limit,\n            )\n            if current_count >= raw_limit:\n                LOGGER.info("Reached raw-link search limit of %d", raw_limit)\n                return\n            if current_count <= previous_count:\n                stable_rounds += 1\n            else:\n                stable_rounds = 0\n            if stable_rounds >= stable_required:\n                LOGGER.info(\n                    "Sendico results stabilised at %d unique links", current_count\n                )\n                return\n            if round_number >= maximum_rounds:\n                LOGGER.info(\n                    "Reached Sendico scroll limit of %d rounds", maximum_rounds\n                )\n                return\n            previous_count = current_count\n            load_more = page.get_by_role(\n                "button",\n                name=re.compile(\n                    r"load more|show more|more results|もっと見る", re.IGNORECASE\n                ),\n            ).first\n            try:\n                if await load_more.count() and await load_more.is_visible():\n                    await load_more.click()\n            except Exception:  # noqa: BLE001\n                pass\n            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")\n            await page.wait_for_timeout(pause_ms)\n\n'''
    text = replace_regex(
        text,
        r"    async def _scroll_search_results\(.*?\n(?=    async def hydrate)",
        bounded,
        "sendico.py bounded scrolling",
    )
    path.write_text(text, encoding="utf-8")


def patch_vision(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "from .models import IdentifiedCard, SendicoListing, VisionResult, WatchCard\n",
        "from .models import (\n"
        "    IdentifiedCard,\n"
        "    SendicoListing,\n"
        "    VisionResult,\n"
        "    WatchCard,\n"
        "    normalize_card_number,\n"
        ")\n",
        "vision.py model import",
    ) if "normalize_card_number" not in text.split("def _number", 1)[0] else text

    text = replace_regex(
        text,
        r"def _number\(value: str \| None\) -> str:\n    .*?\n(?=def _name_matches)",
        "def _number(value: str | None) -> str:\n    return normalize_card_number(value)\n\n",
        "vision.py card-number normalisation",
    )
    path.write_text(text, encoding="utf-8")


def patch_tests(root: Path) -> None:
    config_test = root / "tests/test_config.py"
    if config_test.exists():
        text = config_test.read_text(encoding="utf-8")
        replacements = {
            'assert sendico["max_results_per_search"] == 15': 'assert sendico["max_results_per_search"] == 25',
            'assert sendico["max_listings_per_run"] == 30': 'assert sendico["max_listings_per_run"] == 50',
            'assert sendico["maximum_scroll_rounds"] == 5': 'assert sendico["maximum_scroll_rounds"] == 6',
            'assert tier2["max_screenings_per_run"] == 15': 'assert tier2["max_screenings_per_run"] == 40',
            'assert tier2["max_detailed_analyses_per_run"] == 3': 'assert tier2["max_detailed_analyses_per_run"] == 12',
            'assert tier2["detailed_max_overview_images"] == 8': 'assert tier2["detailed_max_overview_images"] == 10',
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        config_test.write_text(text, encoding="utf-8")

    integrity = root / "tests/test_repository_integrity.py"
    if integrity.exists():
        text = integrity.read_text(encoding="utf-8")
        replacements = {
            'assert "schedule:" not in workflow': 'assert "schedule:" in workflow',
            'python -m pokemon_deal_bot.updated_main --config config.yaml': 'python -m pokemon_deal_bot.main --config config.yaml',
            'assert sendico["max_results_per_search"] == 15': 'assert sendico["max_results_per_search"] == 25',
            'assert sendico["max_raw_links_per_search"] == 40': 'assert sendico["max_raw_links_per_search"] == 60',
            'assert tier2["max_screenings_per_run"] == 15': 'assert tier2["max_screenings_per_run"] == 40',
            'assert tier2["max_detailed_analyses_per_run"] == 3': 'assert tier2["max_detailed_analyses_per_run"] == 12',
            'assert vision["max_listing_analyses_per_run"] == 3': 'assert vision["max_listing_analyses_per_run"] == 12',
            'assert vision["max_vision_requests_per_run"] == 30': 'assert vision["max_vision_requests_per_run"] == 80',
            'assert config["vision"]["max_listing_analyses_per_run"] == 100': 'assert config["vision"]["max_listing_analyses_per_run"] == 12',
            'assert config["vision"]["max_vision_requests_per_run"] == 150': 'assert config["vision"]["max_vision_requests_per_run"] == 80',
        }
        for old, new in replacements.items():
            text = text.replace(old, new)
        if "max_total_tokens_per_run" not in text:
            anchors = [
                '    assert vision["max_vision_requests_per_run"] == 80\n',
                '    assert config["vision"]["max_vision_requests_per_run"] == 80\n',
            ]
            for anchor in anchors:
                if anchor in text:
                    text = text.replace(
                        anchor,
                        anchor + '    assert vision["max_total_tokens_per_run"] == 125000\n'
                        if 'assert vision[' in anchor
                        else anchor + '    assert config["vision"]["max_total_tokens_per_run"] == 125000\n',
                        1,
                    )
                    break
        integrity.write_text(text, encoding="utf-8")


def copy_payload(payload: Path, root: Path) -> None:
    for source in payload.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(payload)
        if relative == Path("data/watchlist.yaml"):
            continue
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def run_checks(root: Path) -> None:
    commands = [
        [sys.executable, "-m", "compileall", "-q", "src"],
        [sys.executable, "-m", "pytest", "-q"],
    ]
    for command in commands:
        result = subprocess.run(command, cwd=root, check=False)
        if result.returncode != 0:
            fail(f"Validation command failed: {' '.join(command)}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the Sendico watchlist-only two-pass 125k-token update"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()

    root = locate_root(args.root)
    package_root = Path(__file__).resolve().parent
    payload = package_root / "payload"

    touched = [
        "config.yaml",
        "data/watchlist.yaml",
        ".github/workflows/scan.yml",
        "src/pokemon_deal_bot/__init__.py",
        "src/pokemon_deal_bot/models.py",
        "src/pokemon_deal_bot/config.py",
        "src/pokemon_deal_bot/tier2_vision.py",
        "src/pokemon_deal_bot/updated_main.py",
        "src/pokemon_deal_bot/main.py",
        "src/pokemon_deal_bot/gemini_vision.py",
        "src/pokemon_deal_bot/sendico.py",
        "src/pokemon_deal_bot/vision.py",
        "tests/test_config.py",
        "tests/test_repository_integrity.py",
    ]

    if args.check_only:
        print(f"Repository root: {root}")
        for relative in touched:
            print(f"{'OK' if (root / relative).exists() else 'MISSING'} {relative}")
        return 0

    backup_root = backup_files(root, touched)
    copy_payload(payload, root)
    migrate_watchlist(root / "data/watchlist.yaml")
    patch_main(root / "src/pokemon_deal_bot/main.py")
    patch_gemini(root / "src/pokemon_deal_bot/gemini_vision.py")
    patch_sendico(root / "src/pokemon_deal_bot/sendico.py")
    patch_vision(root / "src/pokemon_deal_bot/vision.py")
    patch_tests(root)

    if not args.skip_tests:
        run_checks(root)

    print("Sendico v5 update applied successfully.")
    print(f"Backups: {backup_root}")
    print("Run target: approximately 100,000-150,000 Gemini tokens (125,000 configured).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
