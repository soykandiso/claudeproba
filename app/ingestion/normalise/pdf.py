"""PDF → text: the text layer where there is one, Tesseract where there is not.

Decided per page (decisions.md D9): IPARD's advance notices have a text layer
while its calls do not, and one document can mix both. A page with fewer than
MIN_LETTERS letters in its text layer is treated as an image.
"""

import io
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.ingestion.normalise import Normalised, NormaliseError, letters
from app.ingestion.normalise.text import join_pages
from app.models.enums import TextSource

# The image-only PDFs from reconnaissance extracted 0-35 characters per page, most
# of them bullets and digits; a real page of text has hundreds of letters.
MIN_LETTERS = 50

# D9 rule 2: an OCR'd page goes to review when its mean word confidence is below
# MIN_OCR_CONFIDENCE, or more than MAX_LOW_CONFIDENCE_SHARE of its words scored
# under LOW_WORD_CONFIDENCE. Calibrated 13.09.2026 on a Skopje scan:
#   300 dpi (as published)  mean 94, 2.5% low words -- usable
#    75 dpi (degraded)      mean 78,  18% low words -- visibly wrong words
#    50 dpi                 mean 15,  98% low words -- nonsense
# A page mean never catches isolated misread words (the 300 dpi page still had
# some). That is what D9 rule 1 is for: every OCR citation is reviewed.
MIN_OCR_CONFIDENCE = 85.0
LOW_WORD_CONFIDENCE = 60.0
MAX_LOW_CONFIDENCE_SHARE = 0.10


class OcrUnavailable(NormaliseError):
    pass


@dataclass(frozen=True)
class OcrPage:
    text: str
    mean_confidence: float | None  # None when the page had no words at all
    low_confidence_share: float = 0.0


class TesseractOcr:
    """`pdftoppm` renders one page at a time; `tesseract` reads it as Macedonian.

    Macedonian only, not mkd+eng: with English added, Tesseract read Cyrillic "б"
    as "6" and put a Latin "A" into Cyrillic text on an IPARD call. A Latin letter
    that looks identical to a Cyrillic one silently breaks quote matching and
    search; a mangled Latin URL in a letterhead is visible and harmless.
    """

    def __init__(self, languages: str = "mkd", dpi: int = 300, timeout_s: int = 300):
        self.languages = languages
        self.dpi = dpi
        self.timeout_s = timeout_s

    @property
    def engine(self) -> str:
        """The version string recorded on every snapshot this engine reads.

        Different Tesseract versions read the same page differently (5.3.0 in the
        image and 5.3.4 elsewhere gave different confidences on one Skopje scan).
        Stored text is never recomputed, so this is for audit, not correctness.
        """
        if not hasattr(self, "_engine"):
            out = subprocess.run(["tesseract", "--version"], capture_output=True, timeout=30)
            first = (out.stdout or out.stderr).decode(errors="replace").splitlines()[0]
            self._engine = first.strip().replace(" ", "-") + f"-{self.languages}-{self.dpi}dpi"
        return self._engine

    @staticmethod
    def available() -> bool:
        return shutil.which("tesseract") is not None and shutil.which("pdftoppm") is not None

    def read_pages(self, pdf: bytes, page_numbers: list[int]) -> dict[int, OcrPage]:
        if not self.available():
            raise OcrUnavailable("tesseract and pdftoppm must be installed to read image-only PDFs")
        results = {}
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "document.pdf"
            source.write_bytes(pdf)
            for number in page_numbers:
                image = Path(tmp) / f"page-{number}"
                self._run(
                    [
                        "pdftoppm",
                        "-r",
                        str(self.dpi),
                        "-gray",
                        "-f",
                        str(number),
                        "-l",
                        str(number),
                        "-singlefile",
                        "-png",
                        str(source),
                        str(image),
                    ]
                )
                tsv = self._run(
                    ["tesseract", f"{image}.png", "stdout", "-l", self.languages, "tsv"]
                )
                results[number] = _from_tsv(tsv)
        return results

    def _run(self, command: list[str]) -> str:
        try:
            done = subprocess.run(command, capture_output=True, timeout=self.timeout_s, check=True)
        except subprocess.CalledProcessError as exc:
            raise NormaliseError(
                f"{command[0]} failed: {exc.stderr.decode(errors='replace')[:300]}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise NormaliseError(f"{command[0]} timed out after {self.timeout_s}s") from exc
        return done.stdout.decode("utf-8", errors="replace")


def normalise_pdf(content: bytes, ocr: TesseractOcr | None = None) -> Normalised:
    try:
        reader = PdfReader(io.BytesIO(content))
        if reader.is_encrypted and not reader.decrypt(""):
            raise NormaliseError("PDF is password-protected")
        layer = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as exc:
        raise NormaliseError(f"unreadable PDF: {exc}") from exc
    if not layer:
        raise NormaliseError("PDF has no pages")

    image_pages = [
        number for number, text in enumerate(layer, start=1) if letters(text) < MIN_LETTERS
    ]
    pages = list(layer)
    reasons: list[str] = []
    confidences: list[float] = []
    engine = None
    if image_pages:
        ocr = ocr or TesseractOcr()
        read = ocr.read_pages(content, image_pages)
        engine = getattr(ocr, "engine", None)
        for number in image_pages:
            page = read[number]
            pages[number - 1] = page.text
            if page.mean_confidence is None:
                continue  # a blank page: nothing to be wrong about
            confidences.append(page.mean_confidence)
            if page.mean_confidence < MIN_OCR_CONFIDENCE:
                reasons.append(
                    f"page {number}: OCR confidence {page.mean_confidence:.0f} "
                    f"is below {MIN_OCR_CONFIDENCE:.0f}"
                )
            elif page.low_confidence_share > MAX_LOW_CONFIDENCE_SHARE:
                reasons.append(
                    f"page {number}: {page.low_confidence_share:.0%} of OCR words scored "
                    f"below {LOW_WORD_CONFIDENCE:.0f}"
                )

    text = join_pages(pages)
    if not letters(text):
        reasons.append("no text found in the PDF, even with OCR")
    if not image_pages:
        source = TextSource.NATIVE
    elif len(image_pages) == len(pages):
        source = TextSource.OCR
    else:
        source = TextSource.MIXED
    return Normalised(
        text=text,
        text_source=source,
        ocr_pages=tuple(image_pages),
        ocr_mean_confidence=round(sum(confidences) / len(confidences), 2) if confidences else None,
        review_reasons=tuple(reasons),
        ocr_engine=engine,
    )


def _from_tsv(tsv: str) -> OcrPage:
    """Rebuild lines and paragraphs from Tesseract's word table, and average its confidence."""
    lines: dict[tuple[int, int, int], list[str]] = {}
    confidences: list[float] = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":  # level 5 = word
            continue
        word, conf = cols[11].strip(), float(cols[10])
        if not word or conf < 0:
            continue
        lines.setdefault((int(cols[2]), int(cols[3]), int(cols[4])), []).append(word)
        confidences.append(conf)

    out: list[str] = []
    previous: tuple[int, int] | None = None
    for block, paragraph, _line in sorted(lines):
        if previous is not None and previous != (block, paragraph):
            out.append("")  # a blank line between paragraphs
        out.append(" ".join(lines[(block, paragraph, _line)]))
        previous = (block, paragraph)
    if not confidences:
        return OcrPage("\n".join(out), None)
    low = sum(1 for c in confidences if c < LOW_WORD_CONFIDENCE) / len(confidences)
    return OcrPage("\n".join(out), sum(confidences) / len(confidences), low)
