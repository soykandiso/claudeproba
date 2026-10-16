"""The draft label on every document of a package (roadmap P5 s74).

The acceptance: "labelling appears on the artefact itself, not only on the web page". On a
form the applicant submits, it is a comment and the properties, never printed text.
"""

import datetime as dt
import io

import docx
import pytest

from app.documents import TEMPLATES, engine, label
from tests.test_templates_av import IDENTITY

ON = dt.date(2026, 10, 16)
ALL = sorted(TEMPLATES.rglob("*.docx"))


def _filled(path):
    used = {k for k, _ in engine.placeholders(path.read_bytes())}
    return engine.render(path.read_bytes(), {k: v for k, v in IDENTITY.items() if k in used}).docx


@pytest.mark.parametrize("path", ALL, ids=lambda p: f"{p.parent.parent.name}/{p.parent.name}")
def test_every_template_can_carry_the_label(path):
    assert label.is_labelled(label.label(_filled(path), ON))


def test_the_label_is_a_comment_and_properties_never_text_on_the_form():
    path = TEMPLATES / "av" / "ppr" / "2024-04-11.docx"
    before, after = _filled(path), label.label(_filled(path), ON)
    assert engine.text_of(before) == engine.text_of(after)  # not one printed word added
    document = docx.Document(io.BytesIO(after))
    comment = document.comments.get(0)
    assert comment.author == "Грантови и субвенции" and "16.10.2026" in comment.text
    assert "избришете го овој коментар" in comment.text
    assert document.core_properties.keywords == "нацрт за дополнување"


def test_the_label_says_honestly_who_wrote_what():
    assert "ништо не е измислено" in label.words(ON)
    assert "компјутерски модел" not in label.words(ON)
    assert "компјутерски модел" in label.words(ON, model_drafted=True)


def test_an_unlabelled_document_is_seen_as_such():
    assert not label.is_labelled(_filled(TEMPLATES / "av" / "ppr" / "2024-04-11.docx"))


def test_the_labels_words_pass_the_lint(monkeypatch):
    monkeypatch.setattr(
        label, "words", lambda on, model_drafted=False: "Средствата се гарантирани."
    )
    with pytest.raises(label.LabelRefused):
        label.label(_filled(TEMPLATES / "av" / "ppr" / "2024-04-11.docx"), ON)
