
Yesterday 4:28 PM

Pasted text(2).txt
Document
I think we need to refine the search abit more, there were a large number of results. I had used 350,000 tokens and show no pings to discord at all. It was still going.

Seems very high compared to before. Can we optimise to reduce the search numbers? I think we should have a user input where before a search is run the user need to put in the search terms they want to use and a link to price charting for the card they are looking for.

Yesterday 6:21 PM
Can you review the GitHub code and explain what the possible cause is for no listings being returned, only the attached.

https://github.com/ThatSacco/Sendico-Market-Bot/tree/main

Yesterday 9:04 PM

Pasted text(3).txt
Document
See discord output and code


Pasted text(4).txt
Document
See error after update

Today 9:18 AM
image(19).png
See discord output, what variables do I need to adjust to increase the limit or can we remove the limits and I will edit the search description in the watchlist file to be more concisce


Pasted text(5).txt
Document
I wanted to reset the seen file and got this



image(20).png

Worked for 2m 36s
The screenshot shows zero marketplace listings were discovered, so the run stopped before local filtering, Gemini screening, detailed analysis, or token limits were relevant.

In the runtime, discovered_count is calculated immediately after scanner.search() returns its product links and before the candidate prefilter is applied. Therefore, changing criteria cannot fix a zero-discovery run; the active terms in data/watchlist.yaml need to return Sendico links first. 

Central search-criteria update
Download Sendico Market Bot – Central Search Criteria v7

Download the SHA-256 checksum

547b67ab41d04e5bc28d4c4c45a3c460e76a0ecb991dee6f79a694b86e59048e
This creates three separate user-control files:

data/watchlist.yaml         What cards and search terms to use
data/run_limits.yaml        How much work and token usage to allow
data/search_criteria.yaml    How strict or loose the filtering should be
New criteria file
search_criteria.yaml

The supplied balanced profile is:

seller:
  minimum_positive_ratings: 301
  analyse_unverified_sellers: true
  alert_provisional_deals: true

discovery:
  prefilter_watchlist_relevance: true
  run_exact_searches: true
  allow_query_only_candidates: true

lot:
  require_strong_lot_evidence: true
  evidence_terms:
    - "まとめ売り"
    - "大量"
    - "引退品"
    - "引退"
    - "詰め合わせ"
    - "セット販売"
    - "セット"
    - "lot"
    - "bundle"
    - "collection"
    - "bulk"
    - "assorted"

screening:
  minimum_target_probability: 0.30

detailed_analysis:
  minimum_card_confidence: 0.90
  minimum_target_confidence: 0.80

pricing:
  minimum_match_confidence: 0.90

deal:
  minimum_saving_percent: 0.0
Controls that increase listings pushed through
The most relevant values are:

discovery:
  prefilter_watchlist_relevance: true
  allow_query_only_candidates: true

lot:
  require_strong_lot_evidence: true

screening:
  minimum_target_probability: 0.30
For a temporary loose diagnostic run:

discovery:
  prefilter_watchlist_relevance: false
  allow_query_only_candidates: true

lot:
  require_strong_lot_evidence: false

screening:
  minimum_target_probability: 0.20

detailed_analysis:
  minimum_card_confidence: 0.85
  minimum_target_confidence: 0.70
That profile will allow substantially more listings into Gemini, including more unrelated results.

Important distinction for the zero-result screenshot
These criteria only affect listings after Sendico has returned them.

For Ampharos EX, keep active focused searches broad enough to return actual listings:

searches:
  - term: "XY7 まとめ売り"
    mode: focused_lot
    active: true

  - term: "バンデットリング まとめ売り"
    mode: focused_lot
    active: true

  - term: "デンリュウEX まとめ売り"
    mode: focused_lot
    active: true
An exact search such as:

- term: "デンリュウEX 027/081"
  mode: exact
  active: false
can remain inactive initially. Sendico may have no listing using that precise wording even where the card appears inside a lot.

The current search pipeline obtains its terms from watchlist entries and constructs the search plan before calling the Sendico scanner. 

Updated central run limits
run_limits.yaml

The supplied settings are:

search:
  results_per_term: 50
  total_listings_per_run: 100
  raw_links_per_term: 80
  max_scroll_rounds: 8

screening:
  max_listings_per_run: 100
  focused_lot_limit: 100
  generic_lot_limit: 10

detailed_analysis:
  max_listings_per_run: 60

token_budget:
  max_total_tokens_per_run: 150000
  reserve_per_request: 5000
  max_requests_per_run: 0
Confidence thresholds have been removed from run_limits.yaml; they now belong only in search_criteria.yaml.

Criteria changes automatically permit rescanning
The replacement configuration loader includes the complete criteria file in the scan signature. Changing a threshold or filter therefore gives listings a new scan signature, allowing them to be reconsidered without repeatedly emptying data/seen.json.

GitHub-only file updates
No local scripts or PowerShell are included.

Add or replace these files directly through GitHub:

config.yaml

run_limits.yaml

search_criteria.yaml

config.py

test_config.py

test_repository_integrity.py

test_v5_token_pipeline.py

SEARCH_CRITERIA_GUIDE.md

GITHUB_FILE_UPLOAD_INSTRUCTIONS.md

Commit all files together using:

Centralise search criteria and qualification settings
Do not overwrite your existing data/watchlist.yaml; retain your current card details and adjust its active search terms separately.

The replacement configuration module passed Python compilation, YAML validation, central-criteria loading, mapping validation, and a functional smoke test. The full repository test workflow remains the final check after all files are committed together. 


see output form github

Run pytest -q
...........F.F.......................................................... [ 72%]
...........................                                              [100%]
=================================== FAILURES ===================================
_____________ test_repository_watchlist_is_the_only_search_source ______________

    def test_repository_watchlist_is_the_only_search_source():
        root = Path(__file__).resolve().parents[1]
>       data = yaml.safe_load((root / "data/watchlist.yaml").read_text(encoding="utf-8"))
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_config.py:170: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/yaml/__init__.py:125: in safe_load
    return load(stream, SafeLoader)
           ^^^^^^^^^^^^^^^^^^^^^^^^
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/yaml/__init__.py:81: in load
    return loader.get_single_data()
           ^^^^^^^^^^^^^^^^^^^^^^^^
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/yaml/constructor.py:49: in get_single_data
    node = self.get_single_node()
           ^^^^^^^^^^^^^^^^^^^^^^
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/yaml/composer.py:36: in get_single_node
    document = self.compose_document()
               ^^^^^^^^^^^^^^^^^^^^^^^
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/yaml/composer.py:55: in compose_document
    node = self.compose_node(None, None)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/yaml/composer.py:84: in compose_node
    node = self.compose_mapping_node(anchor)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/yaml/composer.py:127: in compose_mapping_node
    while not self.check_event(MappingEndEvent):
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/yaml/parser.py:98: in check_event
    self.current_event = self.state()
                         ^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <yaml.loader.SafeLoader object at 0x7f52bc610dd0>

    def parse_block_mapping_key(self):
        if self.check_token(KeyToken):
            token = self.get_token()
            if not self.check_token(KeyToken, ValueToken, BlockEndToken):
                self.states.append(self.parse_block_mapping_value)
                return self.parse_block_node_or_indentless_sequence()
            else:
                self.state = self.parse_block_mapping_value
                return self.process_empty_scalar(token.end_mark)
        if not self.check_token(BlockEndToken):
            token = self.peek_token()
>           raise ParserError("while parsing a block mapping", self.marks[-1],
                    "expected <block end>, but found %r" % token.id, token.start_mark)
E           yaml.parser.ParserError: while parsing a block mapping
E             in "<unicode string>", line 15, column 1:
E               cards:
E               ^
E           expected <block end>, but found '-'
E             in "<unicode string>", line 42, column 1:
E               - id: victini_sv11b_097
E               ^

/opt/hostedtoolcache/Python/3.12.13/x64/lib/python3.12/site-packages/yaml/parser.py:438: ParserError
_________ test_changing_central_limit_updates_all_legacy_runtime_paths _________

tmp_path = PosixPath('/tmp/pytest-of-runner/pytest-0/test_changing_central_limit_up0')

    def test_changing_central_limit_updates_all_legacy_runtime_paths(tmp_path: Path):
        root = Path(__file__).resolve().parents[1]
        base = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
        limits = yaml.safe_load((root / "data/run_limits.yaml").read_text(encoding="utf-8"))
        limits["screening"]["max_listings_per_run"] = 77
        limits["screening"]["focused_lot_limit"] = 77
        limits["detailed_analysis"]["max_listings_per_run"] = 22
    
        (tmp_path / "data").mkdir()
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump(base, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        (tmp_path / "data/run_limits.yaml").write_text(
            yaml.safe_dump(limits, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    
>       effective = load_config(tmp_path / "config.yaml").raw
                    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_config.py:248: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

path = PosixPath('/tmp/pytest-of-runner/pytest-0/test_changing_central_limit_up0/config.yaml')

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
>               raise FileNotFoundError(
                    f"Configured search criteria file does not exist: {criteria_path}"
                )
E               FileNotFoundError: Configured search criteria file does not exist: /tmp/pytest-of-runner/pytest-0/test_changing_central_limit_up0/data/search_criteria.yaml

src/pokemon_deal_bot/config.py:532: FileNotFoundError
=========================== short test summary info ============================
FAILED tests/test_config.py::test_repository_watchlist_is_the_only_search_source - yaml.parser.ParserError: while parsing a block mapping
  in "<unicode string>", line 15, column 1:
    cards:
    ^
expected <block end>, but found '-'
  in "<unicode string>", line 42, column 1:
    - id: victini_sv11b_097
    ^
FAILED tests/test_config.py::test_changing_central_limit_updates_all_legacy_runtime_paths - FileNotFoundError: Configured search criteria file does not exist: /tmp/pytest-of-runner/pytest-0/test_changing_central_limit_up0/data/search_criteria.yaml
2 failed, 97 passed in 1.10s
Error: Process completed with exit code 1.

Worked for 1m 5s
The test output shows two separate issues, neither involving the scanner or Gemini.

1. Invalid watchlist.yaml indentation
The Victini entry currently starts at the left edge:

- id: victini_sv11b_097
It must be indented underneath cards::

cards:
  - id: ampharos_ex_xy7_027
    ...

  - id: victini_sv11b_097
    ...
The replacement watchlist contains valid Ampharos and Victini entries. Victini is set to:

active: false
so uploading the file will keep Ampharos as the active search unless you deliberately switch the cards.

The Victini entry uses the direct PriceCharting product page for Japanese Black Bolt Victini 097/086. 

2. Test fixture missing search_criteria.yaml
The central-limit test creates a temporary repository containing:

config.yaml
data/run_limits.yaml
However, config.yaml now also requires:

data/search_criteria.yaml
The corrected test copies that file into the temporary test repository before calling load_config().

GitHub-only correction package
Download the complete v7.1 correction package

watchlist.yaml

test_config.py

GITHUB_UPLOAD_INSTRUCTIONS.md

Download the checksum

SHA-256:

e5d2872a4a486bcdf643705ec4bab8c26f06a8836d631e976f6c8f658ec078f5
Replace these two files in GitHub
data/watchlist.yaml
tests/test_config.py
Commit message:

Fix watchlist YAML and central criteria test fixture
Then rerun the Tests workflow.

The replacement watchlist passed YAML parsing, and the replacement test file passed Python compilation. 


Library
/
test_config.py


from pathlib import Path

import pytest
import yaml

from pokemon_deal_bot.config import (
    AppConfig,
    load_config,
    load_run_limits,
    load_search_criteria,
    load_watchlist,
    validate_run_limits,
    validate_search_criteria,
    validate_watchlist_for_run,
    watchlist_era_lot_search_terms,
    watchlist_generic_lot_search_terms,
    watchlist_lot_search_terms,
    watchlist_search_terms,
    watchlist_signature,
)
from pokemon_deal_bot.models import WatchCard, WatchSearch, normalize_card_number


def _exact_card(**overrides):
    values = {
        "id": "ampharos",
        "match_mode": "exact_card",
        "english_name": "Ampharos EX",
        "card_number": "027/081",
        "pricecharting_url": (
            "https://www.pricecharting.com/game/"
            "pokemon-japanese-bandit-ring/ampharos-ex-27"
        ),
        "searches": [
            {"term": "XY7 まとめ売り", "mode": "focused_lot", "active": True}
        ],
    }
    values.update(overrides)
    return WatchCard(**values)


def test_unified_searches_split_by_mode():
    card = _exact_card(
        searches=[
            {"term": "デンリュウEX 027/081", "mode": "exact", "active": True},
            {"term": "XY7 まとめ売り", "mode": "focused_lot", "active": True},
            {"term": "ポケカ まとめ売り", "mode": "generic_lot", "active": False},
        ]
    )
    assert watchlist_search_terms([card]) == ["デンリュウEX 027/081"]
    assert watchlist_era_lot_search_terms([card]) == ["XY7 まとめ売り"]
    assert watchlist_generic_lot_search_terms([card]) == []
    assert watchlist_lot_search_terms([card]) == ["XY7 まとめ売り"]


def test_search_terms_are_never_generated_from_names():
    card = WatchCard(
        id="tyranitar",
        match_mode="pokemon_general",
        english_names=["Tyranitar"],
        japanese_names=["バンギラス"],
    )
    assert watchlist_search_terms([card]) == []
    assert watchlist_lot_search_terms([card]) == []


def test_legacy_constructor_fields_remain_compatible():
    card = WatchCard(
        id="legacy",
        match_mode="exact_card",
        english_name="Ampharos EX",
        card_number="027/081",
        search_terms=["デンリュウEX 027/081"],
        era_lot_search_terms=["XY7 まとめ売り"],
    )
    assert [(item.term, item.mode) for item in card.active_searches] == [
        ("デンリュウEX 027/081", "exact"),
        ("XY7 まとめ売り", "focused_lot"),
    ]


def test_watch_search_rejects_unknown_mode():
    with pytest.raises(ValueError, match="Unsupported watchlist search mode"):
        WatchSearch(term="anything", mode="wide")


def test_run_validation_requires_searches_and_pricecharting():
    no_search = _exact_card(searches=[])
    with pytest.raises(ValueError, match="no active searches"):
        validate_watchlist_for_run([no_search])

    no_price = _exact_card(pricecharting_url=None)
    with pytest.raises(ValueError, match="requires pricecharting_url"):
        validate_watchlist_for_run([no_price])


def test_run_validation_limits_each_card_to_four_active_searches():
    card = _exact_card(
        searches=[
            {"term": f"focused {index}", "mode": "focused_lot", "active": True}
            for index in range(5)
        ]
    )
    with pytest.raises(ValueError, match="maximum is 4"):
        validate_watchlist_for_run([card])


def test_exact_card_requires_a_card_number():
    with pytest.raises(ValueError, match="requires card_number"):
        WatchCard(id="invalid", match_mode="exact_card", english_name="Ampharos EX")


def test_card_number_normalisation_ignores_leading_zeroes():
    assert normalize_card_number("027/081") == "27/81"
    assert normalize_card_number("27 / 81") == "27/81"


def test_watchlist_signature_changes_when_search_changes():
    first = _exact_card(searches=[{"term": "XY7 まとめ売り", "mode": "focused_lot"}])
    second = _exact_card(searches=[{"term": "バンデットリング まとめ売り", "mode": "focused_lot"}])
    assert watchlist_signature([first]) != watchlist_signature([second])


def test_pricecharting_reference_validation():
    assert _exact_card().pricecharting_url.endswith("/ampharos-ex-27")
    with pytest.raises(ValueError, match="invalid pricecharting_url"):
        _exact_card(pricecharting_url="https://example.com/game/ampharos")
    with pytest.raises(ValueError, match="must point to a PriceCharting /game/"):
        _exact_card(pricecharting_url="https://www.pricecharting.com/search-products?q=x")


def test_load_watchlist_supports_unified_searches(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "watchlist.yaml").write_text(
        yaml.safe_dump(
            {
                "cards": [
                    {
                        "id": "ampharos",
                        "active": True,
                        "match_mode": "exact_card",
                        "english_name": "Ampharos EX",
                        "card_number": "027/081",
                        "pricecharting_url": (
                            "https://www.pricecharting.com/game/"
                            "pokemon-japanese-bandit-ring/ampharos-ex-27"
                        ),
                        "searches": [
                            {
                                "term": "XY7 まとめ売り",
                                "mode": "focused_lot",
                                "active": True,
                            }
                        ],
                    }
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    cards = load_watchlist(AppConfig(raw={}, root=tmp_path))
    validate_watchlist_for_run(cards)
    assert watchlist_era_lot_search_terms(cards) == ["XY7 まとめ売り"]


def test_repository_watchlist_is_the_only_search_source():
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "data/watchlist.yaml").read_text(encoding="utf-8"))
    active_cards = [card for card in data["cards"] if card.get("active", True)]
    assert active_cards
    for card in data["cards"]:
        assert "search_terms" not in card
        assert "lot_search_terms" not in card
        assert "era_lot_search_terms" not in card
        assert "generic_lot_search_terms" not in card
    for card in active_cards:
        active_searches = [s for s in card["searches"] if s.get("active", True)]
        assert 1 <= len(active_searches) <= 4
        assert all(s["mode"] in {"exact", "focused_lot", "generic_lot"} for s in active_searches)
        if card["match_mode"] == "exact_card":
            assert card["pricecharting_url"].startswith("https://www.pricecharting.com/game/")


def test_repository_uses_central_run_limits_file():
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert base["run_limits_file"] == "data/run_limits.yaml"
    assert base["watchlist_file"] == "data/watchlist.yaml"
    assert base["search_criteria_file"] == "data/search_criteria.yaml"

    # Tunable caps must not be duplicated in config.yaml.
    assert "max_results_per_search" not in base["sendico"]
    assert "max_listings_per_run" not in base["sendico"]
    assert "max_raw_links_per_search" not in base["sendico"]
    assert "max_screenings_per_run" not in base["sendico"]["tier2_lot_search"]
    assert "max_detailed_analyses_per_run" not in base["sendico"]["tier2_lot_search"]
    assert "max_total_tokens_per_run" not in base["vision"]
    assert "minimum_seller_positive_ratings" not in base
    assert "seller_verification" not in base
    assert "prefilter_watchlist_relevance" not in base["sendico"]
    assert "allow_query_only_candidates" not in base["sendico"]["tier2_lot_search"]
    assert "screening_confidence_threshold" not in base["sendico"]["tier2_lot_search"]
    assert "minimum_match_confidence" not in base["pricing"]

    limits = load_run_limits(root / "data/run_limits.yaml")
    criteria = load_search_criteria(root / "data/search_criteria.yaml")
    validate_search_criteria(criteria)
    validate_run_limits(limits)
    effective = load_config(root / "config.yaml")
    sendico = effective.raw["sendico"]
    tier2 = sendico["tier2_lot_search"]
    vision = effective.raw["vision"]

    assert sendico["max_results_per_search"] == limits["search"]["results_per_term"]
    assert tier2["max_results_per_search"] == limits["search"]["results_per_term"]
    assert sendico["max_listings_per_run"] == limits["search"]["total_listings_per_run"]
    assert tier2["max_screenings_per_run"] == limits["screening"]["max_listings_per_run"]
    assert tier2["max_detailed_analyses_per_run"] == limits["detailed_analysis"]["max_listings_per_run"]
    assert vision["max_listing_analyses_per_run"] == limits["detailed_analysis"]["max_listings_per_run"]
    assert vision["max_total_tokens_per_run"] == limits["token_budget"]["max_total_tokens_per_run"]
    assert sendico["prefilter_watchlist_relevance"] == criteria["discovery"]["prefilter_watchlist_relevance"]
    assert tier2["allow_query_only_candidates"] == criteria["discovery"]["allow_query_only_candidates"]
    assert tier2["screening_confidence_threshold"] == criteria["screening"]["minimum_target_probability"]
    assert vision["minimum_target_confidence"] == criteria["detailed_analysis"]["minimum_target_confidence"]
    assert effective.raw["minimum_seller_positive_ratings"] == criteria["seller"]["minimum_positive_ratings"]


def test_changing_central_limit_updates_all_legacy_runtime_paths(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    limits = yaml.safe_load((root / "data/run_limits.yaml").read_text(encoding="utf-8"))
    limits["screening"]["max_listings_per_run"] = 77
    limits["screening"]["focused_lot_limit"] = 77
    limits["detailed_analysis"]["max_listings_per_run"] = 22

    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(base, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (tmp_path / "data/run_limits.yaml").write_text(
        yaml.safe_dump(limits, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    criteria = yaml.safe_load(
        (root / "data/search_criteria.yaml").read_text(encoding="utf-8")
    )
    (tmp_path / "data/search_criteria.yaml").write_text(
        yaml.safe_dump(criteria, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    effective = load_config(tmp_path / "config.yaml").raw
    assert effective["sendico"]["tier2_lot_search"]["max_screenings_per_run"] == 77
    assert effective["sendico"]["tier2_lot_search"]["max_detailed_analyses_per_run"] == 22
    assert effective["vision"]["max_listing_analyses_per_run"] == 22


def test_central_limits_validation_rejects_inconsistent_values():
    root = Path(__file__).resolve().parents[1]
    limits = yaml.safe_load((root / "data/run_limits.yaml").read_text(encoding="utf-8"))
    limits["search"]["raw_links_per_term"] = 5
    limits["search"]["results_per_term"] = 25
    with pytest.raises(ValueError, match="raw_links_per_term"):
        validate_run_limits(limits)


def test_changing_central_criteria_updates_runtime_without_test_edits(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    limits = yaml.safe_load((root / "data/run_limits.yaml").read_text(encoding="utf-8"))
    criteria = yaml.safe_load((root / "data/search_criteria.yaml").read_text(encoding="utf-8"))
    criteria["discovery"]["allow_query_only_candidates"] = False
    criteria["screening"]["minimum_target_probability"] = 0.55
    criteria["detailed_analysis"]["minimum_target_confidence"] = 0.72

    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(base, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (tmp_path / "data/run_limits.yaml").write_text(
        yaml.safe_dump(limits, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (tmp_path / "data/search_criteria.yaml").write_text(
        yaml.safe_dump(criteria, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    effective = load_config(tmp_path / "config.yaml").raw
    assert effective["sendico"]["tier2_lot_search"]["allow_query_only_candidates"] is False
    assert effective["sendico"]["tier2_lot_search"]["screening_confidence_threshold"] == 0.55
    assert effective["vision"]["minimum_target_confidence"] == 0.72
Library
/
test_config.py


from pathlib import Path

import pytest
import yaml

from pokemon_deal_bot.config import (
    AppConfig,
    load_config,
    load_run_limits,
    load_search_criteria,
    load_watchlist,
    validate_run_limits,
    validate_search_criteria,
    validate_watchlist_for_run,
    watchlist_era_lot_search_terms,
    watchlist_generic_lot_search_terms,
    watchlist_lot_search_terms,
    watchlist_search_terms,
    watchlist_signature,
)
from pokemon_deal_bot.models import WatchCard, WatchSearch, normalize_card_number


def _exact_card(**overrides):
    values = {
        "id": "ampharos",
        "match_mode": "exact_card",
        "english_name": "Ampharos EX",
        "card_number": "027/081",
        "pricecharting_url": (
            "https://www.pricecharting.com/game/"
            "pokemon-japanese-bandit-ring/ampharos-ex-27"
        ),
        "searches": [
            {"term": "XY7 まとめ売り", "mode": "focused_lot", "active": True}
        ],
    }
    values.update(overrides)
    return WatchCard(**values)


def test_unified_searches_split_by_mode():
    card = _exact_card(
        searches=[
            {"term": "デンリュウEX 027/081", "mode": "exact", "active": True},
            {"term": "XY7 まとめ売り", "mode": "focused_lot", "active": True},
            {"term": "ポケカ まとめ売り", "mode": "generic_lot", "active": False},
        ]
    )
    assert watchlist_search_terms([card]) == ["デンリュウEX 027/081"]
    assert watchlist_era_lot_search_terms([card]) == ["XY7 まとめ売り"]
    assert watchlist_generic_lot_search_terms([card]) == []
    assert watchlist_lot_search_terms([card]) == ["XY7 まとめ売り"]


def test_search_terms_are_never_generated_from_names():
    card = WatchCard(
        id="tyranitar",
        match_mode="pokemon_general",
        english_names=["Tyranitar"],
        japanese_names=["バンギラス"],
    )
    assert watchlist_search_terms([card]) == []
    assert watchlist_lot_search_terms([card]) == []


def test_legacy_constructor_fields_remain_compatible():
    card = WatchCard(
        id="legacy",
        match_mode="exact_card",
        english_name="Ampharos EX",
        card_number="027/081",
        search_terms=["デンリュウEX 027/081"],
        era_lot_search_terms=["XY7 まとめ売り"],
    )
    assert [(item.term, item.mode) for item in card.active_searches] == [
        ("デンリュウEX 027/081", "exact"),
        ("XY7 まとめ売り", "focused_lot"),
    ]


def test_watch_search_rejects_unknown_mode():
    with pytest.raises(ValueError, match="Unsupported watchlist search mode"):
        WatchSearch(term="anything", mode="wide")


def test_run_validation_requires_searches_and_pricecharting():
    no_search = _exact_card(searches=[])
    with pytest.raises(ValueError, match="no active searches"):
        validate_watchlist_for_run([no_search])

    no_price = _exact_card(pricecharting_url=None)
    with pytest.raises(ValueError, match="requires pricecharting_url"):
        validate_watchlist_for_run([no_price])


def test_run_validation_limits_each_card_to_four_active_searches():
    card = _exact_card(
        searches=[
            {"term": f"focused {index}", "mode": "focused_lot", "active": True}
            for index in range(5)
        ]
    )
    with pytest.raises(ValueError, match="maximum is 4"):
        validate_watchlist_for_run([card])


def test_exact_card_requires_a_card_number():
    with pytest.raises(ValueError, match="requires card_number"):
        WatchCard(id="invalid", match_mode="exact_card", english_name="Ampharos EX")


def test_card_number_normalisation_ignores_leading_zeroes():
    assert normalize_card_number("027/081") == "27/81"
    assert normalize_card_number("27 / 81") == "27/81"


def test_watchlist_signature_changes_when_search_changes():
    first = _exact_card(searches=[{"term": "XY7 まとめ売り", "mode": "focused_lot"}])
    second = _exact_card(searches=[{"term": "バンデットリング まとめ売り", "mode": "focused_lot"}])
    assert watchlist_signature([first]) != watchlist_signature([second])


def test_pricecharting_reference_validation():
    assert _exact_card().pricecharting_url.endswith("/ampharos-ex-27")
    with pytest.raises(ValueError, match="invalid pricecharting_url"):
        _exact_card(pricecharting_url="https://example.com/game/ampharos")
    with pytest.raises(ValueError, match="must point to a PriceCharting /game/"):
        _exact_card(pricecharting_url="https://www.pricecharting.com/search-products?q=x")


def test_load_watchlist_supports_unified_searches(tmp_path: Path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "watchlist.yaml").write_text(
        yaml.safe_dump(
            {
                "cards": [
                    {
                        "id": "ampharos",
                        "active": True,
                        "match_mode": "exact_card",
                        "english_name": "Ampharos EX",
                        "card_number": "027/081",
                        "pricecharting_url": (
                            "https://www.pricecharting.com/game/"
                            "pokemon-japanese-bandit-ring/ampharos-ex-27"
                        ),
                        "searches": [
                            {
                                "term": "XY7 まとめ売り",
                                "mode": "focused_lot",
                                "active": True,
                            }
                        ],
                    }
                ]
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    cards = load_watchlist(AppConfig(raw={}, root=tmp_path))
    validate_watchlist_for_run(cards)
    assert watchlist_era_lot_search_terms(cards) == ["XY7 まとめ売り"]


def test_repository_watchlist_is_the_only_search_source():
    root = Path(__file__).resolve().parents[1]
    data = yaml.safe_load((root / "data/watchlist.yaml").read_text(encoding="utf-8"))
    active_cards = [card for card in data["cards"] if card.get("active", True)]
    assert active_cards
    for card in data["cards"]:
        assert "search_terms" not in card
        assert "lot_search_terms" not in card
        assert "era_lot_search_terms" not in card
        assert "generic_lot_search_terms" not in card
    for card in active_cards:
        active_searches = [s for s in card["searches"] if s.get("active", True)]
        assert 1 <= len(active_searches) <= 4
        assert all(s["mode"] in {"exact", "focused_lot", "generic_lot"} for s in active_searches)
        if card["match_mode"] == "exact_card":
            assert card["pricecharting_url"].startswith("https://www.pricecharting.com/game/")


def test_repository_uses_central_run_limits_file():
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    assert base["run_limits_file"] == "data/run_limits.yaml"
    assert base["watchlist_file"] == "data/watchlist.yaml"
    assert base["search_criteria_file"] == "data/search_criteria.yaml"

    # Tunable caps must not be duplicated in config.yaml.
    assert "max_results_per_search" not in base["sendico"]
    assert "max_listings_per_run" not in base["sendico"]
    assert "max_raw_links_per_search" not in base["sendico"]
    assert "max_screenings_per_run" not in base["sendico"]["tier2_lot_search"]
    assert "max_detailed_analyses_per_run" not in base["sendico"]["tier2_lot_search"]
    assert "max_total_tokens_per_run" not in base["vision"]
    assert "minimum_seller_positive_ratings" not in base
    assert "seller_verification" not in base
    assert "prefilter_watchlist_relevance" not in base["sendico"]
    assert "allow_query_only_candidates" not in base["sendico"]["tier2_lot_search"]
    assert "screening_confidence_threshold" not in base["sendico"]["tier2_lot_search"]
    assert "minimum_match_confidence" not in base["pricing"]

    limits = load_run_limits(root / "data/run_limits.yaml")
    criteria = load_search_criteria(root / "data/search_criteria.yaml")
    validate_search_criteria(criteria)
    validate_run_limits(limits)
    effective = load_config(root / "config.yaml")
    sendico = effective.raw["sendico"]
    tier2 = sendico["tier2_lot_search"]
    vision = effective.raw["vision"]

    assert sendico["max_results_per_search"] == limits["search"]["results_per_term"]
    assert tier2["max_results_per_search"] == limits["search"]["results_per_term"]
    assert sendico["max_listings_per_run"] == limits["search"]["total_listings_per_run"]
    assert tier2["max_screenings_per_run"] == limits["screening"]["max_listings_per_run"]
    assert tier2["max_detailed_analyses_per_run"] == limits["detailed_analysis"]["max_listings_per_run"]
    assert vision["max_listing_analyses_per_run"] == limits["detailed_analysis"]["max_listings_per_run"]
    assert vision["max_total_tokens_per_run"] == limits["token_budget"]["max_total_tokens_per_run"]
    assert sendico["prefilter_watchlist_relevance"] == criteria["discovery"]["prefilter_watchlist_relevance"]
    assert tier2["allow_query_only_candidates"] == criteria["discovery"]["allow_query_only_candidates"]
    assert tier2["screening_confidence_threshold"] == criteria["screening"]["minimum_target_probability"]
    assert vision["minimum_target_confidence"] == criteria["detailed_analysis"]["minimum_target_confidence"]
    assert effective.raw["minimum_seller_positive_ratings"] == criteria["seller"]["minimum_positive_ratings"]


def test_changing_central_limit_updates_all_legacy_runtime_paths(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    limits = yaml.safe_load((root / "data/run_limits.yaml").read_text(encoding="utf-8"))
    limits["screening"]["max_listings_per_run"] = 77
    limits["screening"]["focused_lot_limit"] = 77
    limits["detailed_analysis"]["max_listings_per_run"] = 22

    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(base, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (tmp_path / "data/run_limits.yaml").write_text(
        yaml.safe_dump(limits, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    criteria = yaml.safe_load(
        (root / "data/search_criteria.yaml").read_text(encoding="utf-8")
    )
    (tmp_path / "data/search_criteria.yaml").write_text(
        yaml.safe_dump(criteria, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    effective = load_config(tmp_path / "config.yaml").raw
    assert effective["sendico"]["tier2_lot_search"]["max_screenings_per_run"] == 77
    assert effective["sendico"]["tier2_lot_search"]["max_detailed_analyses_per_run"] == 22
    assert effective["vision"]["max_listing_analyses_per_run"] == 22


def test_central_limits_validation_rejects_inconsistent_values():
    root = Path(__file__).resolve().parents[1]
    limits = yaml.safe_load((root / "data/run_limits.yaml").read_text(encoding="utf-8"))
    limits["search"]["raw_links_per_term"] = 5
    limits["search"]["results_per_term"] = 25
    with pytest.raises(ValueError, match="raw_links_per_term"):
        validate_run_limits(limits)


def test_changing_central_criteria_updates_runtime_without_test_edits(tmp_path: Path):
    root = Path(__file__).resolve().parents[1]
    base = yaml.safe_load((root / "config.yaml").read_text(encoding="utf-8"))
    limits = yaml.safe_load((root / "data/run_limits.yaml").read_text(encoding="utf-8"))
    criteria = yaml.safe_load((root / "data/search_criteria.yaml").read_text(encoding="utf-8"))
    criteria["discovery"]["allow_query_only_candidates"] = False
    criteria["screening"]["minimum_target_probability"] = 0.55
    criteria["detailed_analysis"]["minimum_target_confidence"] = 0.72

    (tmp_path / "data").mkdir()
    (tmp_path / "config.yaml").write_text(
        yaml.safe_dump(base, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (tmp_path / "data/run_limits.yaml").write_text(
        yaml.safe_dump(limits, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    (tmp_path / "data/search_criteria.yaml").write_text(
        yaml.safe_dump(criteria, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    effective = load_config(tmp_path / "config.yaml").raw
    assert effective["sendico"]["tier2_lot_search"]["allow_query_only_candidates"] is False
    assert effective["sendico"]["tier2_lot_search"]["screening_confidence_threshold"] == 0.55
    assert effective["vision"]["minimum_target_confidence"] == 0.72
