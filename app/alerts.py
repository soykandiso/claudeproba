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
    """Subscriptions whose paid period covers `today` and that nobody has cancelled."""
    return list(
        session.scalars(
            select(Subscription).where(
                Subscription.started_on <= today,
                Subscription.renews_on > today,
                Subscription.cancelled_at.is_(None),  # cancelling stops alerts at once (s80)
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


# ------------------------------------------------------------------ sending (P6 s78)

SHOWN_CONDITIONS = 6  # per call; the rest are on the page, the mail says how many


class SendingRefused(RuntimeError):
    """Nothing is sent: the settings would put wrong links in front of customers."""


def _item(session: Session, alert: Alert, now: dt.datetime, link) -> tuple[dict | None, str | None]:
    """What the mail says about one alert, judged again now; or why it is skipped."""
    from app.models import ApplicantProfile, Programme

    call = session.get(Call, alert.call_id)
    if call is None or not call.is_published:
        return None, "повикот не е објавен"
    if call.deadline_at is not None and call.deadline_at <= now:
        return None, "рокот на повикот истече"
    row = session.get(ApplicantProfile, alert.profile_id)
    profile = normalise.from_row(row, now.astimezone(SKOPJE).date())
    scored, citations = shortlist.ranked(session, profile, now)
    found = next((s for s in scored if s.call.id == call.id), None)
    if found is None or found.excluded or found.outcome.verdict not in ALERTED:
        return None, "повикот повеќе не одговара на профилот"
    cited = [
        (outcome, citations[outcome.criterion.id])
        for outcome in found.outcome.outcomes
        if outcome.criterion.id in citations  # no citation, no claim: not shown
    ]
    programme = session.get(Programme, call.programme_id)
    return {
        "title": call.title_mk,
        "institution": programme.institution if programme else "",
        "verdict": found.outcome.verdict,
        "deadline": call.deadline_at,
        "verified": call.last_verified_at or call.updated_at or now,
        "conditions": [
            {
                "label": outcome.criterion.label_mk,
                "verdict": outcome.verdict,
                "quote": citation.quote,
                "source_url": citation.source_url,
                "retrieved": citation.retrieved_at,
                "link": link("shortlist.passage", criterion_id=outcome.criterion.id),
            }
            for outcome, citation in cited[:SHOWN_CONDITIONS]
        ],
        "more": len(found.outcome.outcomes) - min(len(cited), SHOWN_CONDITIONS),
        "shortlist": link("shortlist.index") + f"#call-{call.id}",
        "canonical": call.canonical_url,
    }, None


def _without_theirs(item: dict) -> dict:
    blank = {"title": "…", "institution": "…", "canonical": "…"}
    conditions = [{**c, "quote": "…", "source_url": "…"} for c in item["conditions"]]
    return {**item, **blank, "conditions": conditions}


def send_pending(app, session: Session, now: dt.datetime | None = None) -> dict:
    """Mail every subscriber their unsent alerts, one message each; skip what is no longer true."""
    from flask import render_template, url_for

    from app import mail
    from app.models import Account
    from app.reports.lint import find_banned

    settings = app.extensions["settings"]
    if settings.is_production and not settings.public_url.startswith("https://"):
        raise SendingRefused("GRANTS_PUBLIC_URL must be the site's https address in production")
    now = now or numbering.now()
    unsent = session.scalars(
        select(Alert)
        .where(Alert.sent_at.is_(None), Alert.skipped_reason.is_(None))
        .order_by(Alert.subscription_id, Alert.created_at)
    ).all()
    by_subscription: dict = {}
    for alert in unsent:
        by_subscription.setdefault(alert.subscription_id, []).append(alert)

    counts = {"mailed": 0, "alerts": 0, "skipped": 0, "failed": 0}
    with app.test_request_context(base_url=settings.public_url):

        def link(endpoint, **values):
            return url_for(endpoint, _external=True, **values)

        for subscription_id, pending in by_subscription.items():
            subscription = session.get(Subscription, subscription_id)
            stop = link(
                "unsubscribe.page",
                token=subscriptions.unsubscribe_token(app.config["SECRET_KEY"], subscription.id),
            )
            items, sent = [], []
            for alert in pending:
                item, reason = _item(session, alert, now, link)
                if reason:
                    alert.skipped_reason = reason
                    counts["skipped"] += 1
                else:
                    items.append(item)
                    sent.append(alert)
            if not items:
                session.commit()
                continue
            body = render_template(
                "alerts/mail.txt",
                items=items,
                until=subscription.renews_on,
                account=link("account.home"),
                unsubscribe=stop,
            )
            # Our own words only: the institution's title, name and quotes are theirs, printed
            # as given (as the report's lint skips `data-theirs`).
            ours = render_template(
                "alerts/mail.txt",
                items=[_without_theirs(i) for i in items],
                until=subscription.renews_on,
                account=link("account.home"),
                unsubscribe=stop,
            )
            banned = find_banned(ours)
            if banned:
                log.error("alert mail for %s refused: banned phrase %s", subscription_id, banned)
                session.rollback()
                counts["failed"] += 1
                continue
            subject = (
                f"Нов повик за вашиот профил: {items[0]['title'][:80]}"
                if len(items) == 1
                else f"{len(items)} нови повици за вашиот профил"
            )
            account = session.get(Account, subscription.account_id)
            try:
                mail.send(
                    settings, account.email, subject, body, headers=mail.unsubscribe_headers(stop)
                )
            except (mail.MailNotConfigured, OSError):
                log.exception("alerts for %s not mailed; they stay unsent", subscription_id)
                session.rollback()
                counts["failed"] += 1
                continue
            for alert in sent:
                alert.sent_at = now
            subscription.last_alert_at = now
            session.commit()
            counts["mailed"] += 1
            counts["alerts"] += len(sent)
    return counts


@cli.command("send")
def send_command():
    """Mail every subscriber their unsent alerts (cron, after the morning's ingestion)."""
    from app.db import session_factory

    sessions = session_factory(current_app.extensions["settings"])
    with sessions() as session:
        counts = send_pending(current_app._get_current_object(), session)
    click.echo(
        f"{counts['mailed']} subscribers mailed ({counts['alerts']} alerts), "
        f"{counts['skipped']} skipped, {counts['failed']} not sent"
    )
