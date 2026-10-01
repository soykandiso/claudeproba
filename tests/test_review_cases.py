"""Reviewer decisions become evaluation cases (roadmap P2 s34).

The row's acceptance is `test_a_rejected_report_appears_on_the_next_run`: a report a
person closed is a file in the cases directory after the next export, and a run
after that writes nothing new. The rest proves what may and may not be in a case —
no identity, no bookkeeping — and that the harness loads what the export writes.
"""

import pytest
import yaml

from app import create_app
from app.config import load_settings
from app.models import ApplicantProfile, MatchRun, ReviewQueueItem
from app.models.enums import CriterionKind, ReviewKind, ReviewState
from app.review import cases
from app.review import extraction as review
from app.review import report as reports
from evals import harness
from tests import test_report_compose as tc
from tests.test_deep import BAKERY
from tests.test_extract import ScriptedProvider
from tests.test_extract_schema import cassette
from tests.test_pipeline import AvSite, run, sessions, store  # noqa: F401
from tests.test_review_extraction import form_from, load, site, written  # noqa: F401
from tests.test_stage1 import DATABASE_AVAILABLE, NOW

pytestmark = pytest.mark.skipif(not DATABASE_AVAILABLE, reason="no database reachable")

registry = tc.registry
world = tc.world

FIXED = "Условот за дејноста е исполнет според текстот на повикот, но одлуката е на институцијата."


def draft(world) -> tuple:
    factory, run_id = tc.verified_run(world)
    item, _ = tc.composed(factory, run_id, tc.prose())
    return factory, item.id


def export(factory, out) -> list:
    with factory() as s:
        return cases.export(s, out)


def read(path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ the acceptance


def test_a_rejected_report_appears_on_the_next_run(world, tmp_path):
    factory, item_id = draft(world)
    assert export(factory, tmp_path) == []  # pending: nothing decided, nothing owed

    with factory() as s:
        reports.close(s, s.get(ReviewQueueItem, item_id), note="објаснувањето е општо", now=NOW)
        s.commit()
    [path] = export(factory, tmp_path)

    assert path == tmp_path / f"report-{item_id}.yaml"
    case = read(path)
    assert case["source"] == "review" and case["kind"] == "report"
    assert (case["item"], case["decision"]) == (item_id, "rejected")
    assert case["reviewer_note"] == "објаснувањето е општо"
    assert case["model"]["task"] == "compose_report" and case["model"]["prompt_version"]
    assert case["run"]["weights_version"] and case["run"]["ruleset_version"]
    [call] = case["draft"]["calls"]
    assert call["conditions"][0]["citation"]["quote"] == "цитат"
    assert path.read_text(encoding="utf-8").startswith(f"# Ставка {item_id} ")

    # Written once: the next run adds nothing and leaves the file as it was.
    before = path.read_bytes()
    assert export(factory, tmp_path) == []
    assert path.read_bytes() == before
    # And the harness reads it as a case from review, not as a verdict file.
    counts, problems = harness.load_review_cases(tmp_path)
    assert problems == [] and counts == {("report", "rejected"): 1}


def test_nothing_identifying_leaves_in_a_report_case(world, tmp_path):
    """The applicant is the shape a model sees; what a person typed is scrubbed."""
    factory, item_id = draft(world)
    with factory() as s:
        item = s.get(ReviewQueueItem, item_id)
        run = s.get(MatchRun, item.match_run_id)
        profile = s.get(ApplicantProfile, run.profile_id)
        profile.label = "Пекара Јовановски"
        reports.edit_statement(
            s, item, part="summary", call=None, n=1,
            text_mk=f"{FIXED} Прашајте на 070 123 456.", cites="1.1", now=NOW,
        )  # fmt: skip
        reports.approve(s, item, note="Пекара Јовановски, јавете се на 02/3123-456", now=NOW)
        s.commit()
        profile_id = str(profile.id)

    [path] = export(factory, tmp_path)
    text = path.read_text(encoding="utf-8")
    case = read(path)

    assert case["decision"] == "edited"
    assert "Јовановски" not in text and "3123-456" not in text and "123 456" not in text
    assert case["reviewer_note"].startswith("[IDENTIFIER_1]")
    [edit] = case["edits"]
    assert edit["before"]["text_mk"] == tc.CLEAN  # the model's words, kept as written
    assert "[PHONE_2]" in edit["after"]["text_mk"]  # one scrubber per case: stable names
    # The applicant as bands and codes; never the answers, the municipality or the row.
    assert "Дејност: 10.71" in case["applicant"]
    assert BAKERY["municipality"] not in text and profile_id not in text
    assert "@" not in text


def test_an_approval_without_an_edit_is_not_a_case(world, tmp_path):
    factory, item_id = draft(world)
    with factory() as s:
        reports.approve(s, s.get(ReviewQueueItem, item_id), note="во ред", now=NOW)
        s.commit()
    assert export(factory, tmp_path) == []


def test_a_run_s_failed_verifications_travel_with_its_report(world, tmp_path):
    factory, item_id = draft(world)
    with factory() as s:
        item = s.get(ReviewQueueItem, item_id)
        failed = ReviewQueueItem(
            kind=ReviewKind.VERIFICATION,
            reason="verify_criterion: quote not in the passage it names",
            match_run_id=item.match_run_id,
            payload={"stage": "verify", "criterion": "Дејност", "answer": {"quote": "x"}},
        )
        s.add(failed)
        reports.close(s, item, note="услов 1.1 не е проверен", now=NOW)
        s.commit()
        failed_id = failed.id

    [path] = export(factory, tmp_path)  # the verification item is not a case of its own
    [carried] = read(path)["failed_verifications"]
    assert carried["item"] == failed_id and carried["criterion"] == "Дејност"


# ------------------------------------------------------------------ extraction items


def test_a_rejected_extraction_names_its_documents_and_what_the_model_said(
    sessions,  # noqa: F811
    written,  # noqa: F811
    tmp_path,
):
    s, item, call = load(sessions, written)
    review.close(s, item, note="вест, не повик", now=NOW)
    s.commit()

    [path] = cases.export(s, tmp_path)
    case = read(path)
    s.close()

    assert path.name == f"extraction-{item.id}.yaml"
    assert case["stage"] == review.APPROVE_CALL and case["reviewer_note"] == "вест, не повик"
    [document] = case["documents"]
    assert len(document["content_sha256"]) == 64 and document["url"].startswith("https://")
    assert case["extracted"]["criteria"]  # the model's output, before anyone touched it
    assert case["model"]["task"] == "extract_call"
    assert "corrected" not in case  # a rejection says why, not what the answer is


def test_an_edited_extraction_carries_the_published_criteria_as_the_truth(
    sessions,  # noqa: F811
    written,  # noqa: F811
    tmp_path,
):
    s, item, call = load(sessions, written)
    attest = next(
        c for c in review.criteria_of(s, call) if c.kind == CriterionKind.APPLICANT_ATTEST
    )
    review.edit_criterion(
        s, item, attest.id, form_from(attest, label_mk="Вработен 6 месеци"), now=NOW
    )
    review.approve_call(s, item, note=None, now=NOW)
    s.commit()

    [path] = cases.export(s, tmp_path)
    s.close()
    case = read(path)

    assert case["decision"] == "edited"
    [edit] = case["edits"]
    assert edit["after"]["label_mk"] == "Вработен 6 месеци"
    labels = [c["label_mk"] for c in case["corrected"]["criteria"]]
    assert "Вработен 6 месеци" in labels
    assert harness.load_review_cases(tmp_path) == ({("extraction", "edited"): 1}, [])


def test_an_item_superseded_by_a_newer_approval_is_not_a_case(
    sessions,  # noqa: F811
    store,  # noqa: F811
    site,  # noqa: F811
    written,  # noqa: F811
    tmp_path,
):
    site.change_text(819, "до 21.08.2026 година", "до 28.08.2026 година")
    reply = (
        cassette("av-measure-819")
        .replace("21.08.2026", "28.08.2026")
        .replace("2026-08-21", "2026-08-28")
    )
    changed = run(sessions, store, site, ScriptedProvider(reply))
    s = sessions()
    new = s.get(ReviewQueueItem, changed.processed[0].review_item_id)
    review.approve_call(s, new, note=None, now=NOW)
    s.commit()
    old = s.get(ReviewQueueItem, written.review_item_id)
    assert old.state == ReviewState.REJECTED

    assert cases.export(s, tmp_path) == []
    s.close()


# ------------------------------------------------------------------ the harness


def valid(kind="report", item=7, decision="rejected") -> dict:
    return {
        "version": 1,
        "source": "review",
        "kind": kind,
        "item": item,
        "decision": decision,
        "reviewer_note": "зошто",
        "edits": [{"before": "a", "after": "b"}],
        harness.REVIEW_KINDS[kind]: {},
    }


@pytest.mark.parametrize(
    ("name", "data", "complaint"),
    [
        ("report-7.yaml", valid() | {"source": "hand"}, "not a version-1 case"),
        ("report-8.yaml", valid(), "names item 7"),
        ("verdict-7.yaml", valid() | {"kind": "verdict"}, "not a kind"),
        ("report-7.yaml", valid() | {"reviewer_note": " "}, "without its reason"),
        ("report-7.yaml", valid(decision="edited") | {"edits": []}, "before and after"),
        ("report-7.yaml", valid(decision="approved"), "not a decision"),
        ("extraction-7.yaml", valid() | {"kind": "extraction"}, "without its documents"),
    ],
)
def test_a_malformed_case_from_review_blocks_the_gate(tmp_path, name, data, complaint):
    (tmp_path / name).write_text(yaml.safe_dump(data), encoding="utf-8")
    counts, [problem] = harness.load_review_cases(tmp_path)
    assert complaint in problem and not counts


def test_cases_from_review_are_not_read_as_verdict_files(tmp_path, monkeypatch):
    (tmp_path / "from_review").mkdir()
    (tmp_path / "from_review" / "report-7.yaml").write_text(
        yaml.safe_dump(valid()), encoding="utf-8"
    )
    monkeypatch.setattr(harness, "CASES", tmp_path)
    monkeypatch.setattr(harness, "FROM_REVIEW", tmp_path / "from_review")

    found, problems, unanswered = harness.load_cases({}, {})
    assert (found, problems, unanswered) == ([], [], 0)


def test_a_well_formed_case_of_each_kind_is_counted(tmp_path):
    for kind in harness.REVIEW_KINDS:
        (tmp_path / f"{kind}-7.yaml").write_text(yaml.safe_dump(valid(kind)), encoding="utf-8")
    counts, problems = harness.load_review_cases(tmp_path)
    assert problems == [] and sum(counts.values()) == 2


def test_the_command_writes_into_the_directory_it_is_given(tmp_path):
    app = create_app(load_settings(env="testing"))
    out = tmp_path / "out"
    with app.app_context():
        result = app.test_cli_runner().invoke(args=["review", "export-cases", "--out", str(out)])
    # Runs against the development database outside any test transaction: what it
    # finds there is not this test's business, only that it answers and writes there.
    assert result.exit_code == 0, result.output
    assert f"new case(s) in {out}" in result.output and out.is_dir()
