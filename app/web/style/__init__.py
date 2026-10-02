"""`/stil`: every design token and every component in every state, in both themes
(DS2, DS3, DL1).

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

# One job each. A colour without a job here fails a test: a token nobody can say the
# purpose of is the start of a second palette.
COLOUR_JOBS = {
    "bg": "Подлога на страницата, како групираната позадина на iOS.",
    "surface": "Подлога на содржината: листа, картичка, поле.",
    "fill": "Вдлабната подлога: цитиран пасус, оневозможена контрола.",
    "label": "Главен текст.",
    "label-2": "Споредни реченици.",
    "label-3": "Ознаки и помошен текст.",
    "separator": "Линии што само одделуваат. Никогаш единствена граница на контрола.",
    "separator-strong": "Граница што ја дефинира контролата: поле, избор.",
    "tint": "Дејство и избор: врска, копче, фокус.",
    "tint-strong": "Подлога на главното копче.",
    "on-tint": "Текст на главното копче.",
    "deadline": "Само рокови: часовникот тече.",
    "verified": "Само ознаката на цитат.",
    "glass-solid": "Стаклото без замаглување: стар прелистувач, или помалку провидност.",
}

# What each step of the type scale is for (tokens.css).
TYPE_JOBS = {
    "text-caption": "Само идентификатори што се копираат или споредуваат.",
    "text-footnote": "Ознаки: dt, ознака на оценка, изворна линија.",
    "text-subhead": "Споредни реченици. Ништо што се чита не е помало.",
    "text-body": "Текст, како на iPhone.",
    "text-title3": "Цитат, наслов на повик.",
    "text-title2": "Наслов на дел.",
    "text-title1": "Наслов на страница на телефон.",
    "text-large": "Наслов на страница од 768px нагоре.",
    "text-display": "Само насловот на почетната страница.",
}

# Text colours against both grounds; a control's boundary against both at 3:1.
TEXT_COLOURS = ("label", "label-2", "label-3", "tint", "deadline", "verified")
GROUNDS = ("bg", "surface", "fill")
THEMES = ("light", "dark")

# Macedonian letters that a Russian-only subset lacks, and the five whose italic
# form is Macedonian-specific (locl, MKD).
MK_LETTERS = "Ѓѓ Ќќ Љљ Њњ Џџ Ѕѕ Јј"


@dataclass(frozen=True)
class Token:
    name: str
    value: str


def _block(css: str, selector: str) -> str:
    """The declarations of the first rule whose selector is exactly `selector`."""
    start = css.index(selector + " {")
    return css[start : css.index("}", start)]


def _declared(block: str) -> list[Token]:
    return [Token(m[1], m[2].strip()) for m in re.finditer(r"--([a-z0-9-]+):\s*([^;]+);", block)]


def tokens(css: str | None = None) -> list[Token]:
    """Every custom property of the light :root block, in file order."""
    css = css if css is not None else TOKENS_CSS.read_text(encoding="utf-8")
    return _declared(_block(css, ":root"))


def dark_tokens(css: str | None = None) -> dict[str, str]:
    """What the dark theme changes (the explicit data-theme block; a test keeps the
    prefers-color-scheme block identical to it)."""
    css = css if css is not None else TOKENS_CSS.read_text(encoding="utf-8")
    return {t.name: t.value for t in _declared(_block(css, ':root[data-theme="dark"]'))}


def themes() -> dict[str, dict[str, str]]:
    light = {t.name: t.value for t in tokens()}
    return {"light": light, "dark": {**light, **dark_tokens()}}


def pairs() -> list[dict]:
    """Every contrast pair that must pass, in both themes, measured from the values."""
    out = []
    for theme, values in themes().items():
        checks = [(fg, g, 4.5) for fg in TEXT_COLOURS for g in GROUNDS]
        checks += [("on-tint", "tint-strong", 4.5)]
        checks += [("separator-strong", g, 3.0) for g in GROUNDS]
        checks += [("tint", g, 3.0) for g in GROUNDS]  # a focus ring
        for fg, ground, need in checks:
            ratio = contrast(values[fg], values[ground])
            out.append(
                {
                    "theme": theme,
                    "fg": fg,
                    "ground": ground,
                    "value": ratio,
                    "ratio": _ratio(ratio),
                    "need": _ratio(need),
                    "ok": ratio >= need,
                }
            )
    return out


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
    dark = dark_tokens()
    colours = [t for t in all_tokens if t.value.startswith("#")]
    return render_template(
        "stil/index.html",
        colours=colours,
        dark=dark,
        colour_jobs=COLOUR_JOBS,
        text=[t for t in all_tokens if t.name.startswith("text-")],
        type_jobs=TYPE_JOBS,
        space=[t for t in all_tokens if t.name.startswith("s-")],
        lines=[t for t in all_tokens if t.name in ("rule-w", "mark-w", "rule-w-strong", "mark")],
        controls=[
            t
            for t in all_tokens
            if t.name in ("target", "control", "check") or t.name.startswith("radius-")
        ],
        widths=[
            t for t in all_tokens if t.name == "measure" or t.name.startswith(("width-", "col-"))
        ],
        fonts=[t for t in all_tokens if t.name.startswith("font-")],
        materials=[t for t in all_tokens if t.name.startswith(("glass", "shadow-", "tint-soft"))],
        motion=[t for t in all_tokens if t.name.startswith(("ease-", "dur-"))],
        pairs=pairs(),
        all_names=[t.name for t in all_tokens],
        mk_letters=MK_LETTERS,
        today=dt.date.today(),
        deadlines=_deadlines(dt.date.today()),
        # ?siv=1 shows the components in greyscale: the verdicts must still tell apart.
        grey=request.args.get("siv") == "1",
        # ?tema=temna or ?tema=svetla holds one theme, whatever the system says (DL1).
        theme={"temna": "dark", "svetla": "light"}.get(request.args.get("tema", "")),
    )
