"""Every document in a package says what it is: a draft for the applicant to complete
(roadmap P5 s74, brief §8: "the UI must say so", and on the artefact itself).

The documents are the institutions' own forms, which the applicant signs and submits. Our
words must not be printed on them, so the label is a **Word comment** anchored at the top of
the document (seen in the margin on opening, removed with «Избриши коментар» before
printing) and the **document properties** (title, subject, keywords, comments), which travel
with the file and print nowhere. The checklist, our own document, says it in its text.

Today nothing in a package is written by a model: every value comes from the order and the
profile, every gap is a highlighted marker. The label says exactly that. When a model drafts
a field (a project description, later), the label says so too (`model_drafted`), and so does
`generated_document.is_ai_assisted`.
"""

import datetime as dt
import io

import docx

from app.reports.lint import find_banned
from app.web.format import mkdate

AUTHOR = "Грантови и субвенции"
INITIALS = "ГС"
KEYWORD = "нацрт за дополнување"


class LabelRefused(ValueError):
    """The label's own words did not pass the lint; nothing was produced."""


def words(on: dt.date, *, model_drafted: bool = False) -> str:
    """The comment's text: what the document is, what is the applicant's, what to do."""
    made = (
        "Дел од текстот го подготви компјутерски модел; проверете го секој збор."
        if model_drafted
        else "Податоците се преземени од нарачката и од профилот што го внесовте; "
        "ништо не е измислено."
    )
    return (
        f"НАЦРТ ЗА ДОПОЛНУВАЊЕ, подготвен на {mkdate(on)} од платформата {AUTHOR}. {made} "
        "Полињата означени со жолто ги пополнувате вие, со вистинските податоци на субјектот. "
        "Образецот е на институцијата: проверете дали е последната верзија. "
        "Пред печатење и поднесување избришете го овој коментар."
    )


def label(document_bytes: bytes, on: dt.date, *, model_drafted: bool = False) -> bytes:
    """The document with the draft label as a comment and in its properties."""
    text = words(on, model_drafted=model_drafted)
    banned = find_banned(text)
    if banned:
        raise LabelRefused(f"banned phrase in the label: {banned}")
    document = docx.Document(io.BytesIO(document_bytes))
    anchor = next((p.runs for p in document.paragraphs if p.runs and p.text.strip()), None)
    if anchor is None:  # a form that opens with a table: anchor in its first cell
        cell = document.tables[0].rows[0].cells[0]
        anchor = cell.paragraphs[0].runs or [cell.paragraphs[0].add_run("")]
    document.add_comment(anchor, text=text, author=AUTHOR, initials=INITIALS)
    properties = document.core_properties
    properties.subject = "Нацрт за дополнување"
    properties.keywords = KEYWORD
    # Word keeps at most 255 characters here; the whole text is in the comment.
    properties.comments = (
        f"Нацрт за дополнување од {AUTHOR}, {mkdate(on)}. Пред поднесување проверете."
    )
    properties.last_modified_by = AUTHOR
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def is_labelled(document_bytes: bytes) -> bool:
    document = docx.Document(io.BytesIO(document_bytes))
    return KEYWORD in (document.core_properties.keywords or "") and any(
        c.author == AUTHOR and "НАЦРТ ЗА ДОПОЛНУВАЊЕ" in c.text for c in document.comments
    )
