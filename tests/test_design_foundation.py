"""The design foundation holds (design phase DS2).

These are the rules of `.claude/skills/design-system` that a file can be checked
against without a browser: one source of values, no inline style, fonts within
budget and complete for Macedonian, and a /stil page that cannot fall behind
tokens.css. What needs eyes (letterforms, greyscale) is on /stil for a person.
"""

import re
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from app import create_app
from app.config import load_settings
from app.web import style

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "app" / "web"
TOKENS = WEB / "static" / "css" / "tokens.css"
FONTS = WEB / "static" / "fonts"

# Every stylesheet and template that reaches a screen or the PDF. Nothing is
# exempt: the demo too, because an exemption is where a second palette starts.
STYLE_FILES = sorted(
    p
    for p in [
        *WEB.rglob("*.css"),
        *WEB.rglob("*.html"),
        *(ROOT / "app" / "reports").rglob("*.css"),
        *(ROOT / "app" / "reports").rglob("*.html"),
    ]
    if p != TOKENS
)
TEMPLATES = sorted(
    [
        *(WEB / "templates").rglob("*.html"),
        *(ROOT / "app" / "reports" / "templates").rglob("*.html"),
    ]
)

COLOUR = re.compile(r"#[0-9A-Fa-f]{3,8}\b|\b(?:rgb|rgba|hsl|hsla)\(")
MK_LETTERS = "ЃѓЌќЉљЊњЏџЅѕЈј"


def _rel(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def test_no_colour_value_outside_tokens_css():
    found = []
    for path in STYLE_FILES:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            # A fragment link (href="#main") is not a colour; a hex needs 3+ hex digits
            # and no letter beyond f, which #main fails. Skip URL fragments anyway.
            scan = re.sub(r'href="[^"]*"', "", line)
            if COLOUR.search(scan):
                found.append(f"{_rel(path)}:{n}: {line.strip()}")
    assert not found, "colour outside tokens.css:\n" + "\n".join(found)


def test_no_inline_style_in_templates():
    """docs/design.md F02: an inline style is a value nobody can find in tokens.css."""
    found = [
        f"{_rel(p)}:{n}"
        for p in TEMPLATES
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r"\sstyle=", line)
    ]
    assert not found, "inline style: " + ", ".join(found)


def test_no_style_block_in_templates():
    """docs/design.md F01: the placeholder had its own <style>. Only the PDF's
    template may inline its stylesheet, because WeasyPrint gets it as one string."""
    found = [
        _rel(p)
        for p in (WEB / "templates").rglob("*.html")
        if "<style" in p.read_text(encoding="utf-8")
    ]
    assert not found, "<style> in " + ", ".join(found)


def test_site_css_takes_every_size_from_a_token():
    """docs/design.md F03. Breakpoints are the one exception: var() cannot be used
    in a media query."""
    found = []
    for name in ("site.css", "stil.css"):
        text = (WEB / "static" / "css" / name).read_text(encoding="utf-8")
        # Comments may name a size ("a 64px word"); blank them, keeping line numbers.
        text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), text, flags=re.S)
        for n, line in enumerate(text.splitlines(), 1):
            # Safari cannot resolve var() inside -webkit-backdrop-filter, so the glass's
            # blur is written out (site.css, materials); and @supports tests a literal.
            if "backdrop-filter" in line:
                continue
            scan = re.sub(r"@media\s*\([^)]*\)", "", line)
            scan = re.sub(r"url\([^)]*\)|unicode-range:[^;]*;", "", scan)
            for m in re.finditer(r"(?<![\w-])-?\d*\.?\d+(px|rem|pt|em)\b", scan):
                # em is allowed: it is relative to the line's own type, not a value.
                if m.group(1) != "em":
                    found.append(f"{name}:{n}: {m.group(0)}")
    assert not found, "raw size:\n" + "\n".join(found)


IOS_SCALE = {
    "caption": 12,
    "footnote": 13,
    "subhead": 15,
    "body": 17,
    "title3": 20,
    "title2": 22,
    "title1": 28,
    "large": 34,
    "display": 48,
}


def test_text_sizes_are_the_scale():
    """The iOS text styles (DL1) and nothing else: body 17, nothing a reader must read
    below subhead 15."""
    sizes = {t.name: t.value for t in style.tokens() if t.name.startswith("text-")}
    assert sizes == {f"text-{n}": f"{px / 16:g}rem" for n, px in IOS_SCALE.items()}


def test_space_is_the_scale():
    space = [t.name for t in style.tokens() if t.name.startswith("s-")]
    assert space == [f"s-{n}" for n in (4, 8, 12, 16, 24, 32, 48, 64, 96)]


def test_every_colour_has_one_job_and_passes_contrast_in_both_themes():
    by_name = {t.name: t.value for t in style.tokens()}
    colours = {n for n, v in by_name.items() if v.startswith("#")}
    assert colours == set(style.COLOUR_JOBS)
    pairs = style.pairs()
    assert {p["theme"] for p in pairs} == {"light", "dark"}
    assert [(p["theme"], p["fg"], p["ground"], p["ratio"]) for p in pairs if not p["ok"]] == []


def _dark_blocks(css: str) -> tuple[str, str]:
    by_system = css[css.index(':root:not([data-theme="light"]) {') :]
    by_system = by_system[by_system.index("{") + 1 : by_system.index("}")]
    explicit = css[css.index(':root[data-theme="dark"] {') :]
    explicit = explicit[explicit.index("{") + 1 : explicit.index("}")]
    return by_system, explicit


def test_the_dark_theme_is_written_once_in_effect():
    """tokens.css repeats the dark values (the system setting, and data-theme for /stil):
    the two copies must say exactly the same."""
    by_system, explicit = _dark_blocks(TOKENS.read_text(encoding="utf-8"))
    norm = lambda b: [line.strip() for line in b.strip().splitlines()]  # noqa: E731
    assert norm(by_system) == norm(explicit)
    # Every colour that has a job is given in dark too, or dark is half a theme.
    dark = style.dark_tokens()
    assert [c for c in style.COLOUR_JOBS if c not in dark] == []


@pytest.mark.parametrize("path", sorted(FONTS.glob("*.woff2")), ids=lambda p: p.name)
def test_font_within_budget(path):
    assert path.stat().st_size <= 40 * 1024


@pytest.mark.parametrize("path", sorted(FONTS.glob("*cyrillic*.woff2")), ids=lambda p: p.name)
def test_cyrillic_subset_has_every_macedonian_letter(path):
    cmap = TTFont(path).getBestCmap()
    assert [ch for ch in MK_LETTERS if ord(ch) not in cmap] == []


@pytest.mark.parametrize(
    "path", sorted(FONTS.glob("source-serif-4-cyrillic-*.woff2")), ids=lambda p: p.name
)
def test_serif_keeps_the_macedonian_language_system(path):
    """docs/design.md F05: the serif is the face Macedonian forms come from."""
    font = TTFont(path)
    langs = {
        lang.LangSysTag
        for sr in font["GSUB"].table.ScriptList.ScriptRecord
        if sr.ScriptTag == "cyrl"
        for lang in sr.Script.LangSysRecord
    }
    assert "MKD " in langs


def test_no_italic_is_shipped():
    """Neither Inter nor SF has Macedonian italic forms, so the language has no italic
    (DL1); emphasis is weight, as on iOS."""
    assert not list(FONTS.glob("*italic*"))
    css = TOKENS.read_text(encoding="utf-8") + (WEB / "static" / "css" / "site.css").read_text(
        encoding="utf-8"
    )
    assert "font-style: italic" not in css
    assert "font-synthesis: none" in css


def test_stil_shows_every_token(client):
    body = client.get("/stil/").get_data(as_text=True)
    missing = [t.name for t in style.tokens() if f"--{t.name}" not in body]
    assert missing == []
    assert 'lang="mk"' in body


def test_stil_has_a_sample_class_for_every_sampled_token():
    """A token on /stil with no sample class would render as an empty box."""
    css = (WEB / "static" / "css" / "stil.css").read_text(encoding="utf-8")
    for t in style.tokens():
        if t.value.startswith("#"):
            assert f".sw--{t.name} " in css, t.name
        elif t.name.startswith("radius-"):
            assert f".box--{t.name} " in css, t.name
        elif t.name.startswith("text-"):
            assert f".size--{t.name} " in css, t.name
        elif t.name.startswith("s-"):
            assert f".bar--{t.name} " in css, t.name
        elif t.name == "measure" or t.name.startswith(("width-", "col-")):
            assert f".span--{t.name} " in css, t.name


def test_stil_holds_a_theme_when_asked(client):
    assert 'data-theme="dark"' in client.get("/stil/?tema=temna").get_data(as_text=True)
    assert 'data-theme="light"' in client.get("/stil/?tema=svetla").get_data(as_text=True)
    assert "data-theme" not in client.get("/stil/").get_data(as_text=True).split(">", 2)[1]


def test_inter_draws_every_macedonian_letter_in_every_weight():
    for path in FONTS.glob("inter-cyrillic-*.woff2"):
        cmap = TTFont(path).getBestCmap()
        assert [ch for ch in MK_LETTERS if ord(ch) not in cmap] == [], path.name
    assert len(list(FONTS.glob("inter-*.woff2"))) == 6


def test_stil_is_not_registered_in_production():
    app = create_app(load_settings(env="production", version="test", secret_key="x" * 40))
    assert "stil" not in app.blueprints
