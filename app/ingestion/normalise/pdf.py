"""PDF → text: the text layer where there is one, Tesseract where there is not.

Decided per page (decisions.md D9): IPARD's advance notices have a text layer
while its calls do not, and one document can mix both. A page with fewer than
MIN_LETTERS letters in its text layer is treated as an image.
"""

import io
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, replace
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

# D9, reopened 18.09.2026: the `mkd` model's character set has no `%`, so it reads
# the glyph as digits -- "75%" as "755", "25%" as "254", "75%." as "7556." -- at
# confidences that raise no flag, and a quote carrying the wrong number still
# matches the OCR text verbatim. A second pass with English added does read `%`,
# but it also turns Cyrillic into look-alike Latin, which is why `mkd` alone reads
# the page (the docstring below). So the second pass is never allowed to contribute
# text: only the `%` character itself crosses over, into a token both passes agree
# is a number. Everything else in the second pass is thrown away.
#
# Measured on IPARD 01/2025 short version, pages 1-2 (300 dpi), the only fixture
# with rates: 6 of 6 percent signs restored, every box overlapping 1.00, second
# pass confidence 92-97 where `mkd` scored 45-75 on the same six tokens.
MIN_PERCENT_CONFIDENCE = 80.0
MIN_PERCENT_OVERLAP = 0.5
# `mkd` is only overruled where `mkd` was itself unsure. Forced to write a character
# it does not have, it scores badly: 45, 46, 47, 60, 65 and 75 on the six rates
# above, against a page mean of 87-97. A number it read confidently is left alone
# even if the second pass saw a `%` there -- "6%" over a confident "60" is as likely
# to be the second pass misreading a zero, and that goes to a reviewer instead.
MAX_MANGLED_CONFIDENCE = 80.0
# How many characters `mkd` may have put where the `%` is. Observed: 0 (dropped),
# 1 ("755", "60\u201c") and 2 ("7556."). More than that is not a misread `%`.
MAX_PERCENT_WIDTH = 2


class OcrUnavailable(NormaliseError):
    pass


@dataclass(frozen=True)
class OcrPage:
    text: str
    mean_confidence: float | None  # None when the page had no words at all
    low_confidence_share: float = 0.0
    percents_restored: int = 0
    percents_unresolved: int = 0  # seen by the second pass, not placeable: review


@dataclass(frozen=True)
class _Word:
    """One level-5 row of Tesseract's word table, with the box that located it."""

    text: str
    confidence: float
    left: int
    top: int
    width: int
    height: int
    block: int
    paragraph: int
    line: int

    @property
    def area(self) -> int:
        return self.width * self.height

    def overlap(self, other: "_Word") -> float:
        """Area shared with other, as a fraction of *this* word's box."""
        x = min(self.left + self.width, other.left + other.width) - max(self.left, other.left)
        y = min(self.top + self.height, other.top + other.height) - max(self.top, other.top)
        return max(0, x) * max(0, y) / self.area if self.area else 0.0


class TesseractOcr:
    """`pdftoppm` renders one page at a time; `tesseract` reads it as Macedonian.

    Macedonian only, not mkd+eng: with English added, Tesseract read Cyrillic "б"
    as "6" and put a Latin "A" into Cyrillic text on an IPARD call. A Latin letter
    that looks identical to a Cyrillic one silently breaks quote matching and
    search; a mangled Latin URL in a letterhead is visible and harmless.

    `mkd` cannot read `%` at all, though, so a page whose text contains a digit is
    read a second time with `percent_pass` and the two word tables are matched by
    box (`restore_percents`). That second read is the reason an OCR'd page now
    costs roughly twice the time; only pages with digits pay it. Pass
    `percent_pass=None` for the single-pass behaviour of P1 s9.
    """

    def __init__(
        self,
        languages: str = "mkd",
        dpi: int = 300,
        timeout_s: int = 300,
        percent_pass: str | None = "mkd+eng",
    ):
        self.languages = languages
        self.dpi = dpi
        self.timeout_s = timeout_s
        self.percent_pass = percent_pass

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
            if self.percent_pass:
                self._engine += f"-pct-{self.percent_pass}"
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
                words = _words_from_tsv(self._read(image, self.languages))
                restored = unresolved = 0
                if self.percent_pass and any(_DIGIT.search(w.text) for w in words):
                    words, restored, unresolved = restore_percents(
                        words, _words_from_tsv(self._read(image, self.percent_pass))
                    )
                results[number] = _page_from_words(words, restored, unresolved)
        return results

    def _read(self, image: Path, languages: str) -> str:
        return self._run(["tesseract", f"{image}.png", "stdout", "-l", languages, "tsv"])

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
            if page.percents_unresolved:
                # A rate that could not be read is a human's, not a guess: D9 and
                # invariant 3. The text keeps whatever `mkd` wrote, wrong number
                # and all, because a snapshot is faithful to what the engine read.
                reasons.append(
                    f"page {number}: {page.percents_unresolved} percent sign(s) could not be "
                    f"placed in the Macedonian OCR text; check every rate against the PDF"
                )
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


def _words_from_tsv(tsv: str) -> list[_Word]:
    """Tesseract's word table, level-5 rows only, in reading order."""
    words = []
    for row in tsv.splitlines()[1:]:
        cols = row.split("\t")
        if len(cols) < 12 or cols[0] != "5":  # level 5 = word
            continue
        text, conf = cols[11].strip(), float(cols[10])
        if not text or conf < 0:
            continue
        words.append(
            _Word(
                text=text,
                confidence=conf,
                left=int(cols[6]),
                top=int(cols[7]),
                width=int(cols[8]),
                height=int(cols[9]),
                block=int(cols[2]),
                paragraph=int(cols[3]),
                line=int(cols[4]),
            )
        )
    return words


def _page_from_words(words: list[_Word], restored: int = 0, unresolved: int = 0) -> OcrPage:
    """Rebuild lines and paragraphs from the word table, and average its confidence."""
    lines: dict[tuple[int, int, int], list[str]] = {}
    for word in words:
        lines.setdefault((word.block, word.paragraph, word.line), []).append(word.text)

    out: list[str] = []
    previous: tuple[int, int] | None = None
    for block, paragraph, line in sorted(lines):
        if previous is not None and previous != (block, paragraph):
            out.append("")  # a blank line between paragraphs
        out.append(" ".join(lines[(block, paragraph, line)]))
        previous = (block, paragraph)

    text = "\n".join(out)
    if not words:
        return OcrPage(text, None, percents_restored=restored, percents_unresolved=unresolved)
    confidences = [w.confidence for w in words]
    low = sum(1 for c in confidences if c < LOW_WORD_CONFIDENCE) / len(confidences)
    return OcrPage(
        text,
        sum(confidences) / len(confidences),
        low,
        percents_restored=restored,
        percents_unresolved=unresolved,
    )


_DIGIT = re.compile(r"\d")


def restore_percents(base: list[_Word], second: list[_Word]) -> tuple[list[_Word], int, int]:
    """Put back the `%` that the Macedonian model has no character for.

    `base` is the `mkd` word table and is the text that will be kept; `second` is
    a second read of the *same image* by a model that can represent `%`. For each
    second-pass word containing one `%`, the `mkd` word occupying the same box is
    rewritten to the second-pass word -- but only when the substitution is a
    `%` and nothing else:

    - the second-pass word holds exactly one `%` and no letter at all, so no Latin
      look-alike can enter the Cyrillic text (the reason `mkd` reads the page);
    - it was read with confidence (MIN_PERCENT_CONFIDENCE) while `mkd` was not
      (MAX_MANGLED_CONFIDENCE), so a number `mkd` is sure of is never overruled;
    - its box covers the `mkd` word's (MIN_PERCENT_OVERLAP);
    - and the `mkd` word is that word with the `%` replaced by at most
      MAX_PERCENT_WIDTH characters, none of them letters -- i.e. the two passes
      agree on everything except the glyph one of them cannot write.

    Anything a `%` was seen in and none of this held for is counted as unresolved
    and becomes a review reason: an unreadable rate is a human's, never a guess
    (invariant 3). Returns the rewritten words, how many were restored, and how
    many were not.
    """
    words = list(base)
    claimed: set[int] = set()
    restored = unresolved = 0
    for candidate in second:
        if "%" not in candidate.text:
            continue
        index = _aligned(candidate, words, claimed)
        if index is None or not _is_percent_repair(candidate, words[index]):
            unresolved += 1
            continue
        words[index] = replace(words[index], text=candidate.text)
        claimed.add(index)
        restored += 1
    return words, restored, unresolved


def _aligned(candidate: _Word, words: list[_Word], claimed: set[int]) -> int | None:
    """The unclaimed word whose box the candidate covers most, if it covers enough."""
    best, score = None, MIN_PERCENT_OVERLAP
    for index, word in enumerate(words):
        if index in claimed:
            continue
        if (overlap := candidate.overlap(word)) > score:
            best, score = index, overlap
    return best


def _is_percent_repair(candidate: _Word, current: _Word) -> bool:
    """Is `current` what `mkd` writes when the page says `candidate`?"""
    if candidate.confidence < MIN_PERCENT_CONFIDENCE:
        return False
    if current.confidence >= MAX_MANGLED_CONFIDENCE:
        return False
    if candidate.text.count("%") != 1 or any(ch.isalpha() for ch in candidate.text):
        return False
    head, tail = candidate.text.split("%")
    if len(current.text) < len(head) + len(tail):
        return False  # head and tail would overlap; they are not the same token
    if not current.text.startswith(head) or not current.text.endswith(tail):
        return False
    middle = current.text[len(head) : len(current.text) - len(tail)]
    return len(middle) <= MAX_PERCENT_WIDTH and not any(ch.isalpha() for ch in middle)
