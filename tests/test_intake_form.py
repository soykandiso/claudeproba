"""The intake form (roadmap P2 s23): the questions, the page, and the picker.

The point of most of these is drift: `app/matching/intake.py` asks the questions and
`app/matching/normalise.py` reads the answers, and a renamed key between the two
would lose a field silently rather than loudly.
"""

import datetime as dt
import re

import pytest
from werkzeug.datastructures import MultiDict

from app.matching import intake, reference
from app.matching.normalise import normalise

BANNED = ["гарантирано", "guaranteed", "approved", "you will receive"]

FULL = {
    "entity": "dooel",
    "municipality": "MK00814",
    "founded": "2022",
    "employees": "2-9",
    "nace": "62.01",
    "turnover": "lt10",
    "inv": ["digital", "equipment"],
    "amount": "1-3",
    "cofinancing": "30",
    "timeline_months": "12",
    "description": "Софтвер за управување со залихи",
}


def form(**overrides) -> MultiDict:
    data = {**FULL, **overrides}
    pairs = []
    for key, value in data.items():
        values = value if isinstance(value, list) else [value]
        pairs.extend((key, v) for v in values)
    return MultiDict(pairs)


def token(client, path="/profil/") -> str:
    page = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def submit(client, **overrides):
    return client.post("/profil/", data=form(csrf=token(client), **overrides))


# ------------------------------------------------------------------ questions


def test_every_question_is_a_key_normalise_reads():
    """A complete intake leaves nothing on the profile unknown.

    This is the drift guard: rename a key in either module and some field below
    goes None, which downstream is *unclear* — correct, but silently useless.
    """
    answers, errors = intake.clean(form(), today=dt.date(2026, 9, 22))

    assert errors == {}
    p = normalise(answers, today=dt.date(2026, 9, 22))
    assert p.nace and p.municipality
    assert p.age_months and p.headcount and p.turnover_mkd and p.investment_mkd
    assert p.cofinancing_pct == 30.0
    assert p.timeline_months == 12
    assert p.entity_types == frozenset({"micro"})
    assert p.project_description == FULL["description"]


def test_only_four_questions_are_required():
    """Under three minutes is an acceptance criterion, and skipping is how it is met."""
    required = [q.key for q in intake.questions() if q.required]

    assert required == ["entity", "municipality", "founded", "employees"]


def test_the_optional_answers_may_all_be_blank():
    answers, errors = intake.clean(
        MultiDict(
            [
                ("entity", "dooel"),
                ("municipality", "MK00814"),
                ("founded", "2022"),
                ("employees", "2-9"),
            ]
        )
    )

    assert errors == {}
    p = normalise(answers, today=dt.date(2026, 9, 22))
    assert (p.nace, p.turnover_mkd, p.investment_mkd, p.cofinancing_pct, p.timeline_months) == (
        None,
        None,
        None,
        None,
        None,
    )


def test_a_missing_required_answer_is_refused_with_what_to_do():
    _, errors = intake.clean(MultiDict())

    assert set(errors) == {"entity", "municipality", "founded", "employees"}
    assert all(message.endswith((".",)) for message in errors.values())


@pytest.mark.parametrize(
    "field,value",
    [
        ("entity", "kompanija"),
        ("employees", "3"),
        ("turnover", "lt5"),
        ("amount", "gt99"),
        ("municipality", "MK99999"),
        ("founded", "22"),
        ("founded", "2400"),
        ("cofinancing", "130"),
        ("cofinancing", "малку"),
        ("timeline_months", "0"),
        ("timeline_months", "999"),
    ],
)
def test_an_answer_that_is_not_an_answer_is_refused(field, value):
    _, errors = intake.clean(form(**{field: value}), today=dt.date(2026, 9, 22))

    assert field in errors


def test_an_unresolvable_activity_is_an_error_not_a_silence():
    """Every other unknown degrades quietly; this one has to be said out loud."""
    _, errors = intake.clean(form(nace="нешто со компјутери"))

    assert "nace" in errors


@pytest.mark.parametrize("value", ["62.01", "62.01 Компјутерско програмирање", "62", "C", "В"])
def test_the_activity_field_takes_what_a_person_would_type(value):
    _, errors = intake.clean(form(nace=value))

    assert errors == {}


def test_the_municipality_picker_is_the_whole_reference_list():
    groups = intake.municipality_groups()
    codes = {code for _, rows in groups for code, _ in rows}

    assert len(groups) == len(reference.regions())
    assert codes == set(reference.municipalities())


# ----------------------------------------------------------------------- page


def test_the_form_renders_in_macedonian_with_every_municipality(client):
    body = client.get("/profil/").get_data(as_text=True)

    assert 'lang="mk"' in body
    assert body.count("<optgroup") == len(reference.regions())
    assert body.count('<option value="MK') == len(reference.municipalities())
    for word in BANNED:
        assert word not in body.lower()


def test_a_refused_form_keeps_what_was_typed_and_says_what_to_fix(client):
    response = submit(client, founded="22")
    body = response.get_data(as_text=True)

    assert response.status_code == 422
    assert 'value="22"' in body
    assert 'id="founded-error"' in body
    assert "Софтвер за управување со залихи" in body  # the rest survived the refusal


def test_a_complete_form_is_saved_and_read_back(client):
    assert submit(client).headers["Location"] == "/profil/pregled"

    body = client.get("/profil/pregled").get_data(as_text=True)
    assert "Компјутерско програмирање" in body
    assert "Центар" in body and "Скопски" in body
    assert "микро претпријатие" in body


def test_the_review_page_says_what_was_not_answered(client):
    client.post(
        "/profil/",
        data=MultiDict(
            [
                ("csrf", token(client)),
                ("entity", "farm"),
                ("municipality", "MK00101"),
                ("founded", "2019"),
                ("employees", "0-1"),
            ]
        ),
    )
    body = client.get("/profil/pregled").get_data(as_text=True)

    assert body.count("Не е одговорено") >= 5


def test_the_description_is_shown_scrubbed_as_well_as_typed(client):
    """Invariant 4 is easier to trust when the page shows what actually leaves."""
    submit(client, description="Нова линија, контакт 070123456")
    body = client.get("/profil/pregled").get_data(as_text=True)

    assert "070123456" in body  # what they typed, back to them
    assert "[PHONE_1]" in body  # what the model would be given


def test_no_profile_means_the_review_page_sends_you_to_the_form(client):
    assert client.get("/profil/pregled").headers["Location"] == "/profil/"


def test_the_form_needs_the_csrf_token(client):
    assert client.post("/profil/", data=form(csrf="guess")).status_code == 400


# --------------------------------------------------------------- the picker


def test_searching_activities_returns_rows_to_pick(client):
    body = client.get("/profil/dejnosti?nace=леб").get_data(as_text=True)

    assert "10.71" in body
    assert 'hx-target="#nace-field"' in body


def test_a_search_that_matches_nothing_says_what_to_do_instead(client):
    body = client.get("/profil/dejnosti?nace=zzzz").get_data(as_text=True)

    assert "шифрата" in body
    assert "picker__list" not in body


def test_one_letter_is_not_a_search(client):
    """A thousand rows behind the first keystroke is a wasted request on mobile data."""
    assert reference.search_nace("л", limit=8)  # the index would happily answer

    body = client.get("/profil/dejnosti?nace=л").get_data(as_text=True)
    assert body.strip() == ""


def test_picking_an_activity_returns_the_field_with_the_code_in_it(client):
    body = client.get("/profil/dejnosti?pick=10.71").get_data(as_text=True)

    assert 'id="nace-field"' in body
    assert 'value="10.71 Производство' in body
    assert "picker__list" not in body  # the results are cleared by the swap


def test_the_picker_degrades_to_a_plain_text_input(client):
    """No JavaScript: the input still posts, and a typed code still resolves."""
    body = client.get("/profil/").get_data(as_text=True)
    scripts = re.findall(r"<script[^>]*src=\"([^\"]+)\"", body)

    assert scripts == ["/static/js/htmx.min.js"]
    assert "<script>" not in body
    assert '<input class="input" id="nace" name="nace" type="text"' in body


# -------------------------------------------------------------------- summary


def test_the_city_of_skopje_is_not_the_skopje_region():
    """Ten municipalities the city funds, seventeen in the planning region."""
    inside = intake.describe(normalise({"municipality": "MK00814"}))  # Центар
    outside = intake.describe(normalise({"municipality": "MK00807"}))  # Илинден

    assert "во Град Скопје" in dict(inside)["Седиште"]
    assert "Скопски регион" in dict(outside)["Седиште"]
    assert "во Град Скопје" not in dict(outside)["Седиште"]
