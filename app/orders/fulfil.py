"""From a paid order to a report draft in the review queue (roadmap P4 s52).

A paid order is analysed by the worker on the `analysis` queue, exactly as `app/matching/deep.py`
does any profile: the first five open calls of the shortlist the order's profile has the moment
the job runs, verified, then composed into a draft a person reviews. This module adds only what
belongs to the order: its state, and which run it paid for.

**Payment never waits on Redis.** Marking an order paid commits first; handing it to the worker
comes after and may fail (Redis down, a deploy in progress). Nothing is lost when it does: every
ten minutes `flask orders dispatch` hands over every order still `paid`, so the worst case is a
late start, never a forgotten order. A job has the order's own id (`order-<uuid>`), so the
sweep and the payment can both try without the analysis running twice.

**A failed job is not retried by itself.** It has already moved the order to `in_progress`, so
the sweep leaves it alone, and RQ keeps the failure for a person to read. Running a report
again costs model calls; `flask orders retry ORDER` is that decision, taken by the operator.

States: `paid` → (job starts) `in_progress` → (s53, the reviewed report sent) `delivered`.
"""

import logging
import uuid

import click
from flask import current_app
from flask.cli import AppGroup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.commerce import Order
from app.models.enums import OrderState
from app.orders import service, states

log = logging.getLogger(__name__)

# RQ statuses of a job that is still going to run or is running: the sweep leaves it be.
_LIVE = {"queued", "started", "deferred", "scheduled"}


def job_id(order_id) -> str:
    return f"order-{order_id}"


def begin(session: Session, order_id) -> uuid.UUID | None:
    """Move a paid order to in_progress and return the profile to analyse, or None to skip.

    An order already in progress with no run is a retry the operator asked for; anything
    else (cancelled, delivered, analysed already) is left as it is.
    """
    order = session.get(Order, order_id)
    if order is None:
        raise LookupError(f"no order {order_id}")
    if order.state == OrderState.PAID:
        states.move(order, OrderState.IN_PROGRESS)
    elif not (order.state == OrderState.IN_PROGRESS and order.match_run_id is None):
        return None
    session.commit()
    return order.profile_id


def link(session: Session, order_id, match_run_id) -> None:
    """Record which run the order paid for: the report is reproducible from it."""
    session.get(Order, order_id).match_run_id = match_run_id
    session.commit()


def job(order_id: str) -> dict:
    """What the RQ worker runs for a paid order."""
    from app.config import load_settings
    from app.db import session_factory
    from app.matching import deep

    settings = load_settings()
    sessions = session_factory(settings)
    with sessions() as session:
        sku = service.sku_of(session, session.get(Order, uuid.UUID(str(order_id))))
        if sku == service.PACKAGE:
            return package_job(session, settings, uuid.UUID(str(order_id)))
        if sku in (service.MONTH, service.YEAR):
            return subscription_job(session, settings, uuid.UUID(str(order_id)))
        profile_id = begin(session, uuid.UUID(str(order_id)))
    if profile_id is None:
        return {"order": str(order_id), "skipped": True}
    result = deep.job(str(profile_id))
    with sessions() as session:
        link(session, uuid.UUID(str(order_id)), uuid.UUID(result["match_run_id"]))
    return {"order": str(order_id), **result}


def package_job(session: Session, settings, order_id) -> dict:
    """A paid package order: made, stored and queued for review (P5 s75). Made once."""
    from app.documents import packages
    from app.ingestion.snapshots import SnapshotStore
    from app.models import ReviewQueueItem
    from app.models.enums import ReviewKind
    from app.orders import numbering

    made = session.scalar(
        select(ReviewQueueItem.id).where(
            ReviewQueueItem.order_id == order_id,
            ReviewQueueItem.kind == ReviewKind.DOCUMENT_PACKAGE,
        )
    )
    if made is not None or begin(session, order_id) is None:
        return {"order": str(order_id), "skipped": True}
    item = packages.prepare(
        session, SnapshotStore(settings.snapshot_dir), order_id, numbering.today()
    )
    session.commit()
    return {"order": str(order_id), "review_item_id": item}


def subscription_job(session: Session, settings, order_id) -> dict:
    """A paid monitoring order starts or extends its subscription (P6 s76). Once."""
    from app.ingestion.snapshots import SnapshotStore
    from app.orders import subscriptions

    if session.get(Order, order_id).state != OrderState.PAID:
        return {"order": str(order_id), "skipped": True}
    done = subscriptions.activate(session, SnapshotStore(settings.snapshot_dir), settings, order_id)
    return {
        "order": str(order_id),
        "subscription": str(done.subscription_id),
        "until": done.until.isoformat(),
    }


def _queue(settings):
    from redis import Redis
    from rq import Queue

    from app.matching import deep

    return Queue(deep.QUEUE, connection=Redis.from_url(settings.redis_url, socket_timeout=5))


def enqueue(settings, order_id, *, again: bool = False) -> bool:
    """Hand an order to the worker; False when a job for it already exists.

    Raises when Redis cannot be reached: the caller decides whether that matters (the
    payment screen does not; the sweep will try again).
    """
    from rq.exceptions import NoSuchJobError
    from rq.job import Job

    from app.matching import deep

    queue = _queue(settings)
    try:
        existing = Job.fetch(job_id(order_id), connection=queue.connection)
    except NoSuchJobError:
        existing = None
    if existing is not None:
        if not again or existing.get_status() in _LIVE:
            return False
        existing.delete()
    queue.enqueue(
        job,
        str(order_id),
        job_id=job_id(order_id),
        job_timeout=deep.JOB_TIMEOUT_S,
        description=f"order {order_id}",
    )
    return True


def waiting(session: Session) -> list[uuid.UUID]:
    """Paid orders the worker has not started, oldest first."""
    return list(
        session.scalars(
            select(Order.id).where(Order.state == OrderState.PAID).order_by(Order.created_at)
        )
    )


def dispatch(settings, session: Session) -> tuple[int, int]:
    """Hand every waiting order to the worker: (handed over now, already queued)."""
    handed = already = 0
    for order_id in waiting(session):
        if enqueue(settings, order_id):
            handed += 1
        else:
            already += 1
    return handed, already


def after_payment(settings, order_id) -> bool:
    """Called once the payment is committed. False when the worker could not be told yet."""
    try:
        enqueue(settings, order_id)
        return True
    except Exception:  # Redis down or unreachable: the sweep hands it over later
        log.exception("order %s paid but not queued; `flask orders dispatch` will", order_id)
        return False


# ------------------------------------------------------------------ the operator's commands

cli = AppGroup("orders", help="Paid orders and the analysis worker (docs/runbook.md).")


def _sessions():
    from app.db import session_factory

    return session_factory(current_app.extensions["settings"])


@cli.command("dispatch")
def dispatch_command():
    """Hand every paid order the worker has not started to it (cron, every 10 minutes)."""
    with _sessions()() as session:
        handed, already = dispatch(current_app.extensions["settings"], session)
    click.echo(f"{handed} handed to the worker, {already} already queued")


@cli.command("retry")
@click.argument("order_id", type=click.UUID)
def retry_command(order_id):
    """Run the analysis of an order again after a failed job. Costs model calls."""
    with _sessions()() as session:
        order = session.get(Order, order_id)
        if order is None:
            raise click.ClickException(f"no order {order_id}")
        if order.state not in (OrderState.PAID, OrderState.IN_PROGRESS) or order.match_run_id:
            raise click.ClickException(
                f"order {order_id} is {order.state} with run {order.match_run_id}: nothing to retry"
            )
    if enqueue(current_app.extensions["settings"], order_id, again=True):
        click.echo(f"order {order_id} handed to the worker again")
    else:
        click.echo(f"order {order_id} is already queued or running")
