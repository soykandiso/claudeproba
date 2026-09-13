"""CallExtraction, the extract_call prompt, and citation location. No database, no model."""

import json
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.ai.gateway import Routing
from app.ai.prompts import load_prompt
from app.ai.schemas import CallExtraction, ExtractedCriterion
from app.ai.scrub import Scrubber
from app.ingestion.extract import TASK, Document, locate_citations
from app.ingestion.normalise import normalise
from app.ingestion.normalise.html import normalise_html
from app.matching.operators import FIELDS, Operator, ProfileField
from app.models.enums import EntityType

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
CASSETTES = ROOT / "tests" / "cassettes" / "extract_call"


def fixture_text(name: str) -> str:
    if name == "economy-call-3":
        return normalise((FIXTURES / "economy/call-3-javen-povik.docx").read_bytes()).text
    if name == "av-measure-819":
        detail = json.loads((FIXTURES / "av/measure-819-business-mk.json").read_bytes())["d"]
        return normalise_html(detail).text
    if name == "ipard-notice-03-2025":
        return normalise((FIXTURES / "ipardpa/call-34-najava-03-2025.pdf").read_bytes()).text
    raise KeyError(name)


CASES = ["economy-call-3", "av-measure-819", "ipard-notice-03-2025"]


def cassette(name: str) -> str:
    return (CASSETTES / f"{name}.json").read_text(encoding="utf-8")


def criterion(**overrides) -> dict:
    base = {
        "document": 1,
        "quote": "Работење во траење од најмалку 12 месеци",
        "kind": "hard_structured",
        "label_mk": "Најмалку 12 месеци работење",
        "applies_to_all_applicants": True,
        "field": "age_months",
        "operator": "gte",
        "minimum": 12,
        "confidence": 0.9,
    }
    return base | overrides


# --- the schema -----------------------------------------------------------------------


@pytest.mark.parametrize("name", CASES)
def test_the_hand_written_replies_validate(name):
    CallExtraction.model_validate_json(cassette(name))


def test_a_well_formed_hard_criterion_is_accepted_and_stored_as_value_json():
    crit = ExtractedCriterion.model_validate(criterion(operator="between", maximum=120))
    assert crit.value_json() == {"min": 12, "max": 120}

    listed = ExtractedCriterion.model_validate(
        criterion(field="entity_type", operator="not_in", values=["large"], minimum=None)
    )
    assert listed.value_json() == {"values": ["large"]}


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"field": None}, "needs a field and an operator"),
        ({"applies_to_all_applicants": False}, "only some applicant types"),
        ({"field": "region_code"}, "field"),
        ({"operator": "prefix_in"}, "takes only these operators"),
        ({"operator": "gte", "minimum": None, "maximum": 12}, "needs exactly: minimum"),
        ({"operator": "between", "minimum": 24, "maximum": 12}, "greater than maximum"),
        ({"minimum": -1}, "negative"),
        (
            {"field": "entity_type", "operator": "in", "values": ["company"], "minimum": None},
            "not a valid entity_type",
        ),
        (
            {"field": "nace_code", "operator": "prefix_in", "values": ["62.0.1"], "minimum": None},
            "not a valid nace_code",
        ),
        ({"field": "nace_code", "operator": "prefix_in", "values": []}, "non-empty values"),
        ({"kind": "narrative_verify"}, "carries no field"),
        ({"quote": "12 мес."}, "at least 8 characters"),
        ({"surprise": True}, "Extra inputs"),
    ],
)
def test_a_criterion_outside_the_vocabulary_is_refused(overrides, message):
    with pytest.raises(ValidationError, match=message):
        ExtractedCriterion.model_validate(criterion(**overrides))


def test_a_call_needs_a_title_but_a_non_call_does_not():
    with pytest.raises(ValidationError, match="needs title_mk"):
        CallExtraction.model_validate({"document_kind": "call", "title_mk": None})
    CallExtraction.model_validate({"document_kind": "not_a_funding_call", "title_mk": None})


def test_quoted_walks_every_cited_item():
    output = CallExtraction.model_validate_json(cassette("economy-call-3"))
    paths = [path for path, _ in output.quoted()]

    assert paths[:4] == ["title_mk", "deadline", "total_budget", "grant_max"]
    assert paths.count("grant_share_pct") == 1
    assert [p for p in paths if p.startswith("criteria.")] == [
        f"criteria.{i}" for i in range(len(output.criteria))
    ]


# --- the prompt and its route ---------------------------------------------------------


def test_the_route_points_at_a_prompt_file_that_exists():
    route = Routing.load().route(TASK)
    prompt = load_prompt(ROOT / "prompts", TASK, route.prompt_version)

    system, user = prompt.render({"documents": '<document index="1">текст</document>'})
    assert "текст" in user


def test_the_prompt_names_exactly_the_vocabulary_the_schema_enforces():
    """The prompt is a versioned file, so it cannot be generated; this catches drift instead."""
    route = Routing.load().route(TASK)
    text = load_prompt(ROOT / "prompts", TASK, route.prompt_version).path.read_text()
    table = {
        match.group(1): set(re.findall(r"`(\w+)`", match.group(2)))
        for match in re.finditer(r"^\| `(\w+)` \|[^|]*\| ([^|]*) \|", text, re.M)
    }

    assert set(table) == set(FIELDS)
    for field, spec in FIELDS.items():
        assert table[field] == set(spec.operators), field
    assert set(Operator) == set().union(*table.values())
    entity_line = next(line for line in text.splitlines() if line.startswith("| `entity_type`"))
    for entity in EntityType:
        assert entity in entity_line
    assert ProfileField.INVESTMENT_SIZE_MKD in text


def test_the_prompt_itself_carries_no_identity_data():
    route = Routing.load().route(TASK)
    system, user = load_prompt(ROOT / "prompts", TASK, route.prompt_version).render(
        {"documents": ""}
    )
    Scrubber().assert_clean(system)
    Scrubber().assert_clean(user)


# --- citation location ----------------------------------------------------------------


@pytest.mark.parametrize("name", CASES)
def test_every_quote_in_the_fixture_replies_is_located_in_the_real_document(name):
    """Roadmap P1 s10 acceptance, in part: criteria extract with citations."""
    text = fixture_text(name)
    output = CallExtraction.model_validate_json(cassette(name))
    documents = [Document(snapshot_id=41, url=f"https://example.mk/{name}", text=text)]

    citations, failures = locate_citations(output, documents)

    assert failures == []
    assert set(citations) == {path for path, _ in output.quoted()}
    for citation in citations.values():
        assert citation.snapshot_id == 41
        assert text[citation.char_start : citation.char_end] == citation.source_quote
    assert output.criteria, "each fixture reply has criteria"


def test_a_look_alike_letter_is_matched_and_the_document_spelling_is_what_is_cited():
    text = fixture_text("ipard-notice-03-2025")
    output = CallExtraction.model_validate_json(cassette("ipard-notice-03-2025"))

    citations, _ = locate_citations(output, [Document(1, "u", text)])

    [(path, item)] = [(p, i) for p, i in output.quoted() if "лтернативно" in i.quote]
    assert item.quote.startswith("А")  # the model's all-Cyrillic copy
    assert citations[path].source_quote.startswith("A")  # the document's Latin A


def test_paraphrase_line_joins_and_bad_document_indexes_all_fail():
    text = fixture_text("economy-call-3")
    output = CallExtraction.model_validate(
        {
            "document_kind": "call",
            "title_mk": {
                "document": 1,
                "quote": "ЈАВЕН ПОВИК за финансиска поддршка",
                "value": "x",
            },
            "deadline": {
                "document": 1,
                "quote": "Рокот за аплицирање е 30.06.2026",
                "value": "2026-06-30",
            },
            "grant_max": {
                "document": 2,
                "quote": "не повеќе од 200.000 денари",
                "amount": 1,
                "currency": "MKD",
            },
        }
    )

    citations, failures = locate_citations(output, [Document(1, "u", text)])

    assert citations == {}
    assert [(f.path, f.reason) for f in failures] == [
        ("title_mk", "quote not found verbatim"),  # the document has "ЈАВЕН ПОВИК\nза ..."
        ("deadline", "quote not found verbatim"),  # paraphrase
        ("grant_max", "no such document"),
    ]


def test_a_quote_copied_across_a_scrubbed_pseudonym_fails():
    text = fixture_text("economy-call-3")
    scrubbed = Scrubber().scrub(text)
    line = next(line for line in scrubbed.splitlines() if "[ADDRESS_1]" in line)
    quote = line[line.index("на адреса") : line.index("[ADDRESS_1]") + len("[ADDRESS_1]")]
    output = CallExtraction.model_validate(
        {
            "document_kind": "call",
            "title_mk": {"document": 1, "quote": quote, "value": "x"},
        }
    )

    _, failures = locate_citations(output, [Document(1, "u", text)])

    assert [f.path for f in failures] == ["title_mk"]
