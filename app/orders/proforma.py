"""The proforma as a PDF (roadmap P4 s49): what the customer pays from.

Rendered the way the report is (`app/reports/render.py`): WeasyPrint, only the fonts this
repository ships, merged per weight, and refused rather than printed when a character could
not be drawn or a foreign font slipped in. A proforma with a wrong digit is worse than late.

**The seller is written once.** Name, address and ЕМБС are `config/legal.yaml`'s entity; the
ЕДБ, the account and the bank are `config/invoicing.yaml`'s. While any is undecided (D4) it
prints as «[се утврдува]» and `flask invoices check` fails: the deploy runbook runs it.

**Nothing is stored.** The proforma is made again from its `invoice` row whenever it is
needed, as the report is from its draft; the row is what the accountant and the law keep.

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


def html_of(invoice: Invoice, order: Order) -> str:
    return (
        _environment()
        .get_template("proforma.html")
        .render(
            invoice=invoice,
            order=order,
            seller=seller(),
            vat_percent=prices().vat_percent,
            description=DESCRIPTION,
            font_faces=Markup(render.font_faces()),
            tokens=Markup(render.token_values()),
            css=(TEMPLATES / "proforma.css").as_uri(),
        )
    )


def pdf(invoice: Invoice, order: Order) -> bytes:
    """The proforma's PDF, after the same checks the report passes. Raises ProformaRefused."""
    if invoice.kind != InvoiceKind.PROFORMA:
        raise ProformaRefused(f"invoice {invoice.number} is not a proforma")
    html = html_of(invoice, order)
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


def sample() -> tuple[Invoice, Order]:
    """An invented order and its proforma, never saved: what the accountant reviews."""
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
    today = dt.date.today()
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
    return invoice, order


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


@cli.command("sample")
@click.argument("out", type=click.Path(dir_okay=False))
def sample_command(out):
    """Write a sample proforma (an invented buyer) for the accountant to review."""
    invoice, order = sample()
    Path(out).write_bytes(pdf(invoice, order))
    click.echo(f"wrote {out}: proforma {invoice.number}, an invented buyer")
