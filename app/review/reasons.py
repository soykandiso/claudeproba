"""A review item's `reason` in the operator's language (docs/design.md F32).

The pipeline writes reasons in English, on purpose: they are log lines, grepped and
compared across years, and each writer (ingestion, extraction, verification, the
composer, the gateway) owns its own wording. The admin is read in Macedonian, so the
screen says them here, by pattern, and keeps the raw string for the log.

A reason no pattern knows is shown as it is: an English line on the screen is the
signal that a writer added a wording this file has not learned yet, which is better
than a guess. A test checks every reason the code can write.
"""

import re

COMPONENT = {
    "extract_call": "Извлекување",
    "verify_criterion": "Проверка на услов",
    "compose_report": "Нацрт на извештај",
}

# (pattern, Macedonian). Groups are carried across by name.
_PATTERNS = (
    (
        r"new call from (?P<source>\S+): approve before publishing",
        "Нов повик од {source}: прегледајте пред објавување.",
    ),
    (
        r"call document changed at (?P<source>\S+): re-approve",
        "Документ на повикот се промени кај {source}: прегледајте повторно.",
    ),
    (
        r"extract_call: (?P<failed>\d+) of (?P<total>\d+) "
        r"quotes not found verbatim in the documents",
        "Извлекување: {failed} од {total} цитати не се пронајдени дословно во документите.",
    ),
    (
        r"extract_call: the model says this is not a funding call; no call was written",
        "Извлекување: според моделот ова не е повик за средства; повик не е запишан.",
    ),
    (
        r"(?P<task>\w+): model output failed validation twice",
        "{component}: одговорот на моделот двапати не ја помина проверката на форматот.",
    ),
    (
        r"normalising snapshot (?P<snapshot>\d+) needs a human",
        "Читањето на снимката {snapshot} бара човек.",
    ),
    (
        r"manual entry: the URLs could not be fetched",
        "Рачен внес: адресите не можеа да се преземат.",
    ),
    (
        r"manual entry: fetched, but the call could not be processed",
        "Рачен внес: преземено, но повикот не можеше да се обработи.",
    ),
    (
        r"manual entry: nothing new, these documents are already known",
        "Рачен внес: ништо ново, овие документи се веќе познати.",
    ),
    (
        r"verify_criterion: the quote is not at its offsets in the stored text",
        "Проверка на услов: цитатот не стои на своите знаци во зачуваниот текст.",
    ),
    (
        r"verify_criterion: passage (?P<n>\d+) of (?P<total>\d+) does not exist",
        "Проверка на услов: моделот посочи пасус {n}, а има само {total}.",
    ),
    (
        r"verify_criterion: the quote is not in passage (?P<n>\d+)",
        "Проверка на услов: цитатот го нема во пасусот {n}.",
    ),
    (r"compose_report: draft ready for review", "Нацрт на извештај, подготвен за преглед."),
    (
        r"compose_report: blocked, (?P<count>\d+) problem\(s\): (?P<checks>.+)",
        "Нацрт на извештај, блокиран: {problems}.",
    ),
)

_CHECKS = {
    "lint": "забранет израз",
    "citation": "цитат",
    "deadline": "поминат рок",
    "version": "верзија на нацртот",
}


def _problems(count: str, checks: str) -> str:
    n = int(count)
    noun = "проблем" if n % 10 == 1 and n % 100 != 11 else "проблеми"
    words = ", ".join(_CHECKS.get(c.strip(), c.strip()) for c in checks.split(","))
    return f"{n} {noun} ({words})"


def in_macedonian(reason: str | None) -> str:
    """The reason as the operator reads it; unknown wording is returned unchanged."""
    if not reason:
        return ""
    for pattern, words in _PATTERNS:
        match = re.fullmatch(pattern, reason.strip())
        if match is None:
            continue
        found = match.groupdict()
        if "task" in found:
            found["component"] = COMPONENT.get(found["task"], found["task"])
        if "checks" in found:
            found["problems"] = _problems(found["count"], found["checks"])
        return words.format(**found)
    return reason
