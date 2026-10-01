"""The chunker: spans that index back into normalised_text exactly."""

import re

import pytest

from app.retrieval.chunker import MAX_CHARS, OVERLAP_CHARS, chunk_spans
from tests.test_extract_schema import CASES, fixture_text


@pytest.mark.parametrize("name", CASES)
def test_chunks_of_real_documents_cover_every_word_within_the_size_limit(name):
    text = fixture_text(name)
    spans = chunk_spans(text)

    assert [s.ordinal for s in spans] == list(range(len(spans)))
    assert all(0 <= s.start < s.end <= len(text) for s in spans)
    assert all(s.end - s.start <= MAX_CHARS for s in spans)
    assert [s.start for s in spans] == sorted({s.start for s in spans}), "starts move forward"
    # No chunk begins or ends in whitespace: offsets point at words.
    assert not any(text[s.start].isspace() or text[s.end - 1].isspace() for s in spans)

    covered = set()
    for s in spans:
        covered.update(range(s.start, s.end))
    words = [m for m in re.finditer(r"\S+", text)]
    assert all(set(range(m.start(), m.end())) <= covered for m in words)


@pytest.mark.parametrize("name", CASES)
def test_chunking_is_deterministic(name):
    text = fixture_text(name)

    assert chunk_spans(text) == chunk_spans(text)


def test_a_clause_across_a_chunk_boundary_is_whole_in_one_chunk():
    # Short wrapped lines, like the IPARD notice: a sentence crosses lines.
    lines = [f"ред {i:03d} од документот со доволно текст за да се пополни" for i in range(60)]
    text = "\n".join(lines)
    spans = chunk_spans(text)
    assert len(spans) > 2

    for boundary in spans[1:]:
        previous = next(s for s in spans if s.ordinal == boundary.ordinal - 1)
        assert boundary.start < previous.end, "consecutive chunks overlap"
        assert previous.end - boundary.start <= OVERLAP_CHARS

    # Every pair of adjacent lines appears together in some chunk.
    for i in range(len(lines) - 1):
        pair = f"{lines[i]}\n{lines[i + 1]}"
        assert any(pair in text[s.start : s.end] for s in spans), i


def test_a_line_longer_than_a_chunk_is_cut_after_a_sentence():
    sentence = "Барателот ја доставува документацијата во оригинал или копија. "
    text = sentence * 40  # one line, ~2.600 characters
    spans = chunk_spans(text)

    assert len(spans) >= 3
    assert all(text[s.start : s.end].endswith(".") for s in spans)
    assert "".join(text[s.start : s.end] + " " for s in spans).strip() == text.strip()


def test_text_without_spaces_is_still_cut():
    text = "а" * (MAX_CHARS * 2 + 10)

    spans = chunk_spans(text)

    assert [(s.start, s.end) for s in spans] == [
        (0, MAX_CHARS),
        (MAX_CHARS, 2 * MAX_CHARS),
        (2 * MAX_CHARS, len(text)),
    ]


def test_page_breaks_separate_lines_and_empty_text_has_no_chunks():
    assert chunk_spans("") == []
    assert chunk_spans(" \n\f\n  ") == []

    text = "прва страна\fвтора страна"
    (span,) = chunk_spans(text)
    assert text[span.start : span.end] == text
