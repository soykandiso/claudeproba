"""Cut the Source Serif 4 italic subsets from the upstream font (design phase DS2).

    uv run python ops/dev/cut_fonts.py --src DIR

DIR holds `SourceSerif4-Italic[opsz,wght].ttf` from google/fonts (URL below). It is
not downloaded here: the run is once a year at most, and a dev host behind a
TLS-inspecting proxy fetches it more easily with a browser or curl than Python
does. The file is hash-pinned; a different upstream build must be looked at, not
silently subset (`--accept-new-hash`).

Why only the italic. The DS1 audit (docs/design.md F05) asked for the subsets to be
re-cut keeping the Macedonian `locl` lookups. Opening the upstream files settled it:

- **Fira Sans has no Cyrillic language systems at all** upstream, so there is no
  `locl` to keep. Its upright forms are correct for Macedonian; a Fira italic never
  would be, so none is shipped and `font-synthesis: none` stops a browser faking one.
- **The Source Serif 4 subsets already keep `cyrl/MKD`.** Re-cutting them would change
  shipped bytes (and the PDF's merged faces, app/reports/render.py) for nothing.

So the one new cut is the italic, the only face in which Macedonian б г д п т differ
from Russian. It is used on `/stil` alone until a native reader signs the forms off
(roadmap DS2); tests/test_design_foundation.py proves the substitution is in the file.

The ranges are the ones tokens.css declares for every other face, so the italic
splits the same way: one Cyrillic and one Latin file per weight.
"""

import argparse
import hashlib
import sys
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parents[2]
FONTS = ROOT / "app" / "web" / "static" / "fonts"

SOURCE = "SourceSerif4-Italic[opsz,wght].ttf"
SOURCE_URL = (
    "https://raw.githubusercontent.com/google/fonts/main/ofl/sourceserif4/"
    "SourceSerif4-Italic%5Bopsz%2Cwght%5D.ttf"
)
SOURCE_SHA256 = "15fbc7e4679489a501998c3669272637a6646388ef7e4bd77eebb5bf967a1f42"

# The same unicode-range strings as tokens.css, so a face never covers a character
# its @font-face does not claim.
RANGES = {
    "cyrillic": "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116",
    "latin": (
        "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
        "U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"
    ),
}

# Text sizes; the optical size the upstream file defaults to as well.
OPSZ = 20
WEIGHTS = (400,)


def unicodes(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        lo, _, hi = part.removeprefix("U+").partition("-")
        out.extend(range(int(lo, 16), int(hi or lo, 16) + 1))
    return out


def cut(src: Path, weight: int, part: str) -> Path:
    font = instancer.instantiateVariableFont(TTFont(src), {"wght": weight, "opsz": OPSZ})
    options = subset.Options()
    # Default features already include locl; say it, so a future default cannot drop it.
    options.layout_features = [*options.layout_features, "locl"]
    options.layout_scripts = ["*"]
    options.name_IDs = ["*"]
    # TrueType instructions are most of the file and do nothing on the screens that
    # matter here (phones, high-DPI). The shipped upright subsets carry none either.
    options.hinting = False
    options.desubroutinize = True
    sub = subset.Subsetter(options)
    sub.populate(unicodes=unicodes(RANGES[part]))
    sub.subset(font)
    out = FONTS / f"source-serif-4-{part}-{weight}-italic.woff2"
    # On the font, not on subset.Options: Options.flavor is read only by subset.main's
    # own save, and without this the file is a plain TTF with a .woff2 name.
    font.flavor = "woff2"
    font.save(out)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--src", type=Path, required=True)
    parser.add_argument("--accept-new-hash", action="store_true")
    args = parser.parse_args()

    src = args.src / SOURCE
    if not src.exists():
        print(f"missing {src}\ndownload it from {SOURCE_URL}", file=sys.stderr)
        return 1
    digest = hashlib.sha256(src.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256 and not args.accept_new_hash:
        print(
            f"{SOURCE} is {digest}, pinned {SOURCE_SHA256}; look, then --accept-new-hash",
            file=sys.stderr,
        )
        return 1

    for weight in WEIGHTS:
        for part in RANGES:
            out = cut(src, weight, part)
            print(f"{out.relative_to(ROOT)}  {out.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
