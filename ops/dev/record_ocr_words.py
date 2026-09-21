"""Record Tesseract's word tables for a PDF page, as a test fixture.

`restore_percents` matches two word tables by box, and both tables differ between
Tesseract versions, so the tests replay a recording instead of running the engine
(the same reason `skopje/call-12149.ocr.json` exists). Re-record with:

    PYTHONPATH=. uv run python ops/dev/record_ocr_words.py \
        tests/fixtures/ipardpa/call-32-javen-povik-01-2025-kratka.pdf 1 2 \
        > tests/fixtures/ipardpa/call-32.words.json

It records every pass `TesseractOcr` can run, so one recording serves both
`restore_percents` and `restore_foreign_blocks`. The source PDF need not be
committed: `economy/call-1.words.json` is the only record of a document too large
for the repo (tests/fixtures/README.md).

and update the manifest in tests/fixtures/README.md.
"""

import json
import subprocess
import sys
import tempfile
from dataclasses import astuple
from pathlib import Path

from app.ingestion.normalise.pdf import TesseractOcr, _words_from_tsv

DPI = 300


def main(pdf: str, pages: list[int]) -> None:
    ocr = TesseractOcr(dpi=DPI)
    out: dict = {"engine": ocr.engine, "dpi": DPI, "source": pdf, "pages": {}}
    with tempfile.TemporaryDirectory() as tmp:
        for number in pages:
            image = Path(tmp) / f"page-{number}"
            subprocess.run(
                ["pdftoppm", "-r", str(DPI), "-gray", "-f", str(number), "-l", str(number),
                 "-singlefile", "-png", pdf, str(image)],
                check=True, capture_output=True,
            )  # fmt: skip
            out["pages"][str(number)] = {
                languages: [list(astuple(w)) for w in _words_from_tsv(ocr._read(image, languages))]
                for languages in dict.fromkeys(
                    lang for lang in (ocr.languages, ocr.percent_pass, ocr.foreign_pass) if lang
                )
            }
    # One word per line: compact enough to commit, still readable in a diff.
    rows = json.dumps(out, ensure_ascii=False, separators=(",", ": "))
    print(rows.replace("],[", "],\n  ["))


if __name__ == "__main__":
    main(sys.argv[1], [int(n) for n in sys.argv[2:]])
