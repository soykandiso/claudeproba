"""The paid report's draft: a stored stage-3 run, explained in Macedonian, then checked (P2 s32).

docs/architecture.md §6, docs/matching.md §6. After `deep.run` has stored a run,
`compose` turns it into a draft and puts it in the review queue. Two things are
kept strictly apart:

- **What the report decides is written by code, from the stored rows only**: each
  call's verdict, every condition with its outcome and reason, the call's own
  words at their offsets, the model's evidence, the source URL and the date it
  was fetched. Nothing is re-run, so a draft read a year from now says what the
  run found then (architecture §4, reproducibility).
- **What the model writes is explanation**: a summary and, per call, what the
  verdict means and what to do next (`ReportProse`). Every one of its statements
  names the conditions it rests on, by the number the prompt gave them.

Then two checks run over the whole draft, and **either one blocks delivery**:

1. **The banned-phrase lint** (`app/reports/lint.py`) over every sentence the
   report says in its own voice: the model's prose, and the labels and reasons
   beside each condition — verification's reasons are model Macedonian too. The
   quotes and the call titles are not linted: they are the institution's own
   words, a reviewer cannot change them, and a customer reads them as quoted.
2. **Citation completeness** (invariant 2): every condition resolves to a stored
   snapshot whose text at `(char_start, char_end)` is the quote, with a source URL
   and a retrieval date; every model answer that decided a condition has its
   evidence, found the same way; every statement cites at least one condition,
   and only conditions of the call it is about.

A blocked draft is still queued — the review queue is where all uncertainty goes
(CLAUDE.md) — with its problems listed and a higher priority. `blockers()` runs
the same checks again on whatever the reviewer's edit leaves (s33 edits, s35
delivers), so a draft that was clean cannot be edited into one that says
"гарантирано" and still be sent.

**No identity data reaches the model** (invariant 4): the applicant goes as
`verify.applicant_shape`, and the gateway scrubs again.

**What the checks cannot see**: whether a sentence says more than its conditions
do. A statement citing a "needs verification" condition may still read as a
promise in other words; that is the human review's to catch (every AI-produced
Macedonian is reviewed before a customer reads it, CLAUDE.md).
"""

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.gateway import Gateway, InvalidModelOutput
from app.ai.schemas import ReportProse
from app.matching import normalise, verify
from app.models import (
    ApplicantProfile,
    Call,
    EligibilityCriterion,
    Evidence,
    MatchCriterionOutcome,
    MatchResult,
    MatchRun,
    Programme,
    RawSnapshot,
    ReviewQueueItem,
)
from app.models.enums import ReviewKind, Verdict
from app.reports.lint import find_banned
from app.web.format import CRITERION_LABELS, VERDICT_LABELS, mkdate

TASK = "compose_report"

# The shape of `payload` in a report review item. Bump when it changes, so s33's
# screen and s35's renderer can refuse a draft they do not know how to read.
DRAFT_VERSION = 1

# A blocked draft is looked at before a clean one (review_queue_item.priority, lower first).
PRIORITY_BLOCKED = 50
PRIORITY_READY = 100

DECIDED_BY_MK = {
    "rule": "правило",
    "model": "проверка на текстот",
    "applicant": "го потврдува апликантот",
}


# ------------------------------------------------------------------ the draft, from stored rows


def _citation(snapshot_id, start, end, quote, url, fetched_at) -> dict:
    return {
        "snapshot_id": snapshot_id,
        "char_start": start,
        "char_end": end,
        "quote": quote,
        "source_url": url,
        "retrieved_at": fetched_at.isoformat() if fetched_at else None,
    }


def _conditions(session: Session, result_id: int) -> list[dict]:
    rows = session.execute(
        select(
            MatchCriterionOutcome,
            EligibilityCriterion,
            func.coalesce(EligibilityCriterion.source_url, RawSnapshot.url),
            RawSnapshot.fetched_at,
        )
        .join(EligibilityCriterion, EligibilityCriterion.id == MatchCriterionOutcome.criterion_id)
        .outerjoin(RawSnapshot, RawSnapshot.id == EligibilityCriterion.snapshot_id)
        .where(MatchCriterionOutcome.match_result_id == result_id)
        .order_by(MatchCriterionOutcome.id)
    ).all()
    evidence = {
        e.outcome_id: (e, fetched)
        for e, fetched in session.execute(
            select(Evidence, RawSnapshot.fetched_at)
            .join(RawSnapshot, RawSnapshot.id == Evidence.snapshot_id)
            .where(Evidence.outcome_id.in_([o.id for o, *_ in rows]))
        ).all()
    }
    conditions = []
    for outcome, criterion, url, fetched in rows:
        found = evidence.get(outcome.id)
        conditions.append(
            {
                "criterion_id": str(criterion.id),
                "kind": criterion.kind.value,
                "label": criterion.label_mk,
                "verdict": outcome.verdict.value,
                "decided_by": outcome.decided_by,
                "reason": outcome.reason_mk,
                "confidence": float(outcome.confidence) if outcome.confidence else None,
                "citation": _citation(
                    criterion.snapshot_id,
                    criterion.quote_start,
                    criterion.quote_end,
                    criterion.source_quote,
                    url,
                    fetched,
                )
                if criterion.snapshot_id is not None
                else None,
                "evidence": _citation(
                    found[0].snapshot_id,
                    found[0].char_start,
                    found[0].char_end,
                    found[0].quote,
                    found[0].source_url,
                    found[1],
                )
                if found
                else None,
            }
        )
    return conditions


def load(session: Session, match_run_id: uuid.UUID) -> dict:
    """Everything the report decides, read from one stored run. No prose yet."""
    run = session.get(MatchRun, match_run_id)
    if run is None:
        raise LookupError(f"no match_run {match_run_id}")
    if run.stage_reached < 3:
        raise ValueError(f"match_run {match_run_id} did not finish stage 3")
    profile = normalise.from_row(
        session.get(ApplicantProfile, run.profile_id), run.created_at.date()
    )

    rows = session.execute(
        select(MatchResult, Call, Programme.institution)
        .join(Call, Call.id == MatchResult.call_id)
        .join(Programme, Programme.id == Call.programme_id)
        .where(MatchResult.match_run_id == run.id)
        .order_by(MatchResult.rank)
    ).all()
    calls, excluded = [], []
    for result, call, institution in rows:
        entry = {
            "call_id": str(call.id),
            "title": call.title_mk,
            "institution": institution,
            "url": call.canonical_url,
            "deadline": call.deadline_at.isoformat() if call.deadline_at else None,
            "verdict": result.verdict.value,
            "rank": result.rank,
            "conditions": _conditions(session, result.id),
        }
        if result.verdict == Verdict.NOT_ELIGIBLE:
            # Only the conditions that exclude: the rest is not what the customer needs.
            entry["conditions"] = [
                c for c in entry["conditions"] if c["verdict"] == Verdict.NOT_ELIGIBLE.value
            ]
            excluded.append(entry)
            continue
        number = len(calls) + 1
        for m, condition in enumerate(entry["conditions"], 1):
            condition["ref"] = f"{number}.{m}"
        calls.append({**entry, "number": number, "explanation": [], "next_steps": []})

    return {
        "version": DRAFT_VERSION,
        "match_run_id": str(run.id),
        "run_date": run.created_at.date().isoformat(),
        "applicant": verify.applicant_shape(profile),
        "candidates_considered": run.candidates_considered,
        "summary": [],
        "calls": calls,
        "excluded": excluded,
        "unplaced": [],
    }


# ------------------------------------------------------------------ what the model is shown


def _deadline(value: str | None) -> str:
    # A deadline is an instant; the day it falls on is Skopje's (app/web/format.py).
    return mkdate(dt.datetime.fromisoformat(value)) if value else "не е објавен"


def render_calls(draft: dict) -> str:
    """The verified calls as the prompt numbers them, conditions included."""
    blocks = []
    for call in draft["calls"]:
        lines = [
            f'<call number="{call["number"]}">',
            f"Повик: {call['title']}",
            f"Институција: {call['institution']}",
            f"Рок: {_deadline(call['deadline'])}",
            f"Оценка: {VERDICT_LABELS[Verdict(call['verdict'])]}",
        ]
        for c in call["conditions"]:
            lines += [
                f'<condition number="{c["ref"]}">',
                f"Услов: {c['label']}",
                f"Исход: {CRITERION_LABELS[Verdict(c['verdict'])]} "
                f"({DECIDED_BY_MK.get(c['decided_by'], c['decided_by'])})",
                f"Образложение: {c['reason']}",
                f"Зборовите на повикот: «{c['citation']['quote'] if c['citation'] else ''}»",
                "</condition>",
            ]
        lines.append("</call>")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def attach(draft: dict, prose: ReportProse) -> dict:
    """Place the model's prose beside the calls it names; keep what names nothing."""
    by_number = {call["number"]: call for call in draft["calls"]}
    draft["summary"] = [s.model_dump() for s in prose.summary]
    for section in prose.calls:
        call = by_number.get(section.call)
        if call is None:
            draft["unplaced"].append(section.model_dump())
            continue
        call["explanation"] = [s.model_dump() for s in section.explanation]
        call["next_steps"] = [s.model_dump() for s in section.next_steps]
    return draft


# ------------------------------------------------------------------ the checks


def _problem(check: str, where: str, detail: str) -> dict:
    return {"check": check, "where": where, "detail": detail}


def _statements(draft: dict):
    """(where, statement, refs it may cite) for every statement of prose."""
    every = {c["ref"] for call in draft["calls"] for c in call["conditions"]}
    for n, s in enumerate(draft["summary"], 1):
        yield f"summary {n}", s, every
    for call in draft["calls"]:
        own = {c["ref"] for c in call["conditions"]}
        for part in ("explanation", "next_steps"):
            for n, s in enumerate(call[part], 1):
                yield f"call {call['number']} {part} {n}", s, own


def _own_voice(draft: dict):
    """(where, text) for everything the report says in its own words."""
    for where, statement, _ in _statements(draft):
        yield where, statement["text_mk"]
    for call in [*draft["calls"], *draft["excluded"]]:
        for c in call["conditions"]:
            where = f"condition {c.get('ref') or c['criterion_id']}"
            yield f"{where} label", c["label"] or ""
            yield f"{where} reason", c["reason"] or ""


def lint(draft: dict) -> list[dict]:
    return [
        _problem("lint", where, f"banned phrase: {label}")
        for where, text in _own_voice(draft)
        for label in find_banned(text)
    ]


def _resolves(texts: dict[int, str], citation: dict | None) -> str | None:
    """Why a citation cannot be shown, or None when it can."""
    if citation is None:
        return "no citation"
    if not citation.get("source_url") or not citation.get("retrieved_at"):
        return "no source URL or retrieval date"
    text = texts.get(citation["snapshot_id"])
    if text is None:
        return f"snapshot {citation['snapshot_id']} has no stored text"
    if text[citation["char_start"] : citation["char_end"]] != citation["quote"]:
        return f"the quote is not at {citation['char_start']}–{citation['char_end']}"
    return None


def citations(session: Session, draft: dict) -> list[dict]:
    """Invariant 2 over the whole draft, against the stored text."""
    conditions = [
        (c.get("ref") or c["criterion_id"], c)
        for call in [*draft["calls"], *draft["excluded"]]
        for c in call["conditions"]
    ]
    ids = {
        cit["snapshot_id"]
        for _, c in conditions
        for cit in (c["citation"], c["evidence"])
        if cit and cit.get("snapshot_id") is not None
    }
    texts = dict(
        session.execute(
            select(RawSnapshot.id, RawSnapshot.normalised_text).where(RawSnapshot.id.in_(ids))
        ).all()
    )
    problems = []
    for ref, c in conditions:
        why = _resolves(texts, c["citation"])
        if why:
            problems.append(_problem("citation", f"condition {ref}", why))
        # A model that decided a condition must show the words it decided on;
        # an undecided one may have none (verify.py keeps low-confidence evidence).
        decided = c["decided_by"] == "model" and c["verdict"] != Verdict.NEEDS_VERIFICATION.value
        if c["evidence"] is not None or decided:
            why = _resolves(texts, c["evidence"])
            if why:
                problems.append(_problem("citation", f"condition {ref} evidence", why))

    for where, statement, allowed in _statements(draft):
        refs = statement.get("cites") or []
        if not refs:
            problems.append(_problem("citation", where, "a statement that cites nothing"))
        for ref in refs:
            if ref not in allowed:
                problems.append(_problem("citation", where, f"cites {ref}, not a condition here"))
    for section in draft["unplaced"]:
        problems.append(
            _problem("citation", f"section for call {section['call']}", "there is no such call")
        )
    for call in draft["calls"]:
        if not call["explanation"]:
            problems.append(_problem("citation", f"call {call['number']}", "no explanation"))
    return problems


def check(session: Session, draft: dict) -> list[dict]:
    """Every reason this draft cannot be delivered; empty when it can go to a customer
    after a person has approved it."""
    if draft.get("version") != DRAFT_VERSION:
        return [_problem("version", "draft", f"unknown draft version {draft.get('version')}")]
    return lint(draft) + citations(session, draft)


def blockers(session: Session, item: ReviewQueueItem) -> list[dict]:
    """The checks again, over what a reviewer's edit left (or the draft as composed)."""
    if item.kind != ReviewKind.REPORT:
        raise ValueError(f"review item {item.id} is not a report")
    return check(session, item.corrected_payload or item.payload)


# ------------------------------------------------------------------ composing


def compose(session_factory, gateway: Gateway, match_run_id: uuid.UUID) -> int:
    """Draft one run's report and queue it for review. Returns the review item's id.

    Output the gateway cannot validate twice is already a `report` review item
    (invariant 5); its id is returned and nothing else is written. A provider
    failure propagates, as in `deep.run`.
    """
    with session_factory() as session:
        draft = load(session, match_run_id)

    model_call_id = None
    if draft["calls"]:
        try:
            result = gateway.run(
                TASK,
                variables={"applicant": draft["applicant"], "calls": render_calls(draft)},
                response_model=ReportProse,
                on_invalid=ReviewKind.REPORT,
                match_run_id=match_run_id,
            )
        except InvalidModelOutput as exc:
            return exc.review_item_id
        attach(draft, result.output)
        model_call_id = result.model_call_id
    draft["model_call_id"] = model_call_id

    with session_factory() as session:
        problems = check(session, draft)
        draft["problems"] = problems
        blocked = sorted({p["check"] for p in problems})
        item = ReviewQueueItem(
            kind=ReviewKind.REPORT,
            match_run_id=match_run_id,
            priority=PRIORITY_BLOCKED if problems else PRIORITY_READY,
            reason=(
                f"{TASK}: blocked, {len(problems)} problem(s): {', '.join(blocked)}"
                if problems
                else f"{TASK}: draft ready for review"
            ),
            payload=draft,
        )
        session.add(item)
        session.commit()
        return item.id
