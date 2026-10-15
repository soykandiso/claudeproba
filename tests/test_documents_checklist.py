"""What the applicant must still provide (roadmap P5 s57).

The acceptance: "every package ships a list of what the applicant must still provide". The
list is made from what the engine left unfilled and what the manifests ask to attach, never
written by hand, so nothing the documents need can be missing from it.
"""

import datetime as dt
import io

import docx
import pytest

from app import create_app
from app.config import load_settings
from app.documents import checklist, engine
from tests.test_documents_engine import FORM, VALUES, template

REQUEST = checklist.Manifest(
    title_mk="Барање за поддршка",
    attachments=[
        checklist.Asked(key="tekovna_sostojba", note_mk="Не постара од шест месеци."),
        checklist.Asked(key="ujp_potvrda"),
    ],
)
STATEMENT = checklist.Manifest(
    title_mk="Изјава на барателот",
    attachments=[checklist.Asked(key="tekovna_sostojba")],
)
DECLARATION = template("Изјавувам: {{r declaration_no_tax_debt }}", "{{r signature_and_stamp }}")


def _package():
    return [
        (REQUEST, engine.render(FORM, VALUES)),
        (STATEMENT, engine.render(DECLARATION, {})),
    ]


def test_everything_left_unfilled_and_every_attachment_is_on_the_list():
    items = checklist.build(_package())
    unfilled = {u.key for _, rendered in _package() for u in rendered.unfilled}
    fields = {i.key for i in items if i.reason != "attachment"}
    assert fields == unfilled
    assert {i.key for i in items if i.reason == "attachment"} == {"tekovna_sostojba", "ujp_potvrda"}


def test_a_field_in_two_documents_is_one_line_naming_both():
    items = {i.key: i for i in checklist.build(_package())}
    assert items["signature_and_stamp"].documents == ["Барање за поддршка", "Изјава на барателот"]
    assert items["tekovna_sostojba"].documents == ["Барање за поддршка", "Изјава на барателот"]
    assert items["tekovna_sostojba"].notes_mk == ["Не постара од шест месеци."]


def test_the_list_runs_in_the_order_an_applicant_works_through_it():
    groups = [i.group for i in checklist.build(_package())]
    assert groups == sorted(groups, key=list(checklist.HEADINGS).index)
    by_key = {i.key: i.group for i in checklist.build(_package())}
    assert by_key["requested_amount"] == "money"
    assert by_key["declaration_no_tax_debt"] == "declaration"
    assert by_key["signature_and_stamp"] == "signature"
    assert by_key["applicant_edb"] == "data"


def test_the_printed_checklist_says_every_item_how_and_where():
    items = checklist.build(_package())
    printed = checklist.to_docx(
        items, applicant="Пекара Проба ДООЕЛ", call="Јавен повик за микро", on=dt.date(2026, 10, 15)
    )
    text = engine.text_of(printed)
    for item in items:
        assert f"{checklist.BOX} {item.label_mk}" in text
    assert "Се добива од Централниот регистар" in text and "Не постара од шест месеци." in text
    assert "Овој податок не го имаме; внесете го." in text  # the ЕДБ the order lacked
    assert "Составено на: 15.10.2026" in text and "нацрт" in text
    assert docx.Document(io.BytesIO(printed)).core_properties.language == "mk-MK"


def test_the_stored_rows_carry_the_whole_list():
    rows = checklist.as_rows(checklist.build(_package()))
    assert {r["key"] for r in rows} >= {"requested_amount", "tekovna_sostojba"}
    assert all(
        set(r) == {"group", "key", "label_mk", "reason", "documents", "how_mk", "notes_mk"}
        for r in rows
    )


def test_a_banned_phrase_stops_the_checklist(monkeypatch):
    bad = checklist.Attachment(label_mk="Потврда", how_mk="Финансирањето е гарантирано.")
    real = dict(checklist.catalogue())
    monkeypatch.setattr(checklist, "catalogue", lambda: {**real, "ujp_potvrda": bad})
    with pytest.raises(checklist.ChecklistRefused, match="banned"):
        checklist.to_docx(
            checklist.build(_package()), applicant="а", call="б", on=dt.date(2026, 1, 1)
        )


def test_a_template_without_a_manifest_or_with_an_unknown_attachment_is_refused(tmp_path):
    form = tmp_path / "2026-10-15.docx"
    form.write_bytes(FORM)
    runner = create_app(load_settings(env="testing")).test_cli_runner()
    assert "no manifest" in runner.invoke(args=["documents", "check", str(form)]).output

    form.with_suffix(".yaml").write_text(
        "title_mk: Барање\nattachments:\n  - key: horoscope\n", encoding="utf-8"
    )
    assert "horoscope" in runner.invoke(args=["documents", "check", str(form)]).output

    form.with_suffix(".yaml").write_text(
        "title_mk: Барање\nattachments:\n  - key: ponudi\n    note_mk: Три понуди.\n",
        encoding="utf-8",
    )
    done = runner.invoke(args=["documents", "check", str(form)])
    assert done.exit_code == 0 and "1 of 1 templates can be filled" in done.output


def test_every_catalogue_entry_is_complete():
    assert all(a.label_mk and a.how_mk for a in checklist.catalogue().values())
