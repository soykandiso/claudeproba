"""The proforma as a PDF (roadmap P4 s49): what the customer pays from. And, since s53, the
invoice issued when the report is delivered: the same document, `kind='final'`, which shows
the payment against the proforma instead of how to pay.

Rendered the way the report is (`app/reports/render.py`): WeasyPrint, only the fonts this
repository ships, merged per weight, and refused rather than printed when a character could
not be drawn or a foreign font slipped in. A proforma with a wrong digit is worse than late.

**The seller is written once.** Name, address and ЕМБС are `config/legal.yaml`'s entity; the
ЕДБ, the account and the bank are `config/invoicing.yaml`'s. While any is undecided (D4) it
prints as «[се утврдува]» and `flask invoices check` fails: the deploy runbook runs it.

**A proforma is not stored.** It is made again from its `invoice` row whenever it is needed;
the row is what the accountant and the law keep. **A final invoice is stored as sent**
(`invoice.pdf_storage_key`, P4 s53), because it is the document the buyer files.

**The acceptance is a person's:** an accountant reviews a sample (`flask invoices sample`)
and confirms the fields before the first real proforma is sent.
"""

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path

import click
import jinja2
from flask import current_app
from flask.cli import AppGroup
from markupsafe import Markup

from app.i18n import number
from app.legal import legal
from app.models.commerce import Invoice, Order
from app.models.enums import InvoiceKind
from app.orders import numbering
from app.pricing import prices
from app.reports import render
from app.reports.lint import find_banned
from app.web.format import mkdate

TEMPLATES = Path(__file__).resolve().parent / "templates"
DESCRIPTION = "Детален извештај за подобност за јавен повик, прегледан од човек"
# The line on a proforma or invoice, by what was bought (P5 s75, P6 s76).
DESCRIPTIONS = {
    "report": DESCRIPTION,
    "package": "Пакет на документи за јавен повик: образци пополнети со податоците на барателот "
    "и листа за дополнување, прегледан од човек",
    "monitoring-month": "Следење на нови јавни повици за профилот на барателот, еден месец",
    "monitoring-year": "Следење на нови јавни повици за профилот на барателот, една година",
}


def describe(session, order: Order, period: tuple[dt.date, dt.date] | None = None) -> str:
    """The invoice line for an order's product, with the period for a subscription."""
    from app.orders import service

    text = DESCRIPTIONS.get(service.sku_of(session, order), DESCRIPTION)
    if period:
        text += f", од {mkdate(period[0])} до {mkdate(period[1])}"
    return text


class ProformaRefused(ValueError):
    """The proforma cannot be printed as it stands; nothing is produced."""


@dataclass(frozen=True)
class Seller:
    name: str | None
    address: str | None
    embs: str | None
    edb: str | None
    bank_account: str | None
    bank: str | None
    place: str | None

    def missing(self) -> list[str]:
        return [field for field, value in self.__dict__.items() if not value]


def seller() -> Seller:
    entity, fiscal = legal().entity, numbering.settings().get("seller") or {}
    return Seller(
        name=entity.name,
        address=entity.address,
        embs=entity.embs,
        edb=fiscal.get("edb"),
        bank_account=fiscal.get("bank_account"),
        bank=fiscal.get("bank"),
        place=fiscal.get("place"),
    )


def _denars(value) -> str:
    """8.900,00: two decimals, grouped as Macedonian groups."""
    return number(Decimal(str(value)), 2)


@cache
def _environment() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(TEMPLATES),
        autoescape=True,
        undefined=jinja2.StrictUndefined,
    )
    env.filters["mkdate"] = mkdate
    env.filters["denars"] = _denars
    return env


def html_of(
    invoice: Invoice, order: Order, proforma: Invoice | None = None, description: str = DESCRIPTION
) -> str:
    """`proforma` is the paid proforma a final invoice settles; unused for a proforma."""
    return (
        _environment()
        .get_template("proforma.html")
        .render(
            invoice=invoice,
            order=order,
            proforma=proforma,
            seller=seller(),
            vat_percent=prices().vat_percent,
            description=description,
            font_faces=Markup(render.font_faces()),
            tokens=Markup(render.token_values()),
            css=(TEMPLATES / "proforma.css").as_uri(),
        )
    )


def pdf(
    invoice: Invoice,
    order: Order,
    proforma: Invoice | None = None,
    description: str = DESCRIPTION,
) -> bytes:
    """The document's PDF, after the same checks the report passes. Raises ProformaRefused."""
    if invoice.kind == InvoiceKind.FINAL and (proforma is None or invoice.paid_at is None):
        raise ProformaRefused(f"invoice {invoice.number}: a final invoice settles a paid proforma")
    html = html_of(invoice, order, proforma, description)
    banned = find_banned(render.own_voice(html))
    if banned:
        raise ProformaRefused(f"banned phrase on proforma {invoice.number}: {banned}")
    missing = render.uncovered(render.visible_text(html))
    if missing:
        codes = ", ".join(f"U+{ord(c):04X}" for c in missing)
        raise ProformaRefused(f"proforma {invoice.number}: the shipped fonts cannot draw {codes}")
    document = render._pdf(html)
    strangers = [f for f in render.embedded_fonts(document) if not render._ours(f)]
    if strangers:
        raise ProformaRefused(f"proforma {invoice.number}: a font we do not ship: {strangers}")
    return document


def sample(final: bool = False) -> tuple[Invoice, Order, Invoice | None]:
    """An invented order and its proforma, or its final invoice, never saved: for the accountant."""
    p = prices()
    net = p.report.net
    order = Order(
        id=uuid.uuid4(),
        amount_mkd=net,
        vat_mkd=p.gross(net) - net,
        buyer_name="Пример ДООЕЛ Скопје",
        buyer_address="ул. Пример бр. 1, 1000 Скопје",
        buyer_edb="МК4000000000000",
        buyer_embs="1234567",
    )
    today = numbering.today()
    invoice = Invoice(
        order_id=order.id,
        kind=InvoiceKind.PROFORMA,
        number=f"{numbering.settings()['prefixes']['proforma']}-{today.year}-0001",
        fiscal_year=today.year,
        issued_at=today,
        due_at=today + dt.timedelta(days=numbering.settings()["proforma_due_days"]),
        amount_mkd=order.amount_mkd,
        vat_mkd=order.vat_mkd,
        total_mkd=p.gross(net),
    )
    if not final:
        return invoice, order, None
    paid = Invoice(
        order_id=order.id,
        kind=InvoiceKind.FINAL,
        number=f"{numbering.settings()['prefixes']['final']}-{today.year}-0001",
        fiscal_year=today.year,
        issued_at=today,
        amount_mkd=order.amount_mkd,
        vat_mkd=order.vat_mkd,
        total_mkd=p.gross(net),
        paid_at=dt.datetime.combine(today, dt.time(12), dt.UTC),
        bank_reference="Пример: извод 123 од 01.01, НЛБ",
    )
    return paid, order, invoice


# ------------------------------------------------------------------ the operator's side

cli = AppGroup("invoices", help="Proformas and invoices (P4).")


@cli.command("check")
def check():
    """Fail while a proforma would print «[се утврдува]» (the deploy runbook runs this)."""
    gaps = seller().missing()
    for gap in gaps:
        click.echo(f"not yet decided: seller.{gap}")
    if gaps:
        raise SystemExit(1)
    click.echo("the seller's details are complete")


@cli.command("audit")
def audit_command():
    """Read every invoice series back: gaps, duplicates, formats, years. Silent when all is well."""
    from app.db import session_factory

    with session_factory(current_app.extensions["settings"])() as session:
        problems = numbering.audit(session)
    for problem in problems:
        click.echo(problem)
    if problems:
        raise SystemExit(1)
    click.echo("every invoice series is whole")


@cli.command("sample")
@click.argument("out", type=click.Path(dir_okay=False))
@click.option("--final", is_flag=True, help="The invoice issued on delivery, not the proforma.")
def sample_command(out, final):
    """Write a sample proforma or invoice (an invented buyer) for the accountant to review."""
    invoice, order, proforma = sample(final)
    Path(out).write_bytes(pdf(invoice, order, proforma))
    click.echo(f"wrote {out}: {invoice.kind} {invoice.number}, an invented buyer")
