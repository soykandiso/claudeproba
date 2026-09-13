"""DOCX → text with the standard library.

Economy published at least one call only as DOCX (docs/sources.md §6.2). Body
paragraphs and tables in document order; runs join with nothing added; tracked
deletions are skipped and insertions kept, which is what the document shows.
"""

import io
import zipfile
from xml.etree import ElementTree

from app.ingestion.normalise import Normalised, NormaliseError, UnsupportedFormat, letters
from app.ingestion.normalise.text import canonical
from app.models.enums import TextSource

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def normalise_docx(content: bytes) -> Normalised:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise NormaliseError("not a readable ZIP archive") from exc
    if "word/document.xml" not in archive.namelist():
        raise UnsupportedFormat("ZIP archive is not a Word document (xlsx, pptx or a bundle?)")
    root = ElementTree.fromstring(archive.read("word/document.xml"))
    body = root.find(f"{W}body")
    if body is None:
        raise NormaliseError("Word document has no body")

    lines: list[str] = []
    _blocks(body, lines)
    text = canonical("\n".join(lines))
    reasons = () if letters(text) else ("no text found in the Word document",)
    return Normalised(text, TextSource.NATIVE, review_reasons=reasons)


def _blocks(parent: ElementTree.Element, lines: list[str]) -> None:
    for element in parent:
        if element.tag == f"{W}p":
            lines.append(_paragraph(element))
        elif element.tag == f"{W}tbl":
            for row in element.findall(f"{W}tr"):
                cells = []
                for cell in row.findall(f"{W}tc"):
                    cell_lines: list[str] = []
                    _blocks(cell, cell_lines)  # cells hold paragraphs and nested tables
                    cells.append([line for line in cell_lines if line.strip()])
                cells = [c for c in cells if c]
                if len(cells) == 1:
                    # A one-cell row is a layout box, not a table: Economy wraps a whole
                    # call in one. Its paragraphs stay paragraphs.
                    lines.extend(cells[0])
                elif cells:
                    lines.append(" | ".join(" ".join(c) for c in cells))
        elif element.tag == f"{W}sdt":  # content controls wrap ordinary blocks
            content = element.find(f"{W}sdtContent")
            if content is not None:
                _blocks(content, lines)


def _paragraph(paragraph: ElementTree.Element) -> str:
    out: list[str] = []
    for node in paragraph.iter():
        if node.tag == f"{W}t" and node.text:
            out.append(node.text)
        elif node.tag == f"{W}tab":
            out.append(" ")
        elif node.tag in (f"{W}br", f"{W}cr"):
            out.append("\n")
        elif node.tag == f"{W}noBreakHyphen":
            out.append("-")
    return "".join(out)
