"""Signing in by e-mail link, and the account (roadmap P3 s44).

**No password anywhere.** A visitor gives an address; we mail a link; the link signs
them in. That is the whole of authentication, so it is built to be hard to misuse:

- **A link works once and for 15 minutes.** It is signed with the app's secret and
  carries the account's `last_seen_at`; signing in moves that, so a used link no longer
  matches. Nothing is stored for it: no token table, nothing to clean up or leak.
- **Opening the link does not sign anyone in; the button on it does.** Mail scanners
  open links to check them, and a sign-in on GET would be spent by the scanner.
- **The page says the same whatever the address.** Whether an account exists is not
  something a stranger can learn from the form.
- **An account is created when a link is used, not when one is asked for**, so an
  address typed by mistake, or by someone else, is never stored.
- **Asking is limited** to three links per ten minutes per browser. A browser can be
  reset, so this stops a slip of the finger, not an attacker; Caddy's rate limit is
  the second lock in production (docs/runbook.md, when it is configured).

**Saved profiles.** A signed-in visitor's profile is kept on the account: every save of
the intake form is a new version (`applicant_profile`, the old one superseded, never
edited, so a purchased report's inputs stay exact), and signing in on another device
brings the latest back.
"""

import datetime as dt
import time

from email_validator import EmailNotValidError, validate_email
from flask import Blueprint, current_app, redirect, render_template, request, session, url_for
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import func, select

from app import legal, mail
from app.config import load_settings
from app.db import session_factory
from app.matching import intake as questions
from app.matching.normalise import normalise, to_row
from app.models import Account, ApplicantProfile, ConsentRecord, EmailEvent
from app.web import csrf
from app.web.intake import ANSWERS, UNKNOWN

bp = Blueprint("account", __name__)
csrf.protect(bp)

ACCOUNT = "account_id"
LINK_MINUTES = 15
SENT = "sign_in_sent"
SENT_LIMIT, SENT_WINDOW = 3, 600


def _sessions():
    return session_factory(load_settings())


def _signer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt="sign-in-link")


def _stamp(account: Account | None) -> str:
    """What a link is bound to: the account's last sign-in, which signing in moves."""
    return account.last_seen_at.isoformat() if account and account.last_seen_at else ""


def current_account_id() -> str | None:
    return session.get(ACCOUNT)


# ------------------------------------------------------------------ asking for a link


@bp.get("/najava")
def sign_in():
    if current_account_id():
        return redirect(url_for("account.home"))
    return render_template("account/sign_in.html", sent=False, error=None, typed="")


@bp.post("/najava")
def send_link():
    typed = request.form.get("email", "").strip()
    try:
        # Reserved test domains (example.test) only outside production (RFC 6761).
        address = validate_email(
            typed,
            check_deliverability=False,
            test_environment=not current_app.extensions["settings"].is_production,
        ).normalized
    except EmailNotValidError:
        return render_template(
            "account/sign_in.html",
            sent=False,
            error="Ова не изгледа како адреса за е-пошта. Проверете ја и обидете се повторно.",
            typed=typed,
        ), 422

    now = time.time()
    recent = [t for t in session.get(SENT, []) if now - t < SENT_WINDOW]
    if len(recent) >= SENT_LIMIT:
        return render_template(
            "account/sign_in.html",
            sent=False,
            error="Побаравте неколку линкови по ред. Почекајте неколку минути и проверете ја "
            "поштата, вклучително и папката за несакана пошта.",
            typed=typed,
        ), 429
    session[SENT] = recent + [now]

    settings = current_app.extensions["settings"]
    with _sessions()() as db:
        account = db.scalar(select(Account).where(Account.email == address))
        token = _signer().dumps({"e": address, "s": _stamp(account)})
        link = url_for("account.confirm", token=token, _external=True)
        try:
            message_id = mail.send(
                settings,
                address,
                "Линк за најава",
                render_template("account/sign_in_mail.txt", link=link, minutes=LINK_MINUTES),
            )
        except mail.MailNotConfigured:
            current_app.logger.error("sign-in link not sent: mail is not configured")
            return render_template(
                "account/sign_in.html",
                sent=False,
                error="Најавата моментално не работи: не можеме да испраќаме пошта. "
                "Обидете се подоцна.",
                typed=typed,
            ), 503
        # The address of someone without an account is not kept, not even here.
        db.add(
            EmailEvent(
                account_id=account.id if account else None,
                kind="sign_in_link",
                provider_message_id=message_id,
            )
        )
        db.commit()
    return render_template("account/sign_in.html", sent=True, error=None, typed="")


# ------------------------------------------------------------------ using it


def _read(token: str) -> tuple[dict | None, str | None]:
    try:
        return _signer().loads(token, max_age=LINK_MINUTES * 60), None
    except SignatureExpired:
        return None, "Линкот истече: важи 15 минути. Побарајте нов."
    except BadSignature:
        return None, "Овој линк не е важечки. Побарајте нов."


def _needs_terms(db, account: Account | None) -> bool:
    """Whether this sign-in must accept the terms: a new account, or a new version since."""
    if account is None:
        return True
    accepted = db.scalar(
        select(ConsentRecord.policy_version)
        .where(ConsentRecord.account_id == account.id, ConsentRecord.purpose == legal.TERMS)
        .order_by(ConsentRecord.created_at.desc())
    )
    return accepted != legal.legal().version


@bp.get("/najava/<token>")
def confirm(token: str):
    payload, problem = _read(token)
    needs = False
    if payload:
        with _sessions()() as db:
            account = db.scalar(select(Account).where(Account.email == payload["e"]))
            needs = _needs_terms(db, account)
    return render_template(
        "account/confirm.html",
        token=token,
        problem=problem,
        email=payload["e"] if payload else None,
        needs_terms=needs,
        terms_error=None,
    )


@bp.post("/najava/<token>")
def use_link(token: str):
    payload, problem = _read(token)
    if problem:
        page = render_template("account/confirm.html", token=token, problem=problem, email=None)
        return page, 400
    now = dt.datetime.now(dt.UTC)
    with _sessions()() as db:
        account = db.scalar(select(Account).where(Account.email == payload["e"]))
        if payload["s"] != _stamp(account):
            return render_template(
                "account/confirm.html",
                token=token,
                email=None,
                problem="Овој линк е веќе искористен. Побарајте нов.",
            ), 400
        # The terms and the privacy notice, accepted in so many words, before any account
        # exists (P3 s45): a person who has not ticked the box is not signed in.
        needs = _needs_terms(db, account)
        if needs and request.form.get("terms") != "yes":
            page = render_template(
                "account/confirm.html",
                token=token,
                problem=None,
                email=payload["e"],
                needs_terms=True,
                terms_error="За да се најавите, потребно е да ги прифатите условите.",
            )
            return page, 422
        if account is None:
            account = Account(email=payload["e"], email_verified_at=now)
            db.add(account)
        account.email_verified_at = account.email_verified_at or now
        account.last_seen_at = now
        db.flush()
        if needs:
            db.add(
                ConsentRecord(
                    account_id=account.id,
                    purpose=legal.TERMS,
                    granted=True,
                    policy_version=legal.legal().version,
                    ip_address=request.remote_addr,
                )
            )
        _restore_profile(db, account)
        account_id = str(account.id)
        db.commit()
    # A fresh session: what an earlier visitor of this browser left does not carry over,
    # except the profile they were filling in.
    answers = session.get(ANSWERS)
    session.clear()
    if answers:
        session[ANSWERS] = answers
    session[ACCOUNT] = account_id
    session.permanent = True
    return redirect(url_for("account.home"))


@bp.post("/odjava")
def sign_out():
    session.clear()
    return redirect(url_for("public.index"))


# ------------------------------------------------------------------ the account


@bp.get("/smetka")
def home():
    account_id = current_account_id()
    if not account_id:
        return redirect(url_for("account.sign_in"))
    with _sessions()() as db:
        account = db.get(Account, account_id)
        if account is None:
            session.clear()
            return redirect(url_for("account.sign_in"))
        profile = _latest(db, account.id)
        versions = db.scalar(
            select(func.count())
            .select_from(ApplicantProfile)
            .where(ApplicantProfile.account_id == account.id)
        )
    # (label, what it was read as, no link): the grouped list, as on /profil/pregled.
    described = questions.describe(normalise(dict(profile.answers))) if profile else []
    rows = [(label, value or UNKNOWN, None) for label, value in described]
    return render_template(
        "account/home.html", account=account, profile=profile, rows=rows, versions=versions
    )


# ------------------------------------------------------------------ saved profiles


def _latest(db, account_id) -> ApplicantProfile | None:
    return db.scalar(
        select(ApplicantProfile)
        .where(ApplicantProfile.account_id == account_id, ApplicantProfile.superseded_at.is_(None))
        .order_by(ApplicantProfile.version.desc())
    )


def _restore_profile(db, account: Account) -> None:
    """On sign-in, an empty form takes the account's latest profile; a filled one is kept
    and saved, because it is the newer of the two."""
    answers = session.get(ANSWERS)
    if answers:
        save_profile(db, account.id, answers)
    else:
        latest = _latest(db, account.id)
        if latest:
            session[ANSWERS] = dict(latest.answers)


def save_profile(db, account_id, answers: dict) -> None:
    """A new version of the account's profile; the previous one superseded, never edited."""
    latest = _latest(db, account_id)
    if latest and dict(latest.answers) == dict(answers):
        return
    row = to_row(normalise(dict(answers)), account_id)
    row.version = (latest.version + 1) if latest else 1
    if latest:
        latest.superseded_at = dt.datetime.now(dt.UTC)
    db.add(row)
