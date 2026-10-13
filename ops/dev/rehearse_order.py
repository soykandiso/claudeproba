"""A dress rehearsal of roadmap P4 s55 on the development machine. Refuses production.

    PYTHONPATH=. uv run python ops/dev/rehearse_order.py [--out var/proba]

Brief §14's path, through the real screens and the real modules: a buyer signs in by link,
orders a report and gets the proforma; the operator marks the transfer paid from a statement
line; the analysis runs (the worker's job, run here in-process, with the evaluation's
recorded model answers instead of a model); the operator approves the draft; the buyer gets
the report and the invoice, and downloads both from the order page. Then the invoice series
is audited.

**Nothing stays in the database.** It all runs in one transaction that is rolled back at the
end, on the evaluation suite's clock (`evals/suite.yaml` `as_of`, plus two days), because
the frozen calls have since closed and delivery rightly refuses a closed call. What is kept
is what a buyer and an accountant would see, in `--out`: the e-mails as sent, every PDF
attached to them, and `checklist.txt`, one line per step.

The real rehearsal (s55) is the user's: a real profile, a real bank transfer, the real VPS.
"""

import argparse
import datetime as dt
import email
import importlib.util
import re
import shutil
from decimal import Decimal
from email.header import decode_header, make_header
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app import create_app
from app.ai.gateway import Gateway
from app.config import load_settings
from app.ingestion.snapshots import SnapshotStore
from app.matching import deep, normalise
from app.models import Account
from app.models.commerce import Invoice, Order
from app.models.enums import InvoiceKind, OrderState
from app.orders import fulfil, numbering
from app.reports import compose
from evals import harness, tier_b

PROFILE = "p02_bitola_bakery_small"
BUYER = {
    "name": "Проба Пекара ДООЕЛ Битола",
    "address": "ул. Пробна 1, 7000 Битола",
    "edb": "",
    "embs": "",
}
HERE = Path(__file__).resolve().parent


def _seed_report():
    spec = importlib.util.spec_from_file_location("seed_report", HERE / "seed_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Steps:
    """The checklist: each step said once, and the first failure stops the rehearsal."""

    def __init__(self):
        self.lines = []

    def check(self, ok: bool, said: str):
        self.lines.append(f"{'✓' if ok else '✗'} {said}")
        print(self.lines[-1])
        if not ok:
            raise SystemExit(f"stopped at: {said}")


def _newest(outbox: Path, seen: set) -> email.message.Message:
    fresh = sorted(set(outbox.glob("*.eml")) - seen, key=lambda p: p.stat().st_mtime)
    seen.update(fresh)
    return email.message_from_bytes(fresh[-1].read_bytes())


def _body(message) -> str:
    part = next(p for p in message.walk() if p.get_content_type() == "text/plain")
    return part.get_payload(decode=True).decode()


def _pdfs(message) -> dict[str, bytes]:
    return {
        str(make_header(decode_header(p.get_filename()))): p.get_payload(decode=True)
        for p in message.walk()
        if p.get_content_type() == "application/pdf"
    }


def rehearse(factory, out: Path, *, profile: str = PROFILE) -> list[str]:
    """Run the whole path on `factory` (whose transaction the caller rolls back)."""
    import app.web.account as account_web
    import app.web.admin as admin
    import app.web.checkout as checkout

    as_of = harness.load_suite()["as_of"]
    clock = dt.datetime.combine(as_of + dt.timedelta(days=2), dt.time(9), dt.UTC)
    out.mkdir(parents=True, exist_ok=True)
    outbox, store = out / "outbox", SnapshotStore(out / "store")
    settings = load_settings(outbox_dir=str(outbox), snapshot_dir=str(store.root))
    steps, seen, handed = Steps(), set(), []

    saved = {
        (account_web, "_sessions"): account_web._sessions,
        (checkout, "_sessions"): checkout._sessions,
        (admin, "_sessions"): admin._sessions,
        (admin, "_store"): admin._store,
        (admin, "_now"): admin._now,
        (numbering, "now"): numbering.now,
        (fulfil, "enqueue"): fulfil.enqueue,
    }
    account_web._sessions = checkout._sessions = admin._sessions = lambda: factory
    admin._store = lambda: store
    admin._now = numbering.now = lambda: clock
    fulfil.enqueue = lambda settings, order_id, **_: handed.append(order_id) or True
    try:
        with factory() as s:
            fixtures = harness.load_fixtures()
            calls = harness.load_registry(s, fixtures)
            s.commit()
        client = create_app(settings).test_client()

        def csrf() -> dict:
            # The session's token; signing in starts a new session, and with it a new token.
            with client.session_transaction() as session:
                return {"csrf": session.setdefault("csrf", "rehearsal")}

        # 1. The buyer signs in by link.
        address = f"proba-{clock:%Y%m%d}@example.test"
        client.post("/najava", data={**csrf(), "email": address})
        link = re.search(r"http://localhost/(najava/\S+)", _body(_newest(outbox, seen))).group(1)
        signed = client.post(f"/{link}", data={**csrf(), "terms": "yes"})
        steps.check(signed.status_code == 302, f"sign-in link reached {address} and signed in")

        # 2. Their profile, as the evaluation profile's answers (the intake has its own tests).
        with factory() as s:
            account = s.scalar(select(Account).where(Account.email == address))
            answers = harness.load_profiles()[profile].answers
            s.add(normalise.to_row(normalise.normalise(answers, as_of), account.id))
            s.commit()

        # 3. The order and the proforma.
        form = client.get("/naracka/").get_data(as_text=True)
        steps.check("првите пет отворени повици" in form, "the order form says what is bought")
        placed = client.post("/naracka/", data={**csrf(), **BUYER})
        steps.check("sent=1" in placed.location, "order placed, proforma e-mailed")
        sent = _newest(outbox, seen)
        (out / "1-profaktura.pdf").write_bytes(next(iter(_pdfs(sent).values())))
        order_id = placed.location.split("/naracka/")[1].split("?")[0]
        with factory() as s:
            proforma = s.scalar(
                select(Invoice).where(
                    Invoice.order_id == order_id, Invoice.kind == InvoiceKind.PROFORMA
                )
            )
            number, total = proforma.number, Decimal(proforma.total_mkd)
        steps.check(
            proforma.issued_at == clock.date(),
            f"proforma {number}, {total:.2f} МКД, dated {clock:%d.%m.%Y}",
        )

        # 4. The transfer, from a statement line as a bank writes it.
        line = (
            f"PROBA PEKARA DOOEL, uplata po {number.replace('ПФ', 'PF')}, {total:.2f} MKD".replace(
                ".", ","
            )
        )
        found = client.get("/admin/uplati", query_string={"line": line}).get_data(as_text=True)
        steps.check(
            "се совпаѓа" in found, f"statement line «{line}» found the proforma and its amount"
        )
        paid = client.post(
            [m for m in re.findall(r'action="(/admin/uplati/[^"]+)"', found)][0],
            data={
                **csrf(),
                "line": line,
                "amount": f"{total:.2f}",
                "reference": line,
                "date": f"{clock:%d.%m.%Y}",
            },
            follow_redirects=True,
        ).get_data(as_text=True)
        steps.check(
            "Купувачот е известен" in paid, "payment marked; the buyer told what happens and when"
        )
        (out / "2-uplata.txt").write_text(_body(_newest(outbox, seen)), encoding="utf-8")
        steps.check(
            [str(o) for o in handed] == [order_id], "the order handed to the analysis worker"
        )

        # 5. The worker's job, here: the evaluation's recorded answers stand in for the model.
        with factory() as s:
            profile_id = fulfil.begin(s, order_id)
        seed = _seed_report()
        slug_of = {call.id: slug for slug, call in calls.items()}
        provider = tier_b.CassetteProvider(tier_b.load_cassettes(), profile=profile)
        fixture_retriever = tier_b.FixtureRetriever(
            {c.id: (c.primary_snapshot_id, fixtures[slug].text) for slug, c in calls.items()}
        )

        def retriever_for(session):
            def retrieve(call, criterion):
                provider.call = slug_of[call.id]
                return fixture_retriever(call, criterion)

            return retrieve

        report = deep.run(factory, Gateway(factory, provider), retriever_for, profile_id, clock)
        prose = seed.ScriptedProse(blocked=False)
        with factory() as s:
            draft = compose.load(s, report.match_run_id)
        prose.refs = [[c["ref"] for c in call["conditions"]] for call in draft["calls"]]
        item_id = compose.compose(
            factory, seed.Uncached(factory, prose), report.match_run_id, today=clock.date()
        )
        with factory() as s:
            fulfil.link(s, order_id, report.match_run_id)
        steps.check(
            item_id is not None,
            f"analysis ran over {len(report.ranked)} calls; draft {item_id} queued for review",
        )

        # 6. A person approves; approval sends it.
        page = client.get(f"/admin/izveshtaj/{item_id}").get_data(as_text=True)
        steps.check(
            "Платена нарачка" in page, "the review page says approving sends it to a paying buyer"
        )
        approved = client.post(
            f"/admin/izveshtaj/{item_id}/odobri", data=csrf(), follow_redirects=True
        )
        steps.check(
            "Извештајот е испратен на" in approved.get_data(as_text=True), "approved and delivered"
        )
        delivered = _newest(outbox, seen)
        for n, (name, content) in enumerate(_pdfs(delivered).items(), 3):
            (out / f"{n}-{name}").write_bytes(content)
        (out / "5-isporaka.txt").write_text(_body(delivered), encoding="utf-8")

        # 7. The buyer's page, and the series.
        mine = client.get(f"/naracka/{order_id}").get_data(as_text=True)
        report_pdf = client.get(f"/naracka/{order_id}/izveshtaj.pdf").data
        steps.check(
            "Испорачана" in mine and report_pdf.startswith(b"%PDF"),
            "the buyer's page offers what was sent",
        )
        with factory() as s:
            order = s.get(Order, order_id)
            steps.check(order.state == OrderState.DELIVERED, f"order {number}: {order.state}")
            problems = [p for p in numbering.audit(s) if str(clock.year) in p]
        steps.check(
            not problems, "every invoice series is whole" if not problems else "; ".join(problems)
        )
    finally:
        for (module, name), value in saved.items():
            setattr(module, name, value)
    (out / "checklist.txt").write_text("\n".join(steps.lines) + "\n", encoding="utf-8")
    return steps.lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="var/proba")
    args = parser.parse_args()
    settings = load_settings()
    if settings.is_production:
        raise SystemExit("refusing to rehearse on a production database")
    out = Path(args.out)
    shutil.rmtree(out, ignore_errors=True)
    connection = create_engine(settings.sqlalchemy_url).connect()
    transaction = connection.begin()
    factory = sessionmaker(
        bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
    )
    try:
        rehearse(factory, out)
    finally:
        transaction.rollback()
        connection.close()
    print(f"\nnothing kept in the database; what the buyer received is in {out}/")


if __name__ == "__main__":
    main()
