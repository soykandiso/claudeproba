"""Reviewer decisions written back as evaluation cases (roadmap P2 s34).

`docs/matching.md` §6 is why this exists: the review gate is not only quality
control, it is the one source of test cases the project has no other way to get.
Every item a person **rejected or edited** becomes one file in
`evals/cases/from_review/`, `<kind>-<item id>.yaml`, the night after the decision.

What is exported, and what is not:

- **extraction** items (P1 s15) and **report** items (P2 s33), rejected or edited.
  An approval without an edit is agreement, and teaches nothing a case could hold.
- **Not** an approval item rejected because a newer one for the same call was
  approved: that is bookkeeping, not a judgement (`corrected_payload.superseded_by`).
- **Not** verification items on their own: they have no decision of their own. A
  run's failed verifications are written into its report's case, which is where a
  person read them.

A file is written **once** and never rewritten: a case is the record of a decision,
and a decision does not change. Writing is atomic (a temporary file, then a rename),
so a crash mid-run leaves no half-case for the harness to choke on, and the next
run fills in whatever is missing.

**The files leave the server** — they are pulled to a laptop and committed
(`docs/runbook.md` §7) — so nothing identifying goes in them. A report case holds
the applicant as `verify.applicant_shape` wrote it into the draft, the same bands
and codes a model is shown (invariant 4), never the answers or the profile id.
Text a person typed — the reviewer's note, an edited statement — passes the
scrubber with the account's e-mail and the profile's label as known identifiers,
because a reviewer writing the company's name into a note is the likeliest leak.
Documents are public; extraction cases name them by URL and content hash.

These are **raw material, not verdict cases**: `evals/harness.py` loads and checks
them but scores none. An extraction case is scored by tier C (s36) against the
document it names; a report case becomes a tier A case when a person writes the
expected verdict and a profile for it (`evals/README.md`).
"""

import datetime as dt
import os
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.scrub import Scrubber
from app.models import (
    Account,
    ApplicantProfile,
    Call,
    MatchRun,
    ModelCall,
    RawSnapshot,
    ReviewQueueItem,
)
from app.models.enums import ReviewKind, ReviewState
from app.review import extraction, report

CASE_VERSION = 1
KINDS = (ReviewKind.EXTRACTION, ReviewKind.REPORT)
DECISIONS = (ReviewState.REJECTED, ReviewState.EDITED)
DECISION_MK = {ReviewState.REJECTED: "одбиена", ReviewState.EDITED: "уредена"}
KIND_MK = {ReviewKind.EXTRACTION: "екстракција", ReviewKind.REPORT: "извештај"}


def file_name(item: ReviewQueueItem) -> str:
    return f"{item.kind}-{item.id}.yaml"


def exportable(session: Session) -> list[ReviewQueueItem]:
    """Every decided item a case is owed for, oldest first."""
    items = session.scalars(
        select(ReviewQueueItem)
        .where(ReviewQueueItem.kind.in_(KINDS), ReviewQueueItem.state.in_(DECISIONS))
        .order_by(ReviewQueueItem.id)
    )
    return [i for i in items if "superseded_by" not in (i.corrected_payload or {})]


def export(session: Session, out_dir: Path) -> list[Path]:
    """Write the case of every decided item that has none yet. Returns what was written."""
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for item in exportable(session):
        path = out_dir / file_name(item)
        if path.exists():
            continue
        case = case_of(session, item)
        tmp = path.with_suffix(".yaml.tmp")
        tmp.write_text(_header(item) + _dump(case), encoding="utf-8")
        os.replace(tmp, path)
        written.append(path)
    return written


def case_of(session: Session, item: ReviewQueueItem) -> dict:
    """The case as data. Kind-specific parts follow what every case shares."""
    scrubber = Scrubber(_known_identifiers(session, item))
    case = {
        "version": CASE_VERSION,
        "source": "review",
        "kind": str(item.kind),
        "item": item.id,
        "decision": str(item.state),
        "decided_at": _iso(item.resolved_at),
        "queued_because": item.reason,
        "reviewer_note": scrubber.scrub(item.reviewer_note) if item.reviewer_note else None,
        "model": _model(session, (item.payload or {}).get("model_call_id")),
    }
    if item.kind == ReviewKind.REPORT:
        case |= _report_part(session, item, scrubber)
    else:
        case |= _extraction_part(session, item, scrubber)
    return case


# -- extraction ---------------------------------------------------------------------------


def _extraction_part(session: Session, item: ReviewQueueItem, scrubber: Scrubber) -> dict:
    payload = item.payload or {}
    ids = payload.get("snapshot_ids") or (
        [payload["snapshot_id"]] if payload.get("snapshot_id") else []
    )
    part = {
        "stage": extraction.stage_of(item),
        "documents": [_document(session.get(RawSnapshot, i), i) for i in ids],
        # What the model said, before any person touched it: the thing tier C re-asks.
        "extracted": payload.get("extraction"),
        "why_it_needed_a_person": payload.get("reasons") or payload.get("errors") or None,
        "edits": _scrub_edits((item.corrected_payload or {}).get("edits") or [], scrubber),
    }
    call = session.get(Call, item.call_id) if item.call_id else None
    if item.state == ReviewState.EDITED and call is not None:
        # The reviewer's version is the truth for this document: what was published.
        part["corrected"] = {
            "title_mk": call.title_mk,
            "deadline_at": _iso(call.deadline_at),
            "criteria": [
                extraction.criterion_state(c) for c in extraction.criteria_of(session, call)
            ],
        }
    return part


def _document(snapshot: RawSnapshot | None, snapshot_id) -> dict:
    if snapshot is None:
        return {"snapshot_id": snapshot_id, "missing": True}
    return {
        "snapshot_id": snapshot.id,
        "url": snapshot.url,
        "content_sha256": snapshot.content_sha256,
        "fetched_at": _iso(snapshot.fetched_at),
        "normaliser_version": snapshot.normaliser_version,
        "text_source": str(snapshot.text_source) if snapshot.text_source else None,
    }


# -- report -------------------------------------------------------------------------------


def _report_part(session: Session, item: ReviewQueueItem, scrubber: Scrubber) -> dict:
    run = session.get(MatchRun, item.match_run_id) if item.match_run_id else None
    payload = dict(item.payload or {})
    # The draft names the run; the case keeps the versions that make it reproducible.
    return {
        "run": {
            "match_run_id": str(run.id),
            "ruleset_version": run.ruleset_version,
            "weights_version": run.weights_version,
        }
        if run
        else None,
        "applicant": payload.pop("applicant", None),
        # As composed: verdicts, conditions with their citations, the model's prose,
        # and the problems the checks found. `edits` says what the reviewer changed.
        "draft": payload,
        "edits": _scrub_edits((item.corrected_payload or {}).get("edits") or [], scrubber),
        "failed_verifications": [
            {
                "item": v.id,
                "why": v.reason,
                "criterion": (v.payload or {}).get("criterion"),
                "criterion_id": (v.payload or {}).get("criterion_id"),
                "answer": (v.payload or {}).get("answer"),
                "passages": (v.payload or {}).get("passages"),
            }
            for v in report.verification_failures(session, item)
        ],
    }


# -- shared -------------------------------------------------------------------------------


def _known_identifiers(session: Session, item: ReviewQueueItem) -> list[str]:
    """What names the customer behind a report: never written to a case."""
    if item.match_run_id is None:
        return []
    row = session.execute(
        select(Account.email, ApplicantProfile.label)
        .join(ApplicantProfile, ApplicantProfile.account_id == Account.id)
        .join(MatchRun, MatchRun.profile_id == ApplicantProfile.id)
        .where(MatchRun.id == item.match_run_id)
    ).first()
    return [v for v in (row or ()) if v]


def _scrub_edits(edits: list[dict], scrubber: Scrubber) -> list[dict]:
    """A person typed every `after`: the scrubber reads its text, whatever its shape."""

    def scrub(value):
        if isinstance(value, str):
            return scrubber.scrub(value)
        if isinstance(value, dict):
            return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list):
            return [scrub(v) for v in value]
        return value

    return [edit | {"after": scrub(edit.get("after"))} for edit in edits]


def _model(session: Session, model_call_id) -> dict | None:
    if not model_call_id:
        return None
    call = session.get(ModelCall, model_call_id)
    if call is None:
        return {"model_call_id": model_call_id, "missing": True}
    return {
        "model_call_id": call.id,
        "task": call.task,
        "prompt_version": call.prompt_version_id,
        "model": call.model,
    }


def _header(item: ReviewQueueItem) -> str:
    decided = item.resolved_at.strftime("%d.%m.%Y") if item.resolved_at else "—"
    return (
        f"# Ставка {item.id} од редот за преглед: {KIND_MK[item.kind]}, "
        f"{DECISION_MK[item.state]} на {decided}.\n"
        "# Создадено автоматски од app/review/cases.py; не се уредува рачно.\n"
    )


class _Dumper(yaml.SafeDumper):
    """Multi-line text (the applicant's shape, a long note) as a block a person can read."""


_Dumper.add_representer(
    str,
    lambda dumper, value: dumper.represent_scalar(
        "tag:yaml.org,2002:str", value, style="|" if "\n" in value else None
    ),
)


def _dump(case: dict) -> str:
    return yaml.dump(case, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=100)


def _iso(value: dt.datetime | None) -> str | None:
    return value.isoformat() if value else None
