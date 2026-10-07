"""Filling the intake from a тековна состојба (app/matching/tekovna.py).

A real тековна carries a person's name, the company's ЕМБС and ЕДБ and addresses, so none
is in this repository. The documents here are invented, rendered with the labels CRM
prints; the CRM font case (Calibri, Identity-H, no ToUnicode) is tested on a font built
in the test, and was checked on a real тековна by hand (07.10.2026, docs/handoff.md).
"""

import io
from pathlib import Path

import pytest
from fontTools.fontBuilder import FontBuilder

from app.matching import reference, tekovna
from app.reports import render

FAKE = """<!doctype html><html lang="mk"><body style="font-family: sans-serif">
<p>ПОДАТОЦИ ЗА СУБЈЕКТОТ</p>
<p>ЕМБС:<br>1234567</p>
<p>Целосен назив:<br>Друштво за пекарство ИЗМИСЛЕНА ДООЕЛ Битола</p>
<p>Седиште:<br>ИЗМИСЛЕНА бр.1 БИТОЛА - БИТОЛА,<br>{seat}</p>
<p>Вид на субјект на упис:<br>{form}</p>
<p>Датум на основање:<br>{founded} г.</p>
<p>ЕДБ:<br>4000000000000</p>
<p>Т Е К О В Н А  С О С Т О Ј Б А</p>
<p>СОПСТВЕНИЦИ</p><p>Име и презиме/Назив:<br>ИЗМИСЛЕНО ЛИЦЕ</p>
<p>Приоритетна дејност/<br>Главна приходна шифра:<br>{activity}</p>
<p>ОПШТА КЛАУЗУЛА ЗА БИЗНИС</p>
<p>www.crm.com.mk</p>
</body></html>"""


def fake(seat="БИТОЛА", form="ДООЕЛ", founded="03.04.2019", activity="10.71 - Производство на леб"):
    return render._pdf(FAKE.format(seat=seat, form=form, founded=founded, activity=activity))


pytestmark = pytest.mark.skipif(not hasattr(render, "_pdf"), reason="WeasyPrint is not available")


def test_the_four_answers_and_nothing_else():
    reading = tekovna.read(fake())
    assert reading.answers() == {
        "entity": "dooel",
        "municipality": reference.resolve_municipality("Битола").code,
        "founded": "2019",
        "nace": "10.71",
    }
    assert reading.nace_certainty == "exact" and reading.unread == []
    # The name, ЕМБС, ЕДБ and the owner are read past, not returned.
    assert "1234567" not in repr(reading) and "ИЗМИСЛЕНО ЛИЦЕ" not in repr(reading)


def test_crms_activity_code_is_read_carefully():
    """CRM writes 80.010 where НКД writes 80.10: one reading that exists is used and marked
    for checking; none or two, only the division, which is certain."""
    assert tekovna._activity("80.010 - Истражни дејности") == ("80.10", "check")
    assert tekovna._activity("10.71 - Леб") == ("10.71", "exact")
    assert tekovna._activity("80.000 - нешто") == ("80", "division")
    assert tekovna._activity("без шифра") == (None, None)


def test_a_form_the_intake_does_not_offer_is_left_to_the_person():
    reading = tekovna.read(fake(form="КД"))
    assert reading.entity is None and "entity" in reading.unread


@pytest.mark.parametrize(
    "document",
    [b"not a pdf", b"%PDF-1.4 broken", b"x" * (tekovna.MAX_BYTES + 1)],
    ids=["not a pdf", "broken", "too large"],
)
def test_anything_else_is_refused(document):
    with pytest.raises(tekovna.NotATekovna):
        tekovna.read(document)


def test_a_pdf_that_is_not_a_tekovna_is_refused():
    with pytest.raises(tekovna.NotATekovna):
        tekovna.read(render._pdf("<p>Фактура бр. 12</p>"))


def test_crms_font_is_read_through_its_own_character_map():
    """The real case: a Type0 font, Identity-H, no ToUnicode, glyph numbers for text."""
    builder = FontBuilder(1000, isTTF=True)
    builder.setupGlyphOrder([".notdef", "uni0414", "uni041E"])
    builder.setupCharacterMap({0x414: "uni0414", 0x41E: "uni041E"})
    builder.setupGlyf({name: _empty_glyph() for name in [".notdef", "uni0414", "uni041E"]})
    builder.setupHorizontalMetrics({n: (500, 0) for n in [".notdef", "uni0414", "uni041E"]})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupNameTable({"familyName": "T", "styleName": "R"})
    builder.setupOS2()
    builder.setupPost()
    data = io.BytesIO()
    builder.save(data)

    font = _Obj(
        {
            "/Subtype": "/Type0",
            "/DescendantFonts": [
                _Obj({"/FontDescriptor": _Obj({"/FontFile2": _Obj({}, data.getvalue())})})
            ],
        }
    )
    assert tekovna._glyph_letters(font) == {1: "Д", 2: "О"}
    # With a ToUnicode table, the text is read as it is.
    assert tekovna._glyph_letters(_Obj({"/Subtype": "/Type0", "/ToUnicode": object()})) is None


def test_the_reader_never_reaches_a_model():
    """Invariant 4: the module that reads a document full of identity data imports no gateway."""
    source = Path(tekovna.__file__).read_text(encoding="utf-8")
    assert "app.ai" not in source and "gateway" not in source


# ------------------------------------------------------------------ the form


def _csrf(client) -> str:
    client.get("/profil/")
    with client.session_transaction() as s:
        return s["csrf"]


def test_uploading_fills_the_form_and_saves_nothing(client):
    token = _csrf(client)
    response = client.post(
        "/profil/tekovna",
        data={"csrf": token, "tekovna": (io.BytesIO(fake()), "tekovna.pdf")},
        content_type="multipart/form-data",
    )
    page = response.get_data(as_text=True)
    assert response.status_code == 200 and "Ја прочитавме тековната" in page
    assert 'value="dooel" selected' in page and 'value="2019"' in page
    assert 'href="#employees"' in page  # the one required answer still to give
    with client.session_transaction() as s:
        assert "profile" not in s  # nothing kept until the person saves the form


def test_a_file_that_is_not_a_tekovna_says_so_and_leaves_the_form(client):
    token = _csrf(client)
    response = client.post(
        "/profil/tekovna",
        data={"csrf": token, "tekovna": (io.BytesIO(b"hello"), "x.pdf")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 422
    assert "не изгледа како тековна" in response.get_data(as_text=True)


def test_the_demo_form_has_no_upload(client):
    assert 'name="tekovna"' not in client.get("/demo/profil").get_data(as_text=True)
    assert 'name="tekovna"' in client.get("/profil/").get_data(as_text=True)


# ------------------------------------------------------------------ helpers


class _Obj(dict):
    """Enough of a pypdf object for _glyph_letters: get_object() and get_data()."""

    def __init__(self, items, data=b""):
        super().__init__(items)
        self._data = data

    def get_object(self):
        return self

    def get_data(self):
        return self._data


def _empty_glyph():
    from fontTools.pens.ttGlyphPen import TTGlyphPen

    return TTGlyphPen(None).glyph()
