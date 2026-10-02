"""Cut the web fonts this site serves from their upstream files (DS2, DL1).

    uv run python ops/dev/cut_fonts.py --src DIR

DIR holds `Inter[opsz,wght].ttf` from google/fonts (the URL is in FACES). It is not
downloaded here: the run is once a year at most, and a dev host behind a TLS-inspecting
proxy fetches it more easily with a browser or curl than Python does. Each source is
hash-pinned; a different upstream build must be looked at, not silently subset
(`--accept-new-hash`).

Inter is the design language's one family (DL1, docs/design-language.md). Variable
subsets with both axes are over the 40 KB budget, so each weight is a static instance
at the optical size it is used at. The ranges are the ones tokens.css declares, so every
weight splits into one Cyrillic and one Latin file.

History: DS2 cut a Source Serif 4 italic for a Macedonian reader to sign off. The
design language has no italic (Inter and SF have no Macedonian italic forms), so DL1
removed it. The Fira Sans and Source Serif 4 uprights stay for the PDF until DL5; they
were never cut here (decisions.md, DS2).
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

# (file in --src, where it comes from, its pinned sha256, output name, cuts). A cut is
# (weight, optical size): a static instance, because a variable subset of Inter with both
# axes is over the 40 KB budget per file.
FACES = (
    # The design language's one family (DL1, docs/design-language.md): Inter, the free face
    # nearest to SF Pro, which may not be served on the web. Each weight is cut at the
    # optical size it is used at, as SF Text and SF Display are: 400 for reading (14), 600
    # for headlines and controls (20), 700 for the large titles (28).
    (
        "Inter[opsz,wght].ttf",
        "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf",
        "29160a80ff49ddcab2c97711247e08b1fab27a484a329ce8b813d820dc559031",
        "inter-{part}-{weight}-normal.woff2",
        ((400, 14), (600, 20), (700, 28)),
    ),
)

# The same unicode-range strings as tokens.css, so a face never covers a character
# its @font-face does not claim.
RANGES = {
    "cyrillic": "U+0301,U+0400-045F,U+0490-0491,U+04B0-04B1,U+2116",
    "latin": (
        "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,"
        "U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"
    ),
}


def unicodes(spec: str) -> list[int]:
    out: list[int] = []
    for part in spec.split(","):
        lo, _, hi = part.removeprefix("U+").partition("-")
        out.extend(range(int(lo, 16), int(hi or lo, 16) + 1))
    return out


def cut(src: Path, weight: int, opsz: int, part: str, name: str) -> Path:
    font = instancer.instantiateVariableFont(TTFont(src), {"wght": weight, "opsz": opsz})
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
    out = FONTS / name.format(part=part, weight=weight)
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

    for source, url, pinned, name, cuts in FACES:
        src = args.src / source
        if not src.exists():
            print(f"missing {src}; download it from {url}", file=sys.stderr)
            return 1
        digest = hashlib.sha256(src.read_bytes()).hexdigest()
        if digest != pinned and not args.accept_new_hash:
            print(
                f"{source} is {digest}, pinned {pinned}; look, then --accept-new-hash",
                file=sys.stderr,
            )
            return 1
        for weight, opsz in cuts:
            for part in RANGES:
                out = cut(src, weight, opsz, part, name)
                print(f"{out.relative_to(ROOT)}  {out.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
