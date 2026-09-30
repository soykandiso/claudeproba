"""The paid report as PDF (roadmap P2 s35).

The row's acceptance, "MK renders correctly using fonts actually installed on the
VPS", is two tests: `test_an_approved_report_is_set_in_the_fonts_we_ship_and_nothing_else`
(every embedded font is one of ours, whatever this machine has installed) and
`test_what_is_printed_reads_back_as_what_was_meant` (the pixels, read by Tesseract,
say the digits and the Macedonian — because the first render had perfect extracted
text and wrong glyphs). The rest proves the renderer checks again instead of
trusting approval.
"""

import datetime as dt
import shutil
import subprocess
from io import BytesIO

import pypdf
import pytest

from app import create_app
from app.config import load_settings
from app.models import RawSnapshot, ReviewQueueItem
from app.reports import render
from app.review import report as reports
from tests import test_report_compose as tc
from tests.test_stage1 import DATABASE_AVAILABLE, NOW

registry = tc.registry
world = tc.world

needs_db = pytest.mark.skipif(not DATABASE_AVAILABLE, reason="no database reachable")
ISSUED = dt.date(2026, 9, 30)
ALPHABET = "АБВГДЃЕЖЗЅИЈКЛЉМНЊОПРСТЌУФХЦЧЏШабвгдѓежзѕијклљмнњопрстќуфхцчџш"


def citation(quote="се од приватен и од граѓански сектор;") -> dict:
    return {
        "snapshot_id": 7,
        "char_start": 10,
        "char_end": 10 + len(quote),
        "quote": quote,
        "source_url": "https://av.gov.mk/oglasi",
        "retrieved_at": "2026-09-22T20:10:20+00:00",
    }


def draft(**changes) -> dict:
    """A draft as compose writes it, one call and one condition, with no database."""
    condition = {
        "ref": "1.1",
        "kind": "hard_structured",
        "label": "Работодавачи од приватен сектор",
        "verdict": "eligible",
        "decided_by": "rule",
        "reason": "Во профилот: ДОО, мало претпријатие.",
        "confidence": None,
        "citation": citation(),
        "evidence": None,
        "criterion_id": "c1",
    }
    call = {
        "number": 1,
        "call_id": "x",
        "title": "Јавен повик за мерката 4. Практикантство",
        "institution": "Агенција за вработување",
        "url": "https://av.gov.mk/oglasi",
        "deadline": "2026-08-21T21:59:59+00:00",
        "verdict": "likely_eligible",
        "rank": 1,
        "conditions": [condition],
        "explanation": [{"text_mk": "Условот е исполнет.", "cites": ["1.1"]}],
        "next_steps": [],
    }
    base = {
        "version": 1,
        "match_run_id": "r",
        "run_date": "2026-09-29",
        "applicant": "- Вид на субјект: ДОО, мало претпријатие\n- Вработени: 10–49",
        "candidates_considered": 4,
        "summary": [{"text_mk": "Прегледани се условите.", "cites": ["1.1"]}],
        "calls": [call],
        "excluded": [],
        "unplaced": [],
    }
    return base | changes


def html(d=None) -> str:
    return render.html_of(d or draft(), issued=ISSUED, reference="И-1")


# ------------------------------------------------------------------ fonts and glyphs


def test_the_shipped_fonts_draw_the_whole_macedonian_alphabet_and_our_punctuation():
    assert render.uncovered(ALPHABET + "0123456789.,:;–—%„“«»()") == []
    assert render.uncovered("漢 ✓") == ["✓", "漢"]


@pytest.mark.skipif(not shutil.which("tesseract"), reason="tesseract is not installed")
@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm is not installed")
def test_what_is_printed_reads_back_as_what_was_meant(tmp_path):
    """The glyphs, not the text layer: a mixed-up font has a perfect text layer."""
    pdf = render._pdf(html())
    (tmp_path / "r.pdf").write_bytes(pdf)
    subprocess.run(
        ["pdftoppm", "-r", "200", "-f", "2", "-l", "2", "-png", "-singlefile", "r.pdf", "p"],
        cwd=tmp_path,
        check=True,
    )
    read = subprocess.run(
        ["tesseract", "p.png", "-", "-l", "mkd"], cwd=tmp_path, capture_output=True, text=True
    ).stdout

    assert "21.08.2026" in read  # the deadline: digits and full stops
    assert "Практикантство" in read and "профилот: ДОО, мало" in read


def test_the_pdf_takes_the_token_values_and_not_the_sites_split_fonts():
    page = html()
    assert "--ink: #22201B" in page and "--seal:" in page
    assert "fira-sans-cyrillic" not in page and "fira-sans-all-400-normal.ttf" in page


# ------------------------------------------------------------------ what is said


def test_the_templates_own_words_pass_the_lint():
    assert render.find_banned(render.own_voice(html())) == []


def test_the_institutions_words_are_printed_but_not_linted():
    quoted = draft()
    quoted["calls"][0]["conditions"][0]["citation"] = citation("износот е гарантиран")
    page = html(quoted)
    assert "гарантиран" in render.visible_text(page)
    assert "гарантиран" not in render.own_voice(page)


def test_a_deadline_is_a_date_on_paper_never_days_left():
    text = render.visible_text(html())
    assert "21.08.2026" in text and "уште" not in text


def test_every_condition_prints_its_quote_source_date_and_span():
    text = " ".join(render.visible_text(html()).split())
    assert "„" not in text  # the quotation marks are CSS, around the institution's words
    assert "се од приватен и од граѓански сектор;" in text
    assert "av.gov.mk" in text and "Преземено на 22.09.2026" in text
    quote = citation()["quote"]
    assert f"Снимка 7, знаци 10–{10 + len(quote)}" in text


# ------------------------------------------------------------------ the gate, again


def approved(world, *, note="во ред") -> tuple:
    factory, run_id = tc.verified_run(world)
    item, _ = tc.composed(factory, run_id, tc.prose())
    with factory() as s:
        reports.approve(s, s.get(ReviewQueueItem, item.id), note=note, now=NOW)
        s.commit()
    return factory, item.id


@needs_db
def test_an_approved_report_is_set_in_the_fonts_we_ship_and_nothing_else(world):
    factory, item_id = approved(world)
    with factory() as s:
        rendered = render.render(s, s.get(ReviewQueueItem, item_id), issued=ISSUED)

    assert rendered.pdf.startswith(b"%PDF") and rendered.pages >= 2
    assert rendered.fonts and all(render._ours(f) for f in rendered.fonts)
    text = "".join(p.extract_text() for p in pypdf.PdfReader(BytesIO(rendered.pdf)).pages)
    assert "Извештај за подобност" in text and "30.09.2026" in text and "цитат" in text


@needs_db
def test_a_pending_or_rejected_report_is_never_printed(world):
    factory, run_id = tc.verified_run(world)
    item, _ = tc.composed(factory, run_id, tc.prose())
    with factory() as s:
        pending = s.get(ReviewQueueItem, item.id)
        with pytest.raises(render.RenderRefused, match="not approved"):
            render.render(s, pending)
        reports.close(s, pending, note="не", now=NOW)
        with pytest.raises(render.RenderRefused, match="not approved"):
            render.render(s, pending)


@needs_db
def test_a_quote_that_moved_after_approval_is_not_printed(world):
    factory, item_id = approved(world)
    with factory() as s:
        s.get(RawSnapshot, world[2].id).normalised_text = "друг текст\n" + "x" * 50
        s.flush()
        with pytest.raises(render.RenderRefused, match="no longer passes its checks"):
            render.render(s, s.get(ReviewQueueItem, item_id))


@needs_db
def test_a_character_the_fonts_cannot_draw_is_refused_not_printed(world):
    factory, item_id = approved(world)
    with factory() as s:
        item = s.get(ReviewQueueItem, item_id)
        edited = reports.draft_of(item) | {}
        edited["calls"][0]["conditions"][0]["reason"] += " ✓"
        item.corrected_payload = edited
        s.flush()
        with pytest.raises(render.RenderRefused, match="U\\+2713"):
            render.render(s, item)


@needs_db
def test_a_font_we_do_not_ship_is_refused(world, monkeypatch):
    factory, item_id = approved(world)
    values = render.token_values().replace('--font-body: "Fira Sans"', "--font-body: monospace")
    monkeypatch.setattr(render, "token_values", lambda: values)
    with factory() as s, pytest.raises(render.RenderRefused, match="a font we do not ship"):
        render.render(s, s.get(ReviewQueueItem, item_id))


# ------------------------------------------------------------------ the operator's ways in


@pytest.fixture
def admin(world, monkeypatch):
    factory = world[0]
    monkeypatch.setattr("app.web.admin._sessions", lambda: factory)
    app = create_app(load_settings(env="testing", secret_key="test"))
    return app.test_client()


@needs_db
def test_the_admin_serves_an_approved_report_as_pdf_and_says_why_it_will_not(world, admin):
    factory, item_id = approved(world)
    page = admin.get(f"/admin/izveshtaj/{item_id}").get_data(as_text=True)
    assert f"/admin/izveshtaj/{item_id}/pdf" in page

    served = admin.get(f"/admin/izveshtaj/{item_id}/pdf")
    assert served.status_code == 200 and served.mimetype == "application/pdf"

    with factory() as s:
        s.get(RawSnapshot, world[2].id).normalised_text = "друг текст"
        s.commit()
    refused = admin.get(f"/admin/izveshtaj/{item_id}/pdf")
    assert refused.status_code == 409
    assert "PDF не е направен" in refused.get_data(as_text=True)


@needs_db
def test_a_pending_report_offers_no_pdf(world, admin):
    factory, run_id = tc.verified_run(world)
    item, _ = tc.composed(factory, run_id, tc.prose())
    assert "/pdf" not in admin.get(f"/admin/izveshtaj/{item.id}").get_data(as_text=True)
    assert admin.get(f"/admin/izveshtaj/{item.id}/pdf").status_code == 409


@needs_db
def test_the_command_says_when_there_is_no_such_item(tmp_path):
    app = create_app(load_settings(env="testing"))
    with app.app_context():
        result = app.test_cli_runner().invoke(
            args=["review", "render-report", "0", "--out", str(tmp_path / "r.pdf")]
        )
    assert result.exit_code != 0 and "no review item 0" in result.output
