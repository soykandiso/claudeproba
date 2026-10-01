"""`/stil`: every design token and every component in every state (DS2, DS3).

Development only, like `/demo`: it is a page for the person building screens, not a
customer screen. It reads `tokens.css` on every request rather than keeping its own
list, so it cannot fall behind the file it shows; a test fails if a token in the
file is missing from the page.

Contrast is computed here from the token values, not copied from the skill, so a
changed colour shows its new ratio the moment it is saved (WCAG 2.1 relative
luminance; 4.5:1 for text, 3:1 for a control's boundary).
"""

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from flask import Blueprint, render_template, request

bp = Blueprint("stil", __name__, url_prefix="/stil")

TOKENS_CSS = Path(__file__).resolve().parents[1] / "static" / "css" / "tokens.css"

# One job each, as the skill gives them. A colour without a job here fails a test:
# a token nobody can say the purpose of is the start of a second palette.
COLOUR_JOBS = {
    "paper": "Подлога на страницата.",
    "paper-sunk": "Вдлабната подлога на цитиран пасус од повикот.",
    "ink": "Главен текст.",
    "ink-soft": "Споредни реченици и ознаки.",
    "rule": "Линии што само одделуваат. Никогаш единствена граница на контрола.",
    "rule-strong": "Граница што ја дефинира контролата: поле, избор, копче.",
    "seal": "Само рокови: часовникот тече.",
    "verified": "Само ознаката на цитат.",
}

# What each step of the type scale is for (tokens.css, the comment above --measure).
TYPE_JOBS = {
    "text-12": "Само идентификатори што се копираат или споредуваат.",
    "text-14": "Ознаки: dt, ознака на оценка, изворна линија.",
    "text-16": "Текст. Ништо што се чита не е помало.",
    "text-20": "Цитат, наслов на повик.",
    "text-28": "Наслов на телефон; h2 на поширок екран.",
    "text-40": "h1 од 768px нагоре.",
    "text-64": "Само насловот на почетната страница.",
}

# The text colours are measured against both grounds; the rest against paper only.
TEXT_COLOURS = ("ink", "ink-soft", "seal", "verified")
GROUNDS = ("paper", "paper-sunk")

# Macedonian letters that a Russian-only subset lacks, and the five whose italic
# form is Macedonian-specific (locl, MKD).
MK_LETTERS = "Ѓѓ Ќќ Љљ Њњ Џџ Ѕѕ Јј"
MK_ITALIC = "б г д п т"


@dataclass(frozen=True)
class Token:
    name: str
    value: str


def tokens(css: str | None = None) -> list[Token]:
    """Every custom property in the :root block, in file order."""
    css = css if css is not None else TOKENS_CSS.read_text(encoding="utf-8")
    root = css[css.index(":root") :]
    return [Token(m[1], m[2].strip()) for m in re.finditer(r"--([a-z0-9-]+):\s*([^;]+);", root)]


def _luminance(hex_value: str) -> float:
    h = hex_value.lstrip("#")
    channels = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def _ratio(value: float) -> str:
    # Macedonian decimal comma, as every number on the site.
    return f"{value:.1f}".replace(".", ",")


def _deadlines(today: dt.date) -> list[tuple[str, dt.date | None]]:
    """One deadline in each state the component has, counted from today."""
    return [
        ("Нема рок", None),
        ("За месец", today + dt.timedelta(days=30)),
        ("За девет дена", today + dt.timedelta(days=9)),
        ("Утре", today + dt.timedelta(days=1)),
        ("Денес", today),
        ("Поминал", today - dt.timedelta(days=3)),
    ]


@bp.get("/")
def index():
    all_tokens = tokens()
    by_name = {t.name: t.value for t in all_tokens}
    colours = [t for t in all_tokens if t.value.startswith("#")]
    pairs = []
    for fg in TEXT_COLOURS + ("rule-strong", "rule"):
        for ground in GROUNDS if fg in TEXT_COLOURS else ("paper",):
            ratio = contrast(by_name[fg], by_name[ground])
            need = 4.5 if fg in TEXT_COLOURS else 3.0
            pairs.append(
                {
                    "fg": fg,
                    "ground": ground,
                    "ratio": _ratio(ratio),
                    "need": _ratio(need),
                    # --rule is a divider and is allowed under 3:1 (skill, Color).
                    "ok": ratio >= need or fg == "rule",
                }
            )
    return render_template(
        "stil/index.html",
        colours=colours,
        colour_jobs=COLOUR_JOBS,
        text=[t for t in all_tokens if t.name.startswith("text-")],
        type_jobs=TYPE_JOBS,
        space=[t for t in all_tokens if t.name.startswith("s-")],
        lines=[t for t in all_tokens if t.name in ("rule-w", "mark-w", "rule-w-strong", "mark")],
        controls=[t for t in all_tokens if t.name in ("target", "control", "check", "radius")],
        widths=[
            t for t in all_tokens if t.name == "measure" or t.name.startswith(("width-", "col-"))
        ],
        fonts=[t for t in all_tokens if t.name.startswith("font-")],
        pairs=pairs,
        all_names=[t.name for t in all_tokens],
        mk_letters=MK_LETTERS,
        mk_italic=MK_ITALIC,
        today=dt.date.today(),
        deadlines=_deadlines(dt.date.today()),
        # ?siv=1 shows the components in greyscale: the verdicts must still tell apart.
        grey=request.args.get("siv") == "1",
    )
