"""Banned-phrase lint for customer-facing text (CLAUDE.md, docs/matching.md §6).

A hit blocks delivery. The list is phrases that promise an outcome only the
funding institution can decide. Matching is case-insensitive on word stems, so
"Гарантирано", "гарантираме" and "guaranteed" are all caught; that also catches
some innocent uses, and that is the right way round for this product.

Built for the demo stage (16.09.2026). P2 session 32 wires it into the report
composer so a draft that fails cannot be sent.
"""

import re

BANNED: tuple[tuple[str, str], ...] = (
    # (pattern, what to tell the reviewer)
    (r"гарантира", "гарантирано / гарантираме"),
    (r"guarantee", "guaranteed"),
    (r"\bapproved\b", "approved"),
    (r"you will receive", "you will receive"),
    (r"\bодобрен[оаи]?\b", "одобрено"),
    (r"\bќе (?:ги )?добиете", "ќе добиете"),
    (r"garantuar", "e garantuar"),
    (r"miratuar", "miratuar"),
    (r"do të merrni", "do të merrni"),
)

_COMPILED = [(re.compile(p, re.IGNORECASE), label) for p, label in BANNED]


def find_banned(text: str) -> list[str]:
    """Labels of every banned phrase present in the text; empty when it is clean."""
    return [label for pattern, label in _COMPILED if pattern.search(text)]
