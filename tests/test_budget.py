"""The performance budget (design phase DS9), as numbers a change cannot quietly break.

Target: a mid-range Android on mobile data (the skill's "Performance budget"). Measured
on 02.10.2026 over the real pages: 132-167 KB gzipped for a first visit, 11-13 requests,
most of it fonts that load with `font-display: swap`, so text shows before they arrive.
These limits sit a little above that, so growth is a decision, not an accident.
"""

import gzip
from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "app" / "web" / "static"


def _gz(path: Path) -> int:
    return len(gzip.compress(path.read_bytes(), compresslevel=6))


def test_the_stylesheets_stay_small():
    css = _gz(STATIC / "css" / "tokens.css") + _gz(STATIC / "css" / "site.css")
    assert css <= 14 * 1024, f"tokens.css + site.css gzipped: {css} bytes"


def test_the_javascript_is_htmx_and_one_small_file():
    js = sorted(p.name for p in (STATIC / "js").glob("*.js"))
    assert js == ["htmx.min.js", "submit.js"]
    assert _gz(STATIC / "js" / "htmx.min.js") <= 17 * 1024
    assert (STATIC / "js" / "submit.js").stat().st_size <= 2 * 1024


def test_a_first_visit_stays_under_the_budget():
    """Everything a customer page can load, gzipped as Caddy serves it (woff2 is already
    compressed). The italic is /stil's alone and not counted."""
    fonts = [p for p in (STATIC / "fonts").glob("*.woff2") if "italic" not in p.name]
    total = (
        _gz(STATIC / "css" / "tokens.css")
        + _gz(STATIC / "css" / "site.css")
        + _gz(STATIC / "js" / "htmx.min.js")
        + _gz(STATIC / "js" / "submit.js")
        + sum(p.stat().st_size for p in fonts)
    )
    assert total <= 190 * 1024, f"first visit at most {total // 1024} KB before the HTML"
