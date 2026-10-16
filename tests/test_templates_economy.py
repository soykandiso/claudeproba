"""Template set 2, the Ministry of Economy and Labour's 2026 forms (roadmap P5 s62).

The Ministry's own Word forms from the attachments of three 2026 calls, with fields placed by
`ops/dev/build_economy_templates.py`. Every application form lists its attachments; the
manifests carry them, in the form's words, into the checklist.
"""

import datetime as dt
import io

import docx
import pytest

from app.documents import TEMPLATES, checklist, derive, engine
from tests.test_templates_av import IDENTITY

ECONOMY = sorted((TEMPLATES / "economy").rglob("*.docx"))
CALLS = {
    "msp-2026": ["barane", "izjava", "izjava-drzavna-pomos"],
    "socijalni-praktiki-2026": ["barane", "izjava-drzavna-pomos"],
    "univerziteti-2026": ["barane", "izjava-drzavna-pomos"],
    "oo-2026": ["izjava"],  # the two ОО calls publish one and the same «Изјава 2026»
}


def _fill(path):
    used = {k for k, _ in engine.placeholders(path.read_bytes())}
    values = {**IDENTITY, "applicant_founded": 2010}
    return engine.render(path.read_bytes(), {k: v for k, v in values.items() if k in used})


def test_the_three_calls_forms_are_there():
    found = {}
    for path in ECONOMY:
        found.setdefault(path.parent.parent.name, []).append(path.parent.name)
    assert found == CALLS


@pytest.mark.parametrize("path", ECONOMY, ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_each_template_fills_says_its_source_and_never_fills_money(path):
    assert engine.check(path.read_bytes()) == []
    manifest = checklist.manifest_for(path)
    assert manifest.source_url.startswith("https://portal.mdt.gov.mk/post-body-files/")
    assert manifest.retrieved == dt.date(2026, 10, 16)
    assert (
        any(a.key == "notarska_zaverka" for a in manifest.attachments)
        or path.parent.name == "barane"
    )
    done = _fill(path)
    money = {k for k, f in engine.registry().items() if f.type == "money"}
    assert not money & set(done.filled)
    assert "[Пополнува барателот: Потпис на одговорното лице и печат]" in engine.text_of(done.docx)


def test_the_sme_application_is_filled_where_the_platform_knows_and_marked_where_it_does_not():
    path = TEMPLATES / "economy" / "msp-2026" / "barane" / "2026-05-15.docx"
    done = _fill(path)
    text = engine.text_of(done.docx)
    assert {"applicant_name", "applicant_edb", "applicant_embs", "applicant_founded"} <= set(
        done.filled
    )
    assert "[Пополнува барателот: Барани средства]" in text
    assert "[Пополнува барателот: Жиро сметка на барателот]" in text
    assert "Тековна состојба од Централен регистар" in text  # the Ministry's own list, untouched


def test_the_sme_checklist_carries_the_ministrys_conditions():
    paths = sorted((TEMPLATES / "economy" / "msp-2026").rglob("*.docx"))
    documents = [(checklist.manifest_for(p), _fill(p)) for p in paths]
    items = {i.key: i for i in checklist.build(documents)}
    assert "не постара од 2 (два) месеци" in " ".join(items["tekovna_sostojba"].notes_mk)
    assert "6 (шест) месеци" in " ".join(items["ujp_potvrda"].notes_mk)
    assert "250,00 и 50,00 денари" in " ".join(items["administrativna_taksa"].notes_mk)
    assert len(items["notarska_zaverka"].documents) == 3


# ------------------------------------------------------------------ a blank line above a caption


def _declaration(*paragraphs, border_on=None) -> docx.document.Document:
    document = docx.Document()
    for n, text in enumerate(paragraphs):
        paragraph = document.add_paragraph(text)
        if n == border_on:
            border = docx.oxml.parse_xml(
                '<w:pBdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                '<w:bottom w:val="single" w:sz="4" w:space="1" w:color="auto"/></w:pBdr>'
            )
            paragraph._p.get_or_add_pPr().append(border)
    return document


def test_a_typed_blank_above_its_caption_takes_the_field_and_keeps_the_words():
    document = _declaration("Јас, ________________ , како управител", "(име и презиме )")
    derive.fill_line_above(document, "(име и презиме", "responsible_person")
    assert document.paragraphs[0].text == "Јас, {{r responsible_person }} , како управител"


def test_a_blank_split_across_runs_is_replaced_once():
    document = docx.Document()
    line = document.add_paragraph()
    for text in ("Јас, ____", "______", "__ , како"):
        line.add_run(text)
    document.add_paragraph("(име и презиме)")
    derive.fill_line_above(document, "(име и презиме", "responsible_person")
    assert line.text == "Јас, {{r responsible_person }} , како"


def test_a_drawn_line_above_its_caption_takes_the_field():
    document = _declaration("", "(полн назив на деловниот субјект)", border_on=0)
    derive.fill_line_above(document, "(полн назив", "applicant_name")
    assert document.paragraphs[0].text == "{{r applicant_name }}"
    out = io.BytesIO()
    document.save(out)
    assert engine.check(out.getvalue()) == []


def test_no_line_above_the_caption_is_an_error():
    with pytest.raises(derive.FormChanged, match="no blank line"):
        derive.fill_line_above(
            _declaration("текст", "(име и презиме)"), "(име и презиме", "responsible_person"
        )
