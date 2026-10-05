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
    assert "--label: #1D1D1F" in page and "--deadline:" in page
    # Paper takes the light theme only: the dark block is not part of :root.
    assert "#000000" not in page.split("</style>")[0].split(":root")[1]
    assert "inter-cyrillic" not in page and "inter-all-400-normal.ttf" in page


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
    values = render.token_values().replace('--font-print: "Inter"', "--font-print: monospace")
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


# ------------------------------------------------------------- DS6: the marks on paper


def _mark_pixels(verdict: str, tmp_path):
    """The verdict mark alone on a small page, rasterised: (image, centre x, y, radius)."""
    from PIL import Image

    page = (
        "<!doctype html><html><head><style>"
        + render.font_faces()
        + render.token_values()
        + "</style>"
        + f'<link rel="stylesheet" href="{(render.TEMPLATES / "report.css").as_uri()}">'
        + "<style>@page { size: 30mm 20mm; margin: 5mm;"
        + " @bottom-left { content: none; } @bottom-right { content: none; } }"
        + "</style></head><body>"
        + f'<p><span class="verdict verdict--{verdict}"></span></p></body></html>'
    )
    (tmp_path / "m.pdf").write_bytes(render._pdf(page))
    subprocess.run(
        ["pdftoppm", "-r", "600", "-gray", "-png", "-singlefile", "m.pdf", "m"],
        cwd=tmp_path,
        check=True,
    )
    image = Image.open(tmp_path / "m.png").convert("L")
    dark = [
        (x, y)
        for y in range(image.height)
        for x in range(image.width)
        if image.getpixel((x, y)) < 160
    ]
    xs, ys = [p[0] for p in dark], [p[1] for p in dark]
    cx, cy = (min(xs) + max(xs)) // 2, (min(ys) + max(ys)) // 2
    return image, cx, cy, (max(xs) - min(xs)) // 2


def _is_dark(image, x, y) -> bool:
    return image.getpixel((x, y)) < 160


@pytest.mark.skipif(not shutil.which("pdftoppm"), reason="pdftoppm is not installed")
def test_the_four_marks_print_as_four_shapes(tmp_path):
    """F10 on paper. Found in DS6: WeasyPrint ignored the site's sized gradient and printed
    «Не можете да аплицирате» as a filled disc, the mark of the opposite verdict."""
    import math

    def ring(image, cx, cy, r):
        return [
            _is_dark(
                image,
                round(cx + r * math.cos(a / 36 * 2 * math.pi)),
                round(cy + r * math.sin(a / 36 * 2 * math.pi)),
            )
            for a in range(36)
        ]

    image, cx, cy, r = _mark_pixels("eligible", tmp_path)
    assert _is_dark(image, cx, cy)  # filled

    image, cx, cy, r = _mark_pixels("likely_eligible", tmp_path)
    assert not _is_dark(image, cx, cy) and all(ring(image, cx, cy, r - 3))  # hollow, whole

    image, cx, cy, r = _mark_pixels("needs_verification", tmp_path)
    edge = ring(image, cx, cy, r - 3)
    assert not _is_dark(image, cx, cy) and not all(edge) and any(edge)  # hollow, broken

    image, cx, cy, r = _mark_pixels("not_eligible", tmp_path)
    assert _is_dark(image, cx, cy)  # the bar
    assert not _is_dark(image, cx, cy - r // 2)  # but not filled


# ------------------------------------------------------------- DS6: the report, F29 and the rest


def test_a_passed_deadline_blocks_delivery_and_says_when():
    """F29 (severity A): a call that closed after the run blocks approval and print."""
    from app.reports import compose

    d = draft()  # the call's deadline is 21.08.2026, 23:59 in Skopje
    assert compose.deadlines(d, dt.date(2026, 8, 21)) == []
    problems = compose.deadlines(d, dt.date(2026, 8, 22))
    assert problems == [
        {"check": "deadline", "where": "call 1", "detail": "the deadline passed on 21.08.2026"}
    ]
    assert "повикот се затвори" in reports.describe(problems[0]["detail"])
    assert compose.deadlines(draft(calls=[{**d["calls"][0], "deadline": None}]), ISSUED) == []


@needs_db
def test_a_report_whose_call_has_since_closed_is_not_printed(world):
    factory, item_id = approved(world)
    with factory() as s:
        item = s.get(ReviewQueueItem, item_id)
        with pytest.raises(render.RenderRefused, match="deadline"):
            render.render(s, item, issued=dt.date(2099, 1, 1))


@needs_db
def test_a_report_whose_call_has_since_closed_is_not_approved(world):
    factory, run_id = tc.verified_run(world)
    item, _ = tc.composed(factory, run_id, tc.prose())
    with factory() as s, pytest.raises(reports.ReviewError):
        reports.approve(
            s,
            s.get(ReviewQueueItem, item.id),
            note="",
            now=dt.datetime(2099, 1, 1, tzinfo=dt.UTC),
        )


def test_the_screen_preview_says_a_passed_deadline_in_ink():
    page = html()  # issued 30.09.2026, the deadline 21.08.2026
    assert '<span class="deadline deadline--passed">21.08.2026, рокот помина</span>' in page
    later = render.html_of(draft(), issued=dt.date(2026, 8, 1), reference="И-1")
    assert "рокот помина" not in later


def test_one_label_for_the_date_of_the_check():
    """F30: «Последна проверка» everywhere, never «Состојба на»."""
    text = render.visible_text(html())
    assert "Последна проверка" in text and "Состојба на" not in text


def test_the_legend_is_a_table_so_a_label_never_wraps_into_its_meaning():
    """F28."""
    page = html()
    assert '<table class="legend">' in page
    assert ".legend th { white-space: nowrap;" in render.report_css()


@pytest.mark.parametrize(
    ("line", "said"),
    [
        ("- Старост: 81–93 месеци", "6–7 години"),
        ("- Старост: 0–5 месеци", "помалку од една година"),
        ("- Вработени: 10–49", "10–49"),
    ],
)
def test_the_applicant_is_said_to_a_reader_in_years(line, said):
    """F23, the report's half: the draft keeps the model's months, paper says years."""
    text = render.visible_text(html(draft(applicant=line)))
    assert said in text and "месеци" not in text


def test_the_print_scale_is_tokens():
    """F07: report.css has no font size of its own; tokens.css holds the print scale."""
    import re

    css = render.report_css()
    assert not re.search(r"font-size:\s*\d", css)
    assert "--print-10-5: 10.5pt" in render.token_values()


def test_the_screen_view_is_the_same_document():
    """The roadmap's DS6 acceptance: the screen and the paper say the same things in the
    same order, because they are one template."""
    paper = render.html_of(draft(), issued=ISSUED, reference="И-1")
    screen = render.html_of(draft(), issued=ISSUED, reference="И-1", screen=("/t.css", "/r.css"))
    assert render.visible_text(paper) == render.visible_text(screen)
    assert '@import url("/t.css");' in screen and 'href="/r.css"' in screen
    assert "file://" not in screen  # a browser cannot load the merged font files


@needs_db
def test_the_admin_shows_the_report_as_a_document(world, admin):
    factory, run_id = tc.verified_run(world)
    item, _ = tc.composed(factory, run_id, tc.prose())

    page = admin.get(f"/admin/izveshtaj/{item.id}").get_data(as_text=True)
    assert f"/admin/izveshtaj/{item.id}/dokument" in page
    document = admin.get(f"/admin/izveshtaj/{item.id}/dokument")
    assert document.status_code == 200 and "Извештај за подобност" in document.get_data(
        as_text=True
    )
    css = admin.get("/admin/izveshtaj/report.css")
    assert css.mimetype == "text/css" and "@media screen" in css.get_data(as_text=True)


# ------------------------------------------------------------- DL5: the design language


def test_paper_is_set_in_the_sites_one_family():
    """DL5: Inter on paper as on screen; the weights do what a second face did."""
    assert {family for family, _, _ in render.FACES} == {"Inter"}
    assert '--font-print: "Inter"' in render.token_values()
    assert "Fira" not in render.report_css() and "Source Serif" not in render.report_css()


def test_each_merged_weight_has_a_name_of_its_own():
    """Every static cut of Inter is called «Inter-Regular»; three files under one name is
    the mix-up the merge exists to prevent (P2 s35), so each is named for its weight."""
    from fontTools.ttLib import TTFont

    folder = render.pdf_fonts()
    names = [
        TTFont(folder / pattern.format("all").replace(".woff2", ".ttf"))["name"].getDebugName(6)
        for _, _, pattern in render.FACES
    ]
    assert names == ["Inter-Regular", "Inter-SemiBold", "Inter-Bold"]


def test_the_screen_view_draws_the_sites_verdict_symbols():
    """On screen the verdicts are the site's symbols; on paper the four printed marks the
    pixel test reads (WeasyPrint has no mask)."""
    css = render.report_css()
    screen = css[css.index("@media screen") :]
    assert "var(--sym-needs-verification)" in screen and "var(--sym-cite)" in screen
    assert "--sym-" not in css[: css.index("@media screen")]
