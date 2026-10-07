"""Erasure, export and the retention job: what the privacy policy promises (P3 s45).

**Erasure anonymises; it does not delete.** An order points at its account and its profile,
and the tax law keeps invoices (docs/decisions.md D5), so an account with an order cannot
disappear. What erasure does:

- the address becomes `izbrisan-<id>@anonymised.invalid`: nobody can sign in as it, and an
  outstanding sign-in link no longer matches (app/web/account);
- every profile no order or subscription points at is deleted, with its match runs;
- a profile an order or subscription points at stays, because the report it bought must be
  reproducible, but loses its one free-text answer (the project description): the rest is
  the shape of a company (form, activity, region, bands), never an identity;
- subscriptions are cancelled;
- consent records keep what was accepted and when, and lose the IP address.

**The 24-month job** (D5) does the profile half for accounts with no activity for 24 months;
the account and its address stay, because a person who comes back should find their orders.

**Export** is the person's own data in a file they can read: the address, the consents, the
profiles. Run by them from /smetka, or by the operator from the CLI for a request by e-mail.
"""

import datetime as dt
import json

import click
from flask import current_app
from flask.cli import AppGroup
from sqlalchemy import delete, func, select, true, update
from sqlalchemy.orm import Session

from app.db import session_factory
from app.models import Account, ApplicantProfile, ConsentRecord
from app.models.commerce import Order, Subscription

RETENTION_MONTHS = 24
_FREE_TEXT = ("description",)


def _anonymised_address(account_id) -> str:
    return f"izbrisan-{account_id}@anonymised.invalid"


def _kept_profiles(session: Session, account_id) -> set:
    """Profiles an order or a subscription points at: their inputs must stay reproducible."""
    ordered = select(Order.profile_id).where(Order.account_id == account_id)
    subscribed = select(Subscription.profile_id).where(Subscription.account_id == account_id)
    return set(session.scalars(ordered.union(subscribed)))


def _forget_profiles(session: Session, account_id) -> tuple[int, int]:
    """(deleted, scrubbed): unreferenced profiles go; referenced ones lose their free text."""
    kept = _kept_profiles(session, account_id)
    deleted = session.execute(
        delete(ApplicantProfile).where(
            ApplicantProfile.account_id == account_id,
            ApplicantProfile.id.notin_(kept) if kept else true(),
        )
    ).rowcount
    scrubbed = 0
    for profile in session.scalars(select(ApplicantProfile).where(ApplicantProfile.id.in_(kept))):
        answers = {k: v for k, v in (profile.answers or {}).items() if k not in _FREE_TEXT}
        if answers != profile.answers or profile.project_description:
            profile.answers = answers
            profile.project_description = None
            scrubbed += 1
    return deleted, scrubbed


def erase(session: Session, account: Account, now: dt.datetime | None = None) -> dict:
    """Anonymise one account as described above. Idempotent."""
    now = now or dt.datetime.now(dt.UTC)
    deleted, scrubbed = _forget_profiles(session, account.id)
    session.execute(
        update(Subscription)
        .where(Subscription.account_id == account.id, Subscription.cancelled_at.is_(None))
        .values(cancelled_at=now)
    )
    session.execute(
        update(ConsentRecord).where(ConsentRecord.account_id == account.id).values(ip_address=None)
    )
    account.email = _anonymised_address(account.id)
    account.email_verified_at = None
    account.last_seen_at = None
    account.anonymised_at = account.anonymised_at or now
    session.flush()
    return {"profiles_deleted": deleted, "profiles_scrubbed": scrubbed}


def anonymise_stale(session: Session, now: dt.datetime | None = None, dry_run=False) -> list:
    """Accounts quiet for RETENTION_MONTHS: their profiles forgotten (D5), the account kept."""
    now = now or dt.datetime.now(dt.UTC)
    cutoff = now - dt.timedelta(days=round(RETENTION_MONTHS * 30.44))
    last_activity = func.coalesce(Account.last_seen_at, Account.created_at)
    stale = session.scalars(
        select(Account)
        .where(Account.anonymised_at.is_(None), last_activity < cutoff)
        .where(
            select(ApplicantProfile.id).where(ApplicantProfile.account_id == Account.id).exists()
        )
    ).all()
    done = []
    for account in stale:
        if dry_run:
            done.append((account.id, None))
            continue
        done.append((account.id, _forget_profiles(session, account.id)))
    session.flush()
    return done


def export(session: Session, account: Account) -> dict:
    """Everything the platform holds about one account, as the person can read it."""
    consents = session.scalars(
        select(ConsentRecord)
        .where(ConsentRecord.account_id == account.id)
        .order_by(ConsentRecord.created_at)
    )
    profiles = session.scalars(
        select(ApplicantProfile)
        .where(ApplicantProfile.account_id == account.id)
        .order_by(ApplicantProfile.version)
    )
    return {
        "е-пошта": account.email,
        "сметка_од": account.created_at.isoformat() if account.created_at else None,
        "последна_најава": account.last_seen_at.isoformat() if account.last_seen_at else None,
        "согласности": [
            {
                "за": c.purpose,
                "прифатено": c.granted,
                "верзија": c.policy_version,
                "кога": c.created_at.isoformat() if c.created_at else None,
                "ip_адреса": str(c.ip_address) if c.ip_address else None,
            }
            for c in consents
        ],
        "профили": [
            {
                "верзија": p.version,
                "зачуван": p.created_at.isoformat() if p.created_at else None,
                "заменет": p.superseded_at.isoformat() if p.superseded_at else None,
                "одговори": p.answers,
            }
            for p in profiles
        ],
    }


# ------------------------------------------------------------------ the operator's side

cli = AppGroup("accounts", help="Erasure, export and retention (docs/runbook.md §7).")


def _db():
    return session_factory(current_app.extensions["settings"])()


def _by_email(session, email) -> Account:
    account = session.scalar(select(Account).where(Account.email == email))
    if account is None:
        raise click.ClickException(f"no account with the address {email}")
    return account


@cli.command("erase")
@click.argument("email")
def erase_command(email):
    """Anonymise the account of EMAIL, for a request that came by e-mail."""
    with _db() as session:
        result = erase(session, _by_email(session, email))
        session.commit()
    click.echo(f"erased: {result}")


@cli.command("export")
@click.argument("email")
def export_command(email):
    """Print what is held about EMAIL as JSON, to send to them."""
    with _db() as session:
        click.echo(
            json.dumps(export(session, _by_email(session, email)), ensure_ascii=False, indent=2)
        )


@cli.command("anonymise-stale")
@click.option("--dry-run", is_flag=True, help="Only list the accounts that would be affected.")
def anonymise_stale_command(dry_run):
    """Forget the profiles of accounts with no activity for 24 months (decisions.md D5)."""
    with _db() as session:
        done = anonymise_stale(session, dry_run=dry_run)
        if not dry_run:
            session.commit()
    click.echo(f"{'would forget' if dry_run else 'forgot'} the profiles of {len(done)} account(s)")
