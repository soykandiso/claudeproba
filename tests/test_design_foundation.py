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
            scan = re.sub(r"@media\s*\([^)]*\)", "", line)
            scan = re.sub(r"url\([^)]*\)|unicode-range:[^;]*;", "", scan)
            for m in re.finditer(r"(?<![\w-])-?\d*\.?\d+(px|rem|pt|em)\b", scan):
                # em is allowed: it is relative to the line's own type, not a value.
                if m.group(1) != "em":
                    found.append(f"{name}:{n}: {m.group(0)}")
    assert not found, "raw size:\n" + "\n".join(found)


def test_text_sizes_are_the_scale():
    """The skill's scale is 12/14/16/20/28/40/64 and nothing else."""
    sizes = {t.name: t.value for t in style.tokens() if t.name.startswith("text-")}
    assert sizes == {f"text-{px}": f"{px / 16:g}rem" for px in (12, 14, 16, 20, 28, 40, 64)}


def test_space_is_the_scale():
    space = [t.name for t in style.tokens() if t.name.startswith("s-")]
    assert space == [f"s-{n}" for n in (4, 8, 12, 16, 24, 32, 48, 64, 96)]


def test_every_colour_has_one_job_and_passes_contrast():
    by_name = {t.name: t.value for t in style.tokens()}
    colours = {n for n, v in by_name.items() if v.startswith("#")}
    assert colours == set(style.COLOUR_JOBS)
    for fg in style.TEXT_COLOURS:
        for ground in style.GROUNDS:
            assert style.contrast(by_name[fg], by_name[ground]) >= 4.5, (fg, ground)
    assert style.contrast(by_name["rule-strong"], by_name["paper"]) >= 3.0


@pytest.mark.parametrize("path", sorted(FONTS.glob("*.woff2")), ids=lambda p: p.name)
def test_font_within_budget(path):
    assert path.stat().st_size <= 40 * 1024


@pytest.mark.parametrize("path", sorted(FONTS.glob("*cyrillic*.woff2")), ids=lambda p: p.name)
def test_cyrillic_subset_has_every_macedonian_letter(path):
    cmap = TTFont(path).getBestCmap()
    assert [ch for ch in MK_LETTERS if ord(ch) not in cmap] == []


def _mkd_locl(font: TTFont) -> dict[str, str]:
    """Glyph substitutions the font makes for Macedonian (cyrl/MKD, feature locl)."""
    gsub = font["GSUB"].table
    out: dict[str, str] = {}
    for sr in gsub.ScriptList.ScriptRecord:
        if sr.ScriptTag != "cyrl":
            continue
        for lang in sr.Script.LangSysRecord:
            if lang.LangSysTag != "MKD ":
                continue
            for fi in lang.LangSys.FeatureIndex:
                record = gsub.FeatureList.FeatureRecord[fi]
                if record.FeatureTag != "locl":
                    continue
                for li in record.Feature.LookupListIndex:
                    for st in gsub.LookupList.Lookup[li].SubTable:
                        st = getattr(st, "ExtSubTable", st)
                        out.update(getattr(st, "mapping", {}) or {})
    return out


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


def test_the_italic_substitutes_the_five_macedonian_forms():
    """б г д п т are the letters whose italic differs from Russian. The substitution
    has to be in the file, or lang="mk" can do nothing (ops/dev/cut_fonts.py)."""
    font = TTFont(FONTS / "source-serif-4-cyrillic-400-italic.woff2")
    cmap = font.getBestCmap()
    locl = _mkd_locl(font)
    assert [ch for ch in "бгдпт" if cmap[ord(ch)] not in locl] == []


def test_no_sans_italic_is_shipped():
    """Fira has no Macedonian forms; its italic would always be the Russian ones."""
    assert not list(FONTS.glob("fira-sans-*italic*"))
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
        elif t.name.startswith("text-"):
            assert f".size--{t.name} " in css, t.name
        elif t.name.startswith("s-"):
            assert f".bar--{t.name} " in css, t.name
        elif t.name == "measure" or t.name.startswith(("width-", "col-")):
            assert f".span--{t.name} " in css, t.name


def test_stil_is_not_registered_in_production():
    app = create_app(load_settings(env="production", version="test", secret_key="x" * 40))
    assert "stil" not in app.blueprints
