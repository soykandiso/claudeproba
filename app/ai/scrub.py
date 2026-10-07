"""Identity scrubbing at the model boundary (CLAUDE.md invariant 4, risks.md R5).

Two layers, because neither is enough alone:

1. **Patterns** catch identity data that has a shape: e-mail addresses, phone
   numbers, ЕДБ (13 digits), ЕМБС (7 digits, only when labelled -- bare 7-digit
   numbers are too often amounts), and street addresses.
2. **Known identifiers** catch what has no shape, above all names. The caller
   passes the values it knows are identifying (company name, contact person,
   the applicant's own ЕМБС) and every occurrence is replaced.

A person's name in free text that the caller did not pass is NOT detectable
here. That is why applicant data reaches a prompt only as bands and codes
(NACE, size band, region code), never as free text -- the scrubber is the
second line of defence, not the first.

Matches become stable pseudonyms within one call (`[EMAIL_1]`, `[PHONE_2]`), so
the model can still tell two different contacts apart. A quote the model copies
across a pseudonym will not be found verbatim in the source chunk and goes to
review, which is the correct outcome.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")

# +389 2 3085 347 · +389(0)2 3085 347 · 00389 70 123 456
_PHONE_INTL = re.compile(r"(?:\+|00)389[\s\-/()]*0?[\s\-/()]*\d(?:[\s\-/]*\d){6,8}")
# 070 123 456 · 02/3123-456 · (02) 3 123 456
# Area codes only (07x mobile, 02 Skopje, 03x/04x regions), so grouped amounts
# like "1 000 000 000" are not mistaken for numbers. A number may end a sentence:
# only a separator followed by another digit ("070 123 456.00") makes it an amount,
# not the full stop after it (P2 s34 found "…на 070 123 456." passing unscrubbed).
_PHONE_DOMESTIC = re.compile(
    r"(?<!\d)(?<!\d[.,])\(?0(?:7\d|2|3[1-4]|4[2-8])\)?[\s\-/]*\d(?:[\s\-]?\d){5,6}"
    r"(?!\d|[.,]\d)"
)

# ЕДБ is 13 digits, sometimes written with the MK prefix of the VAT number.
_EDB = re.compile(r"(?<!\d)(?:MK|МК)?\s?\d{13}(?!\d)")
# ЕМБС is 7 digits. Only redacted when labelled; a bare "5000000" is an amount.
_EMBS = re.compile(
    r"((?:ЕМБС|EMBS|матичен\s+број(?:\s+на\s+субјектот)?)\s*(?:бр\.?)?\s*[:.\-]?\s*)(\d{7})(?!\d)",
    re.IGNORECASE,
)

# ул. „Јуриј Гагарин“ бр. 15 · бул. Партизански одреди 3/2 · ulica Makedonija br. 12
_ADDRESS = re.compile(
    r"(?:\bул\.|\bулица|\bбул\.|\bбулевар|\bul\.|\bulica|\bbul\.)\s*"
    r"[„\"“]?[^\n,;„\"“]{2,50}?[“\"”]?\s*(?:бр\.?|br\.?)?\s*\d+[а-шa-z]?(?:/\d+)?",
    re.IGNORECASE,
)

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("EMAIL", _EMAIL),
    ("EDB", _EDB),
    ("PHONE", _PHONE_INTL),
    ("PHONE", _PHONE_DOMESTIC),
    ("ADDRESS", _ADDRESS),
)


class IdentityLeak(RuntimeError):
    """Raised when identity data is still present after scrubbing. Never caught to continue."""


@dataclass
class Scrubber:
    """Scrubs the texts of one model call, keeping pseudonyms stable across them."""

    known_identifiers: Iterable[str] = ()
    _tokens: dict[str, str] = field(default_factory=dict, init=False)
    _counts: dict[str, int] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        # Longest first, so "Бетон ДООЕЛ Скопје" is replaced before "Бетон".
        values = {v.strip() for v in self.known_identifiers if v and len(v.strip()) >= 3}
        self._known = [
            re.compile(re.escape(v), re.IGNORECASE) for v in sorted(values, key=len, reverse=True)
        ]

    @property
    def replacements(self) -> dict[str, str]:
        """Pseudonym → kind, for the audit record. Never the original values."""
        return {token: token.strip("[]").rsplit("_", 1)[0] for token in self._tokens.values()}

    def scrub(self, text: str) -> str:
        for pattern in self._known:
            text = pattern.sub(lambda m: self._token("IDENTIFIER", m.group(0)), text)
        text = _EMBS.sub(lambda m: m.group(1) + self._token("EMBS", m.group(2)), text)
        for kind, pattern in _PATTERNS:
            text = pattern.sub(lambda m, kind=kind: self._token(kind, m.group(0)), text)
        return text

    def assert_clean(self, text: str) -> None:
        """The tripwire: fail closed if anything identifying survived."""
        found = find_identity_data(text)
        if any(p.search(text) for p in self._known):
            found.append("IDENTIFIER")
        if found:
            # Kinds only: the message ends up in logs, so it must not carry the values.
            raise IdentityLeak(f"identity data remains after scrubbing: {sorted(set(found))}")

    def _token(self, kind: str, original: str) -> str:
        key = f"{kind}:{original.casefold()}"
        if key not in self._tokens:
            self._counts[kind] = self._counts.get(kind, 0) + 1
            self._tokens[key] = f"[{kind}_{self._counts[kind]}]"
        return self._tokens[key]


def find_identity_data(text: str) -> list[str]:
    """Kinds of pattern-detectable identity data present in text."""
    kinds = [kind for kind, pattern in _PATTERNS if pattern.search(text)]
    if _EMBS.search(text):
        kinds.append("EMBS")
    return kinds


# What a public page masks in text around a quote (docs/legal-notes.md, rule 7): a contact
# person's e-mail and phone. Not addresses: an institution's address is not a person's.
_PUBLIC_MASKS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("[е-пошта]", _EMAIL),
    ("[телефон]", _PHONE_INTL),
    ("[телефон]", _PHONE_DOMESTIC),
)


def mask_contacts(text: str) -> str:
    """The text with e-mail addresses and phone numbers replaced by what they were.

    For the stored text shown around a quote on a public page, never for the quote
    itself: a quote is shown verbatim or not at all (invariant 2).
    """
    for label, pattern in _PUBLIC_MASKS:
        text = pattern.sub(label, text)
    return text
