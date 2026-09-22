"""Freeze the evaluation harness's tier A call fixtures from the captured documents.

    PYTHONPATH=. uv run python ops/dev/freeze_eval_fixtures.py

Tier A is defined against *frozen* calls (docs/matching.md §8): the same bytes, the
same normalised text and the same offsets every time it runs, so a verdict that
changes is the matching code changing and nothing else. This script is how those
fixtures are built, and it is the only thing that writes them — like `data/`, they
are rebuilt, never hand-edited (CLAUDE.md, "reference data ... not rows edited in
production").

Each fixture is one real call, taken from two things the repository already holds:

- the document `tests/fixtures/` captured from the source, normalised by the real
  normaliser (`tests/test_extract_schema.fixture_text`, which replays the recorded
  Tesseract output for the scanned ones so OCR versions cannot move an offset);
- the extraction in `tests/cassettes/extract_call/`, treated as *what a reviewer
  approved*. Tier A never calls a model, so a criterion it judges has to come from
  somewhere, and a hand-written reply that a session has already read is the
  honest stand-in until real approvals exist in the database.

Citations are located by `locate_citations`, the same code the pipeline runs, so a
frozen criterion carries a real `(snapshot, char_start, char_end)` into the
harness — which checks every one of them verbatim before it judges anything.

Re-run it after changing a cassette, a captured document or the normaliser, and
**read the diff**: a moved offset or a changed quote is exactly the kind of drift
the harness exists to notice.
"""

import datetime as dt
import hashlib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from app.ai.schemas import CallExtraction
from app.ingestion.extract import Document, locate_citations
from app.ingestion.sources.eu_portal import ELIGIBILITY_GAP
from app.models.enums import CallStatus, TextSource
from tests.test_extract_schema import cassette, fixture_text

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "evals" / "fixtures"
TZ = ZoneInfo("Europe/Skopje")


@dataclass(frozen=True)
class Frozen:
    """What the fixture needs that the extraction itself does not carry."""

    institution: str
    # The page a customer would be sent to; tests/fixtures/README.md records it.
    canonical_url: str
    text_source: TextSource
    # Why this call is in the suite: the shape it contributes (docs/matching.md §8).
    shape: str
    # A fetcher's statement that the documents it read are not all of the call
    # (app/ingestion/fetcher.py). Empty for a call whose own text is complete.
    eligibility_gap: str = ""


CALLS = {
    "av-measure-819": Frozen(
        institution="Агенција за вработување на РСМ",
        canonical_url="https://av.gov.mk/oglasi-za-aktivni-merki.nspx",
        text_source=TextSource.NATIVE,
        shape="мерка за вработување: еден структуриран услов и две изјави",
    ),
    "economy-call-3": Frozen(
        institution="Министерство за економија и труд",
        canonical_url=(
            "https://www.economy.gov.mk/mk-MK/javni-objavi/javni-oglasi/"
            "javen-povik-za-finansiska-poddrska-na-mikro-mali-i-sredni-pretprijatija-i-zanaetcii"
        ),
        text_source=TextSource.NATIVE,
        shape="грант за ММСП: возраст и големина како правила, дејноста како текст",
    ),
    "eu-digital-2026-skills-10-edtech": Frozen(
        institution="European Commission (DIGITAL Europe)",
        canonical_url=(
            "https://ec.europa.eu/info/funding-tenders/opportunities/portal/screen/"
            "opportunities/topic-details/digital-2026-skills-10-edtech"
        ),
        text_source=TextSource.NATIVE,
        shape="ЕУ тема: условите се во документ што не е прочитан",
        eligibility_gap=ELIGIBILITY_GAP,
    ),
    "skopje-call-12149": Frozen(
        institution="Град Скопје",
        canonical_url="https://skopje.gov.mk/media/12149/јавен-повик-субвенции-на-занаети.pdf",
        text_source=TextSource.OCR,
        shape="општински повик: местото и занаетот се услови што правилата не ги знаат",
    ),
    "ipard-notice-03-2025": Frozen(
        institution="Агенција за финансиска поддршка во земјоделството (ИПАРД)",
        canonical_url="https://www.ipardpa.gov.mk/mk/Home/IpardPovici/34",
        text_source=TextSource.NATIVE,
        shape="претходна најава: објавена, но уште не е повик по кој се аплицира",
    ),
}


def deadline_at(out: CallExtraction) -> dt.datetime | None:
    """The same rule as app/ingestion/pipeline.py: end of the day, in Skopje."""
    if out.deadline is None:
        return None
    if out.deadline.time:
        hour, minute = (int(part) for part in out.deadline.time.split(":"))
        local = dt.time(hour, minute)
    else:
        local = dt.time(23, 59, 59)
    return dt.datetime.combine(out.deadline.value, local, tzinfo=TZ)


def criteria_of(out: CallExtraction, citations: dict) -> list[dict]:
    rows = []
    for index, criterion in enumerate(out.criteria):
        citation = citations[f"criteria.{index}"]
        rows.append(
            {
                "kind": str(criterion.kind),
                "label_mk": criterion.label_mk,
                "field": criterion.field and str(criterion.field),
                "operator": criterion.operator and str(criterion.operator),
                "value_json": criterion.value_json(),
                "confidence": criterion.confidence,
                # The document's own spelling, which is what the check constraint
                # and the harness's citation check compare against.
                "quote": citation.source_quote,
                "quote_start": citation.char_start,
                "quote_end": citation.char_end,
            }
        )
    return rows


def freeze(slug: str, frozen: Frozen) -> None:
    text = fixture_text(slug)
    out = CallExtraction.model_validate_json(cassette(slug))
    document = Document(snapshot_id=0, url=frozen.canonical_url, text=text)
    citations, failures = locate_citations(out, [document])
    if failures:
        raise SystemExit(f"{slug}: {len(failures)} quote(s) not found; fix the cassette first")

    directory = OUT / slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "document.txt").write_text(text, encoding="utf-8")

    announced = out.document_kind == "advance_notice"
    call = {
        "slug": slug,
        "shape": frozen.shape,
        "title_mk": out.title_mk.value,
        "institution": frozen.institution,
        "canonical_url": frozen.canonical_url,
        "reference_code": out.reference_code.value if out.reference_code else None,
        # An advance notice is published but cannot be applied to: stage 1a keeps
        # only OPEN calls, so every profile is expected to miss this one.
        "status": str(CallStatus.ANNOUNCED if announced else CallStatus.OPEN),
        "published_at": out.published_on.value if out.published_on else None,
        "deadline_at": deadline_at(out),
        "eligibility_gap": frozen.eligibility_gap or None,
        "document": {
            "path": "document.txt",
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "characters": len(text),
            "text_source": str(frozen.text_source),
        },
        "criteria": criteria_of(out, citations),
    }
    header = (
        "# Frozen by ops/dev/freeze_eval_fixtures.py from tests/fixtures and\n"
        "# tests/cassettes/extract_call. Do not hand-edit: re-run the script.\n"
    )
    (directory / "call.yaml").write_text(
        header + yaml.safe_dump(call, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    print(f"{slug}: {len(text):,} characters, {len(call['criteria'])} criteria")


def main() -> None:
    for slug, frozen in CALLS.items():
        freeze(slug, frozen)


if __name__ == "__main__":
    main()
