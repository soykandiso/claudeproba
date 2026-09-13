"""PII must never leave. Runs on every commit, forever (docs/repo-skeleton.md)."""

import html
import json
import re
from pathlib import Path

import pytest

from app.ai.scrub import IdentityLeak, Scrubber, find_identity_data

FIXTURES = Path(__file__).parent / "fixtures"

# Invented applicant. Every identity field the gateway must stop is present.
APPLICANT_LETTER = """\
Барател: Бетон Градба ДООЕЛ Скопје
Одговорно лице: Марија Трајковска
ЕМБС: 7123456
ЕДБ: MK4030012345678
Адреса: ул. „Македонија“ бр. 12/3, 1000 Скопје
Телефон: +389 70 123 456, канцеларија 02/3123-456
Е-пошта: marija.trajkovska@betongradba.mk
Бараме поддршка од 200.000 денари за набавка на опрема до 30.09.2026.
"""

IDENTITY_VALUES = [
    "Бетон Градба",
    "Марија Трајковска",
    "7123456",
    "4030012345678",
    "Македонија“ бр. 12",
    "70 123 456",
    "3123-456",
    "marija.trajkovska@betongradba.mk",
]


def scrubbed_letter() -> str:
    scrubber = Scrubber(known_identifiers=["Бетон Градба ДООЕЛ Скопје", "Марија Трајковска"])
    text = scrubber.scrub(APPLICANT_LETTER)
    scrubber.assert_clean(text)
    return text


@pytest.mark.parametrize("value", IDENTITY_VALUES)
def test_no_identity_value_survives(value):
    assert value.casefold() not in scrubbed_letter().casefold()


def test_nothing_pattern_detectable_survives():
    assert find_identity_data(scrubbed_letter()) == []


def test_substance_survives():
    """Amounts and dates are what the model needs; scrubbing must not eat them."""
    text = scrubbed_letter()

    assert "200.000 денари" in text
    assert "30.09.2026" in text
    assert "1000 Скопје" in text


def test_pseudonyms_are_stable_within_a_call():
    scrubber = Scrubber(known_identifiers=["Марија Трајковска"])
    first = scrubber.scrub("Контакт: Марија Трајковска")
    second = scrubber.scrub("Потпис: МАРИЈА ТРАЈКОВСКА")

    assert first.split(": ")[1] == second.split(": ")[1] == "[IDENTIFIER_1]"


def test_the_tripwire_fails_closed_and_does_not_log_the_value():
    scrubber = Scrubber(known_identifiers=["Марија Трајковска"])

    with pytest.raises(IdentityLeak) as raised:
        scrubber.assert_clean("Контакт: Марија Трајковска, marija@example.mk")

    assert "Марија" not in str(raised.value)
    assert "marija" not in str(raised.value)


def test_bare_seven_digit_amounts_are_not_mistaken_for_embs():
    text = Scrubber().scrub(
        "Вкупен буџет од 5000000 денари, или 1 000 000 000 во петгодишен период."
    )

    assert "5000000" in text
    assert "1 000 000 000" in text


def test_real_call_text_keeps_its_amounts_and_dates():
    """A real AV call (tests/fixtures/av): only contact details may change."""
    raw = json.loads((FIXTURES / "av" / "measure-724-business-mk.json").read_text())["d"]
    original = html.unescape(re.sub(r"<[^>]+>", "", raw))

    text = Scrubber().scrub(original)

    for substance in ["11.000 денари", "3 (три) месеци", "микро, мали и средни"]:
        assert substance in original
        assert substance in text
