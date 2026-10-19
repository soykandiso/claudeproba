"""New calls for subscribers (roadmap P6 s77): matched when a call is published.

A call reaches customers only when a person approves it (`review.approve_call`), so that is
when it is new: the admin calls `match_call` right after the approval is committed. Each
subscription whose paid period is running gets the call judged against the account's newest
profile by **the same function as the free shortlist** (`shortlist.ranked`: stage 1, the
citation re-check, stage 2), so an alert can never say more than the shortlist would.

An alert is written when the call is on that profile's list and the rules do not exclude it:
`eligible`, `likely_eligible` or `needs_verification`. One per subscription and call, ever
(the database's unique pair), so matching twice, or a call re-approved after a change, never
alerts twice. Sending is s78; how many at once is s81.

If matching fails, the call stays published: the admin says so, and
`flask alerts match --since DATE` matches every call published since then, harmlessly again.
"""

import datetime as dt
import logging

import click
from flask import current_app
from flask.cli import AppGroup
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.matching import normalise, shortlist
from app.models import Alert, Call, ReviewQueueItem, Subscription
from app.models.enums import ReviewKind, ReviewState, Verdict
from app.orders import numbering, subscriptions
from app.web.format import SKOPJE

log = logging.getLogger(__name__)

ALERTED = {Verdict.ELIGIBLE, Verdict.LIKELY_ELIGIBLE, Verdict.NEEDS_VERIFICATION}


def running(session: Session, today: dt.date) -> list[Subscription]:
    """Subscriptions whose paid period covers `today` (cancelled ones too, until their end)."""
    return list(
        session.scalars(
            select(Subscription).where(
                Subscription.started_on <= today, Subscription.renews_on > today
            )
        )
    )


def match_call(session: Session, call_id, now: dt.datetime | None = None) -> list[Alert]:
    """Judge one published call for every running subscription; the alerts written now."""
    now = now or numbering.now()
    today = now.astimezone(SKOPJE).date()
    call = session.get(Call, call_id)
    if call is None or not call.is_published:
        return []
    written = []
    for subscription in running(session, today):
        row = subscriptions.monitored_profile(session, subscription)
        if row is None:
            continue
        profile = normalise.from_row(row, today)
        scored, _ = shortlist.ranked(session, profile, now)
        found = next((s for s in scored if s.call.id == call.id), None)
        if found is None or found.excluded or found.outcome.verdict not in ALERTED:
            continue
        inserted = session.execute(
            insert(Alert)
            .values(
                subscription_id=subscription.id,
                call_id=call.id,
                profile_id=row.id,
                verdict=found.outcome.verdict,
            )
            .on_conflict_do_nothing(constraint="uq_alert_subscription_call")
            .returning(Alert.id)
        ).scalar()
        if inserted is not None:
            written.append(session.get(Alert, inserted))
    session.flush()
    return written


def published_since(session: Session, since: dt.datetime) -> list:
    """The calls a person approved since `since`, oldest first, each once."""
    found = list(
        session.scalars(
            select(ReviewQueueItem.call_id)
            .where(
                ReviewQueueItem.kind == ReviewKind.EXTRACTION,
                ReviewQueueItem.state.in_([ReviewState.APPROVED, ReviewState.EDITED]),
                ReviewQueueItem.resolved_at >= since,
                ReviewQueueItem.call_id.is_not(None),
            )
            .order_by(ReviewQueueItem.resolved_at)
        )
    )
    return list(dict.fromkeys(found))


def after_publish(session_factory, call_id) -> int | None:
    """Called once the approval is committed. None when matching failed (the call stays)."""
    try:
        with session_factory() as session:
            written = match_call(session, call_id)
            session.commit()
            return len(written)
    except Exception:  # matching never undoes a publication; the CLI catches up
        log.exception("call %s published but not matched for subscribers", call_id)
        return None


# ------------------------------------------------------------------ the operator's command

cli = AppGroup("alerts", help="New calls for subscribers (P6).")


@cli.command("match")
@click.option("--since", required=True, help="dd.mm.yyyy: match every call approved since then.")
def match_command(since):
    """Match calls approved since a date for every running subscription. Safe to repeat."""
    from app.db import session_factory

    day = dt.datetime.strptime(since, "%d.%m.%Y").replace(tzinfo=SKOPJE)
    sessions = session_factory(current_app.extensions["settings"])
    total = 0
    with sessions() as session:
        calls = published_since(session, day)
        for call_id in calls:
            total += len(match_call(session, call_id))
        session.commit()
    click.echo(f"{len(calls)} calls matched, {total} new alerts")
