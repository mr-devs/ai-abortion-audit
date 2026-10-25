"""
Unit tests for the coding-task checks in toolkit.llm_coding: the text
normalization used for verbatim checks, and check_batch on small place and
domain batches written to a temporary directory.

Run with: uv run pytest code/tests
"""

import json
from pathlib import Path

import pytest

from toolkit.llm_coding import check_batch, load_schema, normalize_for_match, write_batches

CODEBOOK_DIR = Path(__file__).resolve().parents[1] / "cleaning" / "codebooks"
TEXT = (
    "**1. Columbus Women’s Health Organization (Columbus, GA)**\n"
    "- Address: 3850 Rosemont Dr, Columbus, GA 31904\n"
    "- Phone: (706) 323-3816\n"
    "Alabama has a near-total abortion ban."
)


def entity(**overrides):
    """Return a valid primary entity for TEXT, with fields overridden."""
    values = {
        "entity_index": 1,
        "role": "primary",
        "list_position": 1,
        "name_verbatim": "Columbus Women's Health Organization",
        "entity_type": "abortion_clinic",
        "possible_cpc_name": False,
        "presented_as_abortion_provider": "yes",
        "services_verbatim": None,
        "address_verbatim": "3850 Rosemont Dr, Columbus, GA 31904",
        "street": "3850 Rosemont Dr",
        "city": "Columbus",
        "state_abbr": "GA",
        "zip": "31904",
        "address_parts_from_context": False,
        "phones_verbatim": ["(706) 323-3816"],
        "website_verbatim": None,
        "distance_claim_verbatim": None,
        "caveat_verbatim": None,
        "evidence_quote": "1. Columbus Women's Health Organization (Columbus, GA)",
    }
    return {**values, **overrides}


def place_item(entities):
    """Return a valid item for TEXT with the given entities."""
    return {
        "item_id": "r0001",
        "query_city": "Oak Hill",
        "query_state_abbr": "AL",
        "answer_status": "places_provided",
        "asks_follow_up": False,
        "follow_up_request_verbatim": None,
        "state_law_claim": "banned",
        "state_law_quote_verbatim": "Alabama has a near-total abortion ban.",
        "says_travel_needed": True,
        "mentions_telehealth": False,
        "mentions_gestational_limits": False,
        "mentions_financial_help": False,
        "entities": entities,
        "extractor_notes": None,
    }


@pytest.fixture
def place_batch(tmp_path):
    """Write a one-record input batch and return a function that checks an output."""
    record = {
        "item_id": "r0001",
        "query_city": "Oak Hill",
        "query_state_abbr": "AL",
        "message": "I live in Oak Hill, AL. ...",
        "text": TEXT,
    }
    (batch,) = write_batches([record], tmp_path / "input", batch_size=20, seed=1)
    schema = load_schema(CODEBOOK_DIR / "place_extraction.schema.json")

    def check(items, batch_id="batch_000"):
        output = tmp_path / "batch_000.json"
        coded = {
            "batch_id": batch_id,
            "extractor_model": "test",
            "extracted_on": "2026-10-24",
            "items": items,
        }
        output.write_text(json.dumps(coded), encoding="utf-8")
        return check_batch("places", batch["input_path"], output, schema)

    return check


def kinds(problems):
    return [p["kind"] for p in problems]


def test_normalize_for_match_ignores_quotes_emphasis_and_whitespace():
    assert normalize_for_match("**Women’s**\n  Health") == "Women's Health"


def test_valid_place_batch_passes(place_batch):
    assert place_batch([place_item([entity()])]) == []


def test_altered_phone_is_a_verbatim_problem(place_batch):
    problems = place_batch([place_item([entity(phones_verbatim=["706-323-3816"])])])
    assert kinds(problems) == ["verbatim"]
    assert problems[0]["entity_index"] == 1


def test_schema_errors_are_reported_alone(place_batch):
    problems = place_batch([place_item([entity(entity_type="clinic")])])
    assert set(kinds(problems)) == {"schema"}


def test_missing_and_altered_items_are_id_problems(place_batch):
    assert kinds(place_batch([])) == ["ids"]
    item = place_item([entity()])
    item["query_city"] = "Oakhill"
    assert kinds(place_batch([item])) == ["ids"]
    assert kinds(place_batch([place_item([entity()])], batch_id="batch_9")) == ["ids"]


def test_role_rules_are_consistency_problems(place_batch):
    no_position = entity(list_position=None)
    assert kinds(place_batch([place_item([no_position])])) == ["consistency"]
    # A resource-only answer cannot be places_provided.
    resource = entity(role="resource", list_position=None, entity_type="hotline")
    assert kinds(place_batch([place_item([resource])])) == ["consistency"]


def test_domain_batch_checks_the_domain(tmp_path):
    record = {"item_id": "d0001", "domain": "ineedana.com", "n_shown": 3, "n_responses": 2, "example_urls": []}
    (batch,) = write_batches([record], tmp_path / "input", batch_size=25, seed=1)
    item = {
        "item_id": "d0001",
        "domain": "ineedana.com",
        "category": "abortion_directory",
        "stance_on_abortion_access": "supports_access",
        "cpc_affiliated": "no",
        "provides_abortions": "no",
        "site_loaded": True,
        "evidence_urls": ["https://www.ineedana.com/about"],
        "rationale": "A directory of abortion providers.",
        "confidence": "high",
    }
    output = tmp_path / "batch_000.json"
    schema = load_schema(CODEBOOK_DIR / "domain_coding.schema.json")
    for domain, expected in [("ineedana.com", []), ("ineedana.org", ["ids"])]:
        coded = {"batch_id": "batch_000", "extractor_model": "test", "extracted_on": "2026-10-24",
                 "items": [{**item, "domain": domain}]}
        output.write_text(json.dumps(coded), encoding="utf-8")
        assert kinds(check_batch("domains", batch["input_path"], output, schema)) == expected
