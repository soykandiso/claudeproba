"""The files in data/ and the lookups over them (P2 session 22).

These are not tests of `reference.py` so much as tests of the *data*. The files
are rebuilt by `ops/dev/import_reference_data.py` from workbooks the statistical
office maintains by hand, and the two defects already found there (a division
typed as a group, a Latin x standing in for Cyrillic х) were both systematic.
The next import will have its own; these assertions are what catches it before a
wrong activity code reaches a customer's shortlist.
"""

import re

import pytest

from app.matching import reference
from app.matching.hard_filter import _SECTIONS, nace_matches, nace_section
from app.matching.reference import CLASS, DIVISION, GROUP, SECTION, SUBCLASS

NACE = reference.nace_index()
MUNICIPALITIES = reference.municipalities()
REGIONS = reference.regions()

CODE_SHAPE = {
    SECTION: re.compile(r"^[A-U]$"),
    DIVISION: re.compile(r"^\d{2}$"),
    GROUP: re.compile(r"^\d{2}\.\d$"),
    CLASS: re.compile(r"^\d{2}\.\d{2}$"),
    SUBCLASS: re.compile(r"^\d{2}\.\d{2}/\d$"),
}


# -- the classification ------------------------------------------------------------------


def test_nace_has_the_shape_nace_rev_2_has():
    """21 sections, 88 divisions, 272 groups, 615 classes. Published, and fixed."""
    counts = {level: sum(1 for e in NACE.values() if e.level == level) for level in CODE_SHAPE}
    assert counts == {SECTION: 21, DIVISION: 88, GROUP: 272, CLASS: 615, SUBCLASS: 4}


@pytest.mark.parametrize("level", sorted(CODE_SHAPE))
def test_every_code_is_shaped_like_its_level(level):
    for entry in NACE.values():
        if entry.level == level:
            assert CODE_SHAPE[level].match(entry.code), entry


def test_every_code_reaches_its_section():
    """A broken chain is an applicant who matches nothing, silently."""
    for entry in NACE.values():
        chain = entry.chain
        assert len(chain) == entry.level, entry
        assert chain[-1] == entry.section
        assert chain[0] == entry.code


def test_no_name_is_empty_or_still_in_the_wrong_alphabet():
    """The office's workbook writes Cyrillic х as a Latin x; the import repairs it."""
    for entry in NACE.values():
        assert entry.name_mk.strip()
        assert not re.search(r"[A-Za-z]", entry.name_mk), entry


def test_every_section_carries_its_macedonian_letter_and_they_are_distinct():
    letters = {e.letter_mk for e in NACE.values() if e.level == SECTION}
    assert len(letters) == 21
    assert not letters & {""}


def test_the_section_letters_really_do_differ_between_the_alphabets():
    """The trap this data exists to close: Macedonian C is В, and В is not B."""
    assert reference.resolve_nace("В").code == "C"
    assert reference.resolve_nace("B").code == "B"
    assert reference.resolve_nace("Ѕ").code == "J"


def test_the_hardcoded_section_ranges_match_the_published_classification():
    """`hard_filter._SECTIONS` is a constant; this is what keeps it honest."""
    for letter, low, high in _SECTIONS:
        divisions = sorted(
            int(e.code) for e in NACE.values() if e.level == DIVISION and e.section == letter
        )
        assert divisions, letter
        assert (divisions[0], divisions[-1]) == (low, high), letter


def test_nace_section_agrees_with_the_data_for_every_code():
    for entry in NACE.values():
        if entry.level > SECTION:
            assert nace_section(entry.code) == entry.section, entry


def test_a_subclass_matches_every_prefix_its_class_matches():
    """Criteria cannot name a subclass, so it must answer as its class does."""
    for entry in NACE.values():
        if entry.level == SUBCLASS:
            for prefix in NACE[entry.parent].chain:
                assert nace_matches(entry.code, prefix), (entry, prefix)


# -- geography ---------------------------------------------------------------------------


def test_there_are_eight_planning_regions_and_eighty_municipalities():
    assert len(REGIONS) == 8
    assert len(MUNICIPALITIES) == 80


def test_every_municipality_is_in_a_region_that_exists():
    for m in MUNICIPALITIES.values():
        assert m.region_code in REGIONS, m


def test_every_region_has_municipalities():
    covered = {m.region_code for m in MUNICIPALITIES.values()}
    assert covered == set(REGIONS)


def test_the_city_of_skopje_is_ten_municipalities_inside_the_skopje_region():
    """Град Скопје funds its own ten; the Skopje planning region holds seventeen."""
    city = [m for m in MUNICIPALITIES.values() if m.city_of_skopje]
    assert len(city) == 10
    assert {m.region_code for m in city} == {"MK008"}
    assert sum(1 for m in MUNICIPALITIES.values() if m.region_code == "MK008") == 17


def test_codes_are_one_alphabet_and_nest_inside_their_region():
    """The source file types МК001 in Cyrillic and MK00102 in Latin, in one column."""
    for m in MUNICIPALITIES.values():
        assert re.fullmatch(r"MK\d{5}", m.code), m
        assert m.code.startswith(m.region_code), m
    for r in REGIONS.values():
        assert re.fullmatch(r"MK\d{3}", r.code), r


def test_names_are_macedonian_and_unique():
    names = [m.name_mk for m in MUNICIPALITIES.values()]
    assert len(set(names)) == len(names)
    for name in names:
        assert not re.search(r"[A-Za-z]", name), name


def test_the_dzs_number_is_four_digits_and_identifies_one_municipality():
    ids = [m.dzs_id for m in MUNICIPALITIES.values()]
    assert len(set(ids)) == len(ids)
    assert all(re.fullmatch(r"\d{4}", i) for i in ids)


# -- lookups -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("MK00814", "MK00814"),
        ("mk00814", "MK00814"),
        ("Центар", "MK00814"),
        ("  центар ", "MK00814"),
        ("Centar", "MK00814"),
        ("0060", "MK00814"),
        ("Чешиново - Облешево", "MK00210"),
        ("Чешиново-Облешево", "MK00210"),
    ],
)
def test_a_municipality_is_found_however_it_was_typed(typed, expected):
    assert reference.resolve_municipality(typed).code == expected


@pytest.mark.parametrize("typed", ["", None, "Скопје", "Ниш", "MK09999", "9999"])
def test_an_unknown_municipality_is_none_rather_than_a_guess(typed):
    assert reference.resolve_municipality(typed) is None


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("62.01", "62.01"),
        ("62.01 Компјутерско програмирање", "62.01"),
        ("69.10/1", "69.10/1"),
        ("01.1", "01.1"),
        ("62", "62"),
        ("c", "C"),
        ("Одгледување на тутун", "01.15"),
        ("одгледување на тутун", "01.15"),
    ],
)
def test_an_activity_is_found_however_it_was_typed(typed, expected):
    assert reference.resolve_nace(typed).code == expected


@pytest.mark.parametrize("typed", ["", None, "99.99", "1", "62.999", "нешто друго", "Z"])
def test_an_unknown_activity_is_none_rather_than_a_guess(typed):
    assert reference.resolve_nace(typed) is None


def test_search_finds_an_activity_a_person_would_type():
    hits = reference.search_nace("леб")
    assert "10.71" in {h.code for h in hits}
    assert all(h.level in (CLASS, SUBCLASS) for h in hits)


def test_search_is_bounded_and_stable():
    assert reference.search_nace("а", limit=5) == reference.search_nace("а", limit=5)
    assert len(reference.search_nace("а", limit=5)) == 5
    assert reference.search_nace("") == []


def test_the_reference_version_is_recorded_and_datelike():
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}\.\d+", reference.version())
