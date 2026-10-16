"""Document packages: which forms a call gets, and the package made for an order (roadmap P5 s75).

`config/packages.yaml` names each package's templates and the calls it is offered for. A call
gets a package only when exactly one matches (`for_call`): two would be a mistake in the file,
and none means none is sold.

`assemble` makes the package from three things the platform holds, never from a guess:

- the **buyer** typed on the order (name, address, ЕДБ, ЕМБС);
- the **profile** the order was placed for (legal form, municipality, activity, founding year);
- the **call** as published after review (title, institution, deadline);

and fills every template with them (`engine.render`), labels each as a draft (`label.label`),
and makes the checklist from what was left and what the forms ask to attach
(`checklist.build`). Nothing here reaches a model: invariant 4 does not even come into it.
"""

import datetime as dt
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.documents import TEMPLATES, checklist, engine, label
from app.web.format import SKOPJE

CATALOGUE = Path(__file__).resolve().parents[2] / "config" / "packages.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Calls(_Strict):
    source: str
    title_contains: list[str] = Field(default_factory=list)


class Package(_Strict):
    slug: str
    title_mk: str
    documents: list[str]
    calls: Calls

    def offered_for(self, source: str, title_mk: str) -> bool:
        if source != self.calls.source:
            return False
        title = (title_mk or "").casefold()
        return not self.calls.title_contains or any(
            phrase.casefold() in title for phrase in self.calls.title_contains
        )


@cache
def catalogue(path: Path = CATALOGUE) -> dict[str, Package]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))["packages"]
    found = [Package.model_validate(entry) for entry in raw]
    return {p.slug: p for p in found}


def for_call(source: str, title_mk: str) -> Package | None:
    """The one package offered for a call, or None (no match, or an ambiguous file)."""
    matching = [p for p in catalogue().values() if p.offered_for(source, title_mk)]
    return matching[0] if len(matching) == 1 else None


def check() -> list[str]:
    """What is wrong with config/packages.yaml, one line each."""
    problems = []
    for package in catalogue().values():
        for document in package.documents:
            path = TEMPLATES / document
            if not path.exists():
                problems.append(f"{package.slug}: {document} does not exist")
                continue
            problems += [
                f"{package.slug}: {document}: {p}" for p in engine.check(path.read_bytes())
            ]
            try:
                checklist.manifest_for(path)
            except (checklist.ChecklistRefused, ValueError) as refused:
                problems.append(f"{package.slug}: {refused}")
    return problems


@dataclass(frozen=True)
class Facts:
    """What the platform holds about the applicant and the call, for the forms."""

    buyer_name: str | None = None
    buyer_address: str | None = None
    buyer_edb: str | None = None
    buyer_embs: str | None = None
    legal_form: str | None = None
    municipality: str | None = None
    activity: str | None = None
    founded: int | None = None
    call_title: str | None = None
    call_institution: str | None = None
    call_deadline: dt.datetime | None = None

    def values(self, today: dt.date) -> dict:
        deadline = self.call_deadline.astimezone(SKOPJE).date() if self.call_deadline else None
        return {
            "applicant_name": self.buyer_name,
            "applicant_address": self.buyer_address,
            "applicant_edb": self.buyer_edb,
            "applicant_embs": self.buyer_embs,
            "applicant_legal_form": self.legal_form,
            "applicant_municipality": self.municipality,
            "applicant_activity": self.activity,
            "applicant_founded": self.founded,
            "call_title": self.call_title,
            "call_institution": self.call_institution,
            "call_deadline": deadline,
            "document_date": today,
        }


def facts_from(
    order, profile_answers: dict, call, institution: str | None, today: dt.date
) -> Facts:
    """The facts, from the order's buyer details, the profile's answers and the call."""
    from app.matching import intake
    from app.matching.normalise import normalise

    profile = normalise(dict(profile_answers), today)
    founded = profile_answers.get("founded")
    return Facts(
        buyer_name=order.buyer_name,
        buyer_address=order.buyer_address,
        buyer_edb=order.buyer_edb,
        buyer_embs=order.buyer_embs,
        legal_form=intake.entity_label(profile),
        municipality=profile.municipality.name_mk if profile.municipality else None,
        activity=f"{profile.nace.code} {profile.nace.name_mk}" if profile.nace else None,
        founded=int(founded) if str(founded or "").isdigit() else None,
        call_title=call.title_mk if call else None,
        call_institution=institution,
        call_deadline=call.deadline_at if call else None,
    )


@dataclass(frozen=True)
class Made:
    """One filled document of a package."""

    template: str  # the path under app/documents/templates/
    title_mk: str
    docx: bytes
    unfilled: list[engine.Unfilled]


@dataclass(frozen=True)
class Assembled:
    package: Package
    documents: list[Made]
    checklist: list[checklist.Item]
    checklist_docx: bytes


def assemble(package: Package, facts: Facts, today: dt.date) -> Assembled:
    """Every document filled from the facts and labelled; the checklist made from all of them."""
    values = facts.values(today)
    made, pairs = [], []
    for document in package.documents:
        path = TEMPLATES / document
        template = path.read_bytes()
        manifest = checklist.manifest_for(path)
        used = {key for key, _ in engine.placeholders(template)}
        rendered = engine.render(template, {k: v for k, v in values.items() if k in used})
        made.append(
            Made(document, manifest.title_mk, label.label(rendered.docx, today), rendered.unfilled)
        )
        pairs.append((manifest, rendered))
    items = checklist.build(pairs)
    printed = checklist.to_docx(
        items,
        applicant=facts.buyer_name or "",
        call=facts.call_title or package.title_mk,
        on=today,
        notes=checklist.package_notes([m for m, _ in pairs]),
    )
    return Assembled(package, made, items, printed)


# ------------------------------------------------------------------ a paid order's package


class PackageRefused(ValueError):
    """The package cannot be made as things stand; nothing was written. Said to the operator."""


def _template_row(session, document: str, content: bytes):
    import hashlib

    from sqlalchemy import select

    from app.models.documents import DocumentTemplate

    digest = hashlib.sha256(content).hexdigest()
    row = session.scalar(select(DocumentTemplate).where(DocumentTemplate.file_path == document))
    if row is None:
        parts = Path(document)
        row = DocumentTemplate(
            slug=str(parts.parent), version=parts.stem, file_path=document, sha256=digest
        )
        session.add(row)
    elif row.sha256 != digest:
        raise PackageRefused(
            f"{document} changed since it was recorded: a new version is a new file"
        )
    session.flush()
    return row


def _keep(store, package_id, content: bytes) -> str:
    import hashlib

    key = f"packages/{package_id}/{hashlib.sha256(content).hexdigest()}"
    store.put(key, content)
    return key


def prepare(session, store, order_id, today: dt.date) -> int:
    """Make the package of a paid order, store it and queue it for review: the item's id."""
    from sqlalchemy import select

    from app.models import ApplicantProfile, Call, Programme, ReviewQueueItem, SourceFeed
    from app.models.commerce import Order
    from app.models.documents import DocumentPackage, GeneratedDocument
    from app.models.enums import ReviewKind

    order = session.get(Order, order_id)
    row = session.scalar(select(DocumentPackage).where(DocumentPackage.order_id == order_id))
    if order is None or row is None:
        raise PackageRefused(f"order {order_id} is not a package order")
    call = session.get(Call, row.call_id)
    source = session.get(SourceFeed, call.source_feed_id)
    package = for_call(source.slug, call.title_mk)
    if package is None:
        raise PackageRefused(f"no package is offered for the call «{call.title_mk}» any more")
    programme = session.get(Programme, call.programme_id)
    profile = session.get(ApplicantProfile, order.profile_id)
    facts = facts_from(
        order, profile.answers, call, programme.institution if programme else None, today
    )
    made = assemble(package, facts, today)

    documents = []
    for document in made.documents:
        template = _template_row(
            session, document.template, (TEMPLATES / document.template).read_bytes()
        )
        key = _keep(store, row.id, document.docx)
        session.add(
            GeneratedDocument(
                package_id=row.id,
                template_id=template.id,
                storage_key=key,
                format="docx",
                is_ai_assisted=False,  # filled from the order and profile; no model wrote a word
                unfilled_fields=[u.as_row() for u in document.unfilled],
            )
        )
        documents.append({"title_mk": document.title_mk, "template": document.template, "key": key})
    checklist_key = _keep(store, row.id, made.checklist_docx)
    session.add(
        GeneratedDocument(
            package_id=row.id, storage_key=checklist_key, format="docx", is_ai_assisted=False
        )
    )
    row.checklist = checklist.as_rows(made.checklist)
    item = ReviewQueueItem(
        kind=ReviewKind.DOCUMENT_PACKAGE,
        order_id=order.id,
        call_id=call.id,
        reason="Пакет на документи за преглед пред испраќање",
        payload={
            "package": package.slug,
            "title_mk": package.title_mk,
            "documents": documents,
            "checklist_key": checklist_key,
            "made_on": today.isoformat(),
        },
    )
    session.add(item)
    session.flush()
    return item.id
