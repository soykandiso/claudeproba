"""HTML → text with selectolax.

Block elements end a line; inline elements join with nothing added, so text
split across styled spans reads as it renders. Table cells in a row are joined
with " | ", which keeps tabular eligibility conditions on one line each.
"""

import re

from selectolax.lexbor import LexborHTMLParser, LexborNode

from app.ingestion.normalise import Normalised, NormaliseError, letters
from app.ingestion.normalise.text import canonical
from app.models.enums import TextSource

BLOCK = {
    "address", "article", "aside", "blockquote", "caption", "dd", "details", "dialog", "div",
    "dl", "dt", "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
    "h5", "h6", "header", "hr", "li", "main", "nav", "ol", "p", "section", "summary", "table",
    "tbody", "tfoot", "thead", "ul",
}  # fmt: skip
CELL = {"td", "th"}
SKIP = {
    "script", "style", "noscript", "template", "svg", "head", "iframe", "object", "select",
    "input", "textarea", "button", "canvas",
}  # fmt: skip

_CELL_MARK = "\ue000"  # private use: never occurs in real text
_HTML_WHITESPACE = re.compile(r"[ \t\n\r\f]+")


def normalise_html(markup: str, root: str | None = None) -> Normalised:
    """`root` is a CSS selector for the content area; missing it is an error, not a fallback.

    A selector that stops matching means the page layout changed, and normalising
    the whole page instead would quietly put navigation text into citations.
    """
    tree = LexborHTMLParser(markup)
    if root is not None:
        node = tree.css_first(root)
        if node is None:
            raise NormaliseError(
                f"content selector {root!r} matched nothing; has the layout changed?"
            )
    else:
        node = tree.body or tree.root
    if node is None:
        raise NormaliseError("document has no body")

    parts: list[str] = []
    _walk(node, parts, preformatted=False)
    text = canonical(_cells("".join(parts)))
    reasons = () if letters(text) else ("no text found in the HTML",)
    return Normalised(text, TextSource.NATIVE, review_reasons=reasons)


def _walk(node: LexborNode, parts: list[str], preformatted: bool) -> None:
    for child in node.iter(include_text=True):
        tag = child.tag
        if tag == "-text":
            value = child.text_content or ""
            parts.append(value if preformatted else _HTML_WHITESPACE.sub(" ", value))
        elif tag in SKIP or tag == "-comment":
            continue
        elif tag == "br":
            parts.append("\n")
        elif tag == "tr":
            # Rows end a line without a blank one, so a table reads as a block.
            _walk(child, parts, preformatted)
            parts.append("\n")
        elif tag in CELL:
            parts.append(_CELL_MARK)
            _walk(child, parts, preformatted)
        elif tag in BLOCK or tag == "pre":
            parts.append("\n")
            _walk(child, parts, preformatted or tag == "pre")
            parts.append("\n")
        else:
            _walk(child, parts, preformatted)


def _cells(text: str) -> str:
    lines = []
    for line in text.split("\n"):
        if _CELL_MARK in line:
            cells = [cell.strip() for cell in line.split(_CELL_MARK)]
            line = " | ".join(cell for cell in cells if cell)
        lines.append(line)
    return "\n".join(lines)
