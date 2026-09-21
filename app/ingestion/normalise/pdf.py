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

# D9, reopened 16.09.2026: every Economy call is a bilingual Macedonian-Albanian
# PDF. `mkd` reads the Macedonian cleanly and turns the Albanian into Cyrillic
# nonsense at confidence 0 ("ЕКопотте" for "Ekonomisë"), so every page's mean landed
# at 67-75 and rule 2 flagged all of them -- while the Macedonian was never in doubt.
#
# The answer is to read the page properly rather than to move the yardstick, and
# Tesseract makes that easy: it already segments the two languages into *separate
# blocks*. Measured over all 20 pages of both calls, the block sets of the `mkd` and
# `sqi` passes were identical on every page, and the two languages never disagreed
# by less than the margin below -- an Albanian block gained 30-90 points under `sqi`,
# a Macedonian block lost 20-60. So a whole block is swapped to the second pass,
# never a word, and only where the gap is unambiguous. Page means went 67-75 -> 83-95.
#
# Unlike the `%` pass, this one contributes *text*, so it is confined to blocks the
# primary pass demonstrably failed on. A Latin-script model cannot corrupt Cyrillic
# it is never applied to.
MIN_FOREIGN_CONFIDENCE = 80.0
MIN_FOREIGN_GAIN = 25.0
# Blocks are whole regions of a page, so they must land on each other squarely; a
# word only has to be covered (MIN_PERCENT_OVERLAP).
MIN_FOREIGN_OVERLAP = 0.7


class OcrUnavailable(NormaliseError):
    pass


@dataclass(frozen=True)
class OcrPage:
    text: str
    mean_confidence: float | None  # None when the page had no words at all
    low_confidence_share: float = 0.0
    percents_restored: int = 0
    percents_unresolved: int = 0  # seen by the second pass, not placeable: review
    foreign_blocks: int = 0  # blocks another language's model read instead


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

    Two narrow second passes fix what one Macedonian model cannot do alone, each
    confined to where the primary pass demonstrably failed:

    - `foreign_pass` re-reads *whole blocks* `mkd` could not read at all, which on
      a bilingual Macedonian-Albanian call is the Albanian half
      (`restore_foreign_blocks`);
    - `percent_pass` puts back the `%` that `mkd` has no character for, one
      character at a time (`restore_percents`).

    A page pays for a pass only when it shows the symptom -- a block below
    LOW_WORD_CONFIDENCE, or a digit in the text -- so a clean Macedonian page is
    still read once. Either can be switched off with `None`; both off is the
    single-pass behaviour of P1 s9. A language whose model is not installed is
    skipped, so a thin image degrades instead of failing (`installed`).
    """

    def __init__(
        self,
        languages: str = "mkd",
        dpi: int = 300,
        timeout_s: int = 300,
        percent_pass: str | None = "mkd+eng",
        foreign_pass: str | None = "sqi",
    ):
        self.languages = languages
        self.dpi = dpi
        self.timeout_s = timeout_s
        self.percent_pass = percent_pass
        self.foreign_pass = foreign_pass

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
            if self._foreign:
                self._engine += f"-fgn-{self._foreign}"
        return self._engine

    @property
    def _foreign(self) -> str | None:
        """`foreign_pass`, unless its model is not installed in this image."""
        if not self.foreign_pass:
            return None
        return self.foreign_pass if self.foreign_pass in self.installed() else None

    @staticmethod
    def installed() -> frozenset[str]:
        """The language models this Tesseract has, so a missing one is skipped."""
        out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, timeout=30)
        lines = (out.stdout or out.stderr).decode(errors="replace").splitlines()
        return frozenset(line.strip() for line in lines[1:] if line.strip())

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
                foreign = 0
                if self._foreign and _has_unreadable_block(words):
                    words, foreign = restore_foreign_blocks(
                        words, _words_from_tsv(self._read(image, self._foreign))
                    )
                restored = unresolved = 0
                if self.percent_pass and any(_DIGIT.search(w.text) for w in words):
                    words, restored, unresolved = restore_percents(
                        words, _words_from_tsv(self._read(image, self.percent_pass))
                    )
                results[number] = _page_from_words(words, restored, unresolved, foreign)
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


def _page_from_words(
    words: list[_Word], restored: int = 0, unresolved: int = 0, foreign: int = 0
) -> OcrPage:
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
    counts = {
        "percents_restored": restored,
        "percents_unresolved": unresolved,
        "foreign_blocks": foreign,
    }
    if not words:
        return OcrPage(text, None, **counts)
    confidences = [w.confidence for w in words]
    low = sum(1 for c in confidences if c < LOW_WORD_CONFIDENCE) / len(confidences)
    return OcrPage(text, sum(confidences) / len(confidences), low, **counts)


_DIGIT = re.compile(r"\d")


def _blocks(words: list[_Word]) -> dict[int, list[_Word]]:
    blocks: dict[int, list[_Word]] = {}
    for word in words:
        blocks.setdefault(word.block, []).append(word)
    return blocks


def _mean(words: list[_Word]) -> float:
    return sum(w.confidence for w in words) / len(words)


def _bounds(words: list[_Word]) -> _Word:
    """The block's bounding box, as a _Word, so blocks match the way words do."""
    left, top = min(w.left for w in words), min(w.top for w in words)
    right = max(w.left + w.width for w in words)
    bottom = max(w.top + w.height for w in words)
    return replace(words[0], text="", left=left, top=top, width=right - left, height=bottom - top)


def _has_unreadable_block(words: list[_Word]) -> bool:
    """Is any block bad enough to be worth a second pass in another language?

    The trigger, not the test: a page with nothing under LOW_WORD_CONFIDENCE has
    no region another model could rescue, and is read once.
    """
    return any(_mean(block) < LOW_WORD_CONFIDENCE for block in _blocks(words).values())


def restore_foreign_blocks(base: list[_Word], second: list[_Word]) -> tuple[list[_Word], int]:
    """Re-read the blocks the Macedonian model could not read, in another language.

    A bilingual call is not a degraded scan: `mkd` reads the Macedonian half at 90+
    and the Albanian half at nearly 0, and Tesseract has already put the two in
    separate blocks. So this swaps a **whole block** to `second` -- never a word,
    never part of a line -- and only where the second pass is unambiguously better:
    its block mean is at least MIN_FOREIGN_CONFIDENCE, and at least
    MIN_FOREIGN_GAIN above what `mkd` scored on the block it covers.

    Blocks are matched by bounding box, like words, rather than by Tesseract's block
    numbering. The numbering agreed on all 20 pages measured, but it is an internal
    counter of a separate run and nothing guarantees it.

    A swapped block keeps the *base* block's number, so the page still reads in the
    order `mkd` laid out. Returns the merged words and how many blocks were swapped.
    """
    blocks = _blocks(base)
    numbers = list(blocks)
    boxes = [_bounds(blocks[n]) for n in numbers]
    taken: set[int] = set()
    replacements: dict[int, list[_Word]] = {}

    for words in _blocks(second).values():
        if _mean(words) < MIN_FOREIGN_CONFIDENCE:
            continue
        match = _aligned(_bounds(words), boxes, taken, MIN_FOREIGN_OVERLAP)
        if match is None:
            continue
        target = numbers[match]
        if _mean(words) - _mean(blocks[target]) < MIN_FOREIGN_GAIN:
            continue
        taken.add(match)
        replacements[target] = [replace(w, block=target) for w in words]

    merged: list[_Word] = []
    for number in numbers:
        merged += replacements.get(number, blocks[number])
    return merged, len(replacements)


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

    A word that already contains a `%` needs no repair and is skipped -- the
    Albanian blocks `restore_foreign_blocks` supplies come from a Latin-script
    model, which writes `%` itself.

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
        if index is not None and "%" in words[index].text:
            continue  # already reads `%`: a block a Latin-script pass supplied
        if index is None or not _is_percent_repair(candidate, words[index]):
            unresolved += 1
            continue
        words[index] = replace(words[index], text=candidate.text)
        claimed.add(index)
        restored += 1
    return words, restored, unresolved


def _aligned(
    candidate: _Word, words: list[_Word], claimed: set[int], minimum: float = MIN_PERCENT_OVERLAP
) -> int | None:
    """The unclaimed word whose box the candidate covers most, if it covers enough."""
    best, score = None, minimum
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
