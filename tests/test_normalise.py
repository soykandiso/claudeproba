"""The normaliser on real source documents.

Roadmap P1 s9 acceptance: a known quote's (start, end) in normalised_text
round-trips to exactly that text. The quotes below were read off the documents
by a person, not produced by the code under test.
"""

import io
import json
import shutil
import unicodedata
from dataclasses import replace
from pathlib import Path

import pytest
from pypdf import PdfReader, PdfWriter

from app.ingestion.normalise import (
    PAGE_BREAK,
    NormaliseError,
    UnsupportedFormat,
    find_quote,
    normalise,
    page_of,
)
from app.ingestion.normalise.html import normalise_html
from app.ingestion.normalise.pdf import OcrPage, TesseractOcr, _Word, restore_percents
from app.models.enums import TextSource

FIXTURES = Path(__file__).parent / "fixtures"
needs_tesseract = pytest.mark.skipif(
    not TesseractOcr.available(), reason="tesseract and pdftoppm not installed"
)


def fixture(path: str) -> bytes:
    return (FIXTURES / path).read_bytes()


def av_detail(detail_id: int) -> str:
    return json.loads(fixture(f"av/measure-{detail_id}-business-mk.json"))["d"]


def assert_round_trip(text: str, quote: str) -> None:
    spans = find_quote(text, quote)
    assert spans, f"quote not found: {quote!r}"
    for span in spans:
        assert text[span.start : span.end] == quote


class FakeOcr:
    """Stands in for Tesseract where the test is about structure, not reading."""

    def __init__(self, confidence: float = 95.0, unresolved: int = 0):
        self.confidence = confidence
        self.unresolved = unresolved
        self.asked: list[int] = []

    def read_pages(self, pdf: bytes, page_numbers: list[int]) -> dict[int, OcrPage]:
        self.asked += page_numbers
        return {
            n: OcrPage(
                f"OCR текст страница {n}", self.confidence, percents_unresolved=self.unresolved
            )
            for n in page_numbers
        }


def word(text: str, confidence: float, *, left: int = 100) -> _Word:
    """One word table row, at a box no other test word overlaps unless it is given one."""
    return _Word(
        text, confidence, left=left, top=50, width=60, height=30, block=1, paragraph=1, line=1
    )


# --- acceptance: known quotes round-trip, one per format ------------------------------


@pytest.mark.parametrize(
    "quote",
    [
        # Split across <span>s in the source: must read as written, not "202 3".
        "за 2023 година усвоен од Владата",
        "на ден 21.09.2023 година, се објавува",
        "ќе им се издаде потврда за спроведената практична обука",
    ],
)
def test_html_quotes_round_trip(quote):
    assert_round_trip(normalise_html(av_detail(724)).text, quote)


def test_docx_quote_round_trips():
    text = normalise(fixture("economy/call-3-javen-povik.docx")).text

    assert_round_trip(
        text, "кофинансирање на 40% од докажаните трошоци, но не повеќе од 200.000 денари"
    )


def test_pdf_text_layer_quote_round_trips():
    result = normalise(fixture("ipardpa/call-34-najava-03-2025.pdf"))

    assert result.text_source == TextSource.NATIVE
    assert_round_trip(result.text, "во четвртиот квартал од 2025 година ќе се објави Јавен повик")


def test_html_page_with_a_content_selector():
    result = normalise(
        fixture("economy/call-1.html"), "text/html; charset=utf-8", html_root="section.pt-8"
    )

    assert_round_trip(result.text, "Рок на пријавување: 15/09/2026")
    assert_round_trip(result.text, "Образец „Изјава – Државна помош 2026“")
    assert "Сектор за управување со човечки ресурси" not in result.text, "navigation excluded"


@needs_tesseract
def test_ocr_quote_round_trips_and_is_marked_as_ocr():
    """A Skopje call exists only as scanned paper (docs/sources.md §6.2)."""
    result = normalise(fixture("skopje/call-12149.pdf"))

    assert result.text_source == TextSource.OCR
    assert result.ocr_pages == (1, 2)
    assert result.review_reasons == (), f"a clean 300 dpi scan: {result.review_reasons}"
    assert_round_trip(result.text, "1. Предмет на јавниот повик")
    [span] = find_quote(result.text, "1. Предмет на јавниот повик")
    assert page_of(result.text, span.start) == 1


# --- faithfulness ---------------------------------------------------------------------


def test_the_same_bytes_always_give_the_same_text():
    for path in ["economy/call-3-javen-povik.docx", "ipardpa/call-34-najava-03-2025.pdf"]:
        assert normalise(fixture(path)).text == normalise(fixture(path)).text
    assert normalise_html(av_detail(820)).text == normalise_html(av_detail(820)).text


def test_latin_lookalikes_in_the_document_are_kept_and_found_by_folding():
    """The Economy DOCX itself types "зa" with a Latin a."""
    text = normalise(fixture("economy/call-3-javen-povik.docx")).text
    typed = "направени за набавка на нови машини"  # all Cyrillic, as a person types it

    assert find_quote(text, typed) == [], "exact matching must not paper over it"
    [span] = find_quote(text, typed, fold=True)
    assert text[span.start : span.end] == "направени зa набавка на нови машини"
    assert text[span.start : span.end] != typed, "the span shows what the document says"


def test_decomposed_cyrillic_is_composed():
    decomposed = unicodedata.normalize("NFD", "<p>ќе се објави</p>")
    assert decomposed != "<p>ќе се објави</p>"

    assert_round_trip(normalise_html(decomposed).text, "ќе се објави")


def test_html_structure():
    markup = """<body><script>var x = 'нема';</script>
      <h1>Јавен   повик</h1><p>Прв<br>ред</p>
      <table><tr><th>Мерка</th><th>Износ</th></tr>
             <tr><td>1.1</td><td>200.000 денари</td></tr></table>
      <p>со&nbsp;soft&shy;hyphen</p></body>"""

    assert normalise_html(markup).text == (
        "Јавен повик\n\nПрв\nред\n\nМерка | Износ\n1.1 | 200.000 денари\n\nсо softhyphen"
    )


def test_a_content_selector_that_no_longer_matches_is_an_error_not_a_fallback():
    with pytest.raises(NormaliseError, match="layout"):
        normalise_html("<body><div class='other'>текст</div></body>", root="section.pt-8")


def test_formats_that_need_a_human_say_so():
    with pytest.raises(UnsupportedFormat, match="legacy"):
        normalise(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\0" * 100)
    with pytest.raises(UnsupportedFormat, match="source-specific"):
        normalise(b'{"d": "<p>x</p>"}', "application/json")


# --- PDFs: text layer, OCR, and both in one document ----------------------------------


def mixed_pdf() -> bytes:
    """IPARD's 2-page advance notice (text layer) followed by its 3-page call (images)."""
    writer = PdfWriter()
    for path in [
        "ipardpa/call-34-najava-03-2025.pdf",
        "ipardpa/call-32-javen-povik-01-2025-kratka.pdf",
    ]:
        for page in PdfReader(io.BytesIO(fixture(path))).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def test_a_pdf_is_read_page_by_page_and_only_image_pages_are_ocrd():
    ocr = FakeOcr()
    result = normalise(mixed_pdf(), ocr=ocr)

    assert ocr.asked == [3, 4, 5]
    assert result.text_source == TextSource.MIXED
    assert result.text.count(PAGE_BREAK) == 4
    [span] = find_quote(result.text, "OCR текст страница 4")
    assert page_of(result.text, span.start) == 4
    [native] = find_quote(result.text, "ПРЕТХОДНА НАЈАВА")
    assert page_of(result.text, native.start) == 1


def test_low_ocr_confidence_is_flagged_but_the_text_is_kept():
    result = normalise(fixture("skopje/call-12094.pdf"), ocr=FakeOcr(confidence=70.0))

    assert result.text_source == TextSource.OCR
    assert result.text, "a reviewer needs something to look at"
    assert len(result.review_reasons) == 2
    assert "below 85" in result.review_reasons[0]


@needs_tesseract
def test_a_degraded_scan_is_sent_to_review():
    """The calibration case in pdf.py: the same Skopje scan rendered at 75 dpi."""
    result = normalise(fixture("skopje/call-12094.pdf"), ocr=TesseractOcr(dpi=75))

    assert result.review_reasons, "a visibly misread page must not pass silently"


def test_without_tesseract_an_image_pdf_fails_loudly(monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)

    with pytest.raises(NormaliseError, match="tesseract"):
        normalise(fixture("skopje/call-12094.pdf"))


@needs_tesseract
def test_an_ocr_read_records_the_engine_that_did_it():
    result = normalise(fixture("skopje/call-12094.pdf"), ocr=TesseractOcr(dpi=75))

    assert result.ocr_engine.startswith("tesseract-5")
    assert result.ocr_engine.endswith("mkd-75dpi-pct-mkd+eng"), "the second pass changes the text"
    assert normalise(fixture("ipardpa/call-34-najava-03-2025.pdf")).ocr_engine is None


# --- the percent sign the Macedonian model cannot write (D9, reopened) -----------------
#
# Every rate on these two pages is a number a criterion turns on, and `mkd` alone
# reads all six of them wrong at a confidence that raises no flag. The word tables
# are a recording (tests/fixtures/README.md): both of them differ between Tesseract
# versions, and restore_percents matches them by box.

RATES = {  # what `mkd` wrote -> what the page says, read off the PDF by a person
    "755": "75%",
    "254": "25%",
    "605": "60%",
    "655": "65%",
    "704": "70%",
    "7556.": "75%.",
}


def recorded_words(page: int) -> tuple[list[_Word], list[_Word]]:
    """The `mkd` and `mkd+eng` word tables recorded for one page of IPARD 01/2025."""
    data = json.loads(fixture("ipardpa/call-32.words.json"))["pages"][str(page)]
    return tuple([_Word(*row) for row in data[languages]] for languages in ("mkd", "mkd+eng"))


@pytest.mark.parametrize("page", [1, 2])
def test_every_rate_on_the_page_gets_its_percent_sign_back(page):
    base, second = recorded_words(page)
    restored, count, unresolved = restore_percents(base, second)

    assert unresolved == 0
    assert count == sum(1 for w in second if "%" in w.text)
    before = [w.text for w in base]
    after = [w.text for w in restored]
    changed = {b: a for b, a in zip(before, after, strict=True) if b != a}
    assert changed, "the page has rates; something must have changed"
    assert changed == {b: a for b, a in RATES.items() if b in changed}


@pytest.mark.parametrize("page", [1, 2])
def test_the_second_pass_contributes_nothing_but_the_percent_sign(page):
    """The reason `mkd` reads the page: `mkd+eng` puts Latin look-alikes in Cyrillic.

    So every word the second pass does not repair must come through untouched, and
    a repaired word must differ from what `mkd` wrote only where the `%` went.
    """
    base, second = recorded_words(page)
    restored, _, _ = restore_percents(base, second)

    for was, now in zip(base, restored, strict=True):
        if was.text == now.text:
            continue
        head, tail = now.text.split("%")
        assert was.text.startswith(head) and was.text.endswith(tail), "only the `%` may differ"
        assert was == replace(now, text=was.text), "a repair must not move the box"


def test_a_percent_the_macedonian_pass_cannot_be_reconciled_with_goes_to_review():
    """Invariant 3: an unreadable rate is a reviewer's, never a guess."""
    base = [word("нема", 95.0, left=0)]
    second = [word("40%", 95.0, left=900)]  # nowhere near any `mkd` word

    restored, count, unresolved = restore_percents(base, second)

    assert (count, unresolved) == (0, 1)
    assert [w.text for w in restored] == ["нема"]


def test_an_unresolved_percent_reaches_the_review_reasons():
    result = normalise(fixture("skopje/call-12094.pdf"), ocr=FakeOcr(confidence=95.0, unresolved=2))

    assert any("2 percent sign(s)" in reason for reason in result.review_reasons)
    assert "check every rate against the PDF" in result.review_reasons[0]


@pytest.mark.parametrize(
    ("candidate", "confidence", "current", "why"),
    [
        ("65%", 95.0, "755", "the two passes read different digits"),
        ("60%", 40.0, "605", "the second pass was not confident"),
        ("60%", 95.0, "605", "`mkd` was confident in the number it read"),
        ("6O%", 95.0, "605", "a Latin look-alike letter must never cross over"),
        ("50%-60%", 95.0, "505-605", "two `%` in one token is ambiguous"),
        ("60%", 95.0, "60ста", "`mkd` read letters there, so it is not the same token"),
    ],
)
def test_a_percent_is_not_restored_on_a_doubtful_match(candidate, confidence, current, why):
    base = [word(current, 95.0 if "`mkd` was confident" in why else 50.0)]
    restored, count, unresolved = restore_percents(base, [word(candidate, confidence)])

    assert (count, unresolved) == (0, 1), why
    assert restored[0].text == current, "the text stays what the engine read"


def test_the_second_pass_is_skipped_when_asked_for_the_single_pass_behaviour():
    ocr = TesseractOcr(percent_pass=None)

    assert ocr.percent_pass is None
    assert "pct" not in f"-{ocr.languages}-{ocr.dpi}dpi"
