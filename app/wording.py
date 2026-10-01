"""How the platform says a number of days to a deadline, in one place.

Two layers say it: the screens (`app/web/format.days_left`) and stage 2's reasons
(`app/matching/stage2.timeline_fit`). They used to say it twice, and on the closing
day the shortlist read «рокот истекува денес» above «До рокот остануваат 0 дена»
(docs/design.md F17). Matching must not import the web layer, so the words live
here, below both, with nothing but the standard library.

The design system: under 14 days a deadline also says the days, in words.
"""

DAYS_IN_WORDS = {
    1: "еден ден",
    2: "два дена",
    3: "три дена",
    4: "четири дена",
    5: "пет дена",
    6: "шест дена",
    7: "седум дена",
    8: "осум дена",
    9: "девет дена",
    10: "десет дена",
    11: "единаесет дена",
    12: "дванаесет дена",
    13: "тринаесет дена",
}

PASSED = "рокот помина"
TODAY = "рокот истекува денес"


def days_in_words(days: int) -> str | None:
    """Words for a deadline `days` calendar days away, or None at 14 and over,
    where the date alone will do."""
    if days < 0:
        return PASSED
    if days == 0:
        return TODAY
    if days in DAYS_IN_WORDS:
        return f"уште {DAYS_IN_WORDS[days]}"
    return None
