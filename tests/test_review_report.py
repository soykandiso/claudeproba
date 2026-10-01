"""The report review screen (roadmap P2 s33): read, edit, approve or close a draft.

The row's acceptance — a full report approved or edited in under 45 minutes — is a
person's time and cannot be a test; the screen says the minutes back at the
decision. What is proven here is what the handoff made s33 owe: **approval calls
`compose.blockers()` and refuses while it returns anything**, through the service
and through the screen, and no edit can bring back what the checks exist to stop.
"""

import copy
import re

import pytest

from app import create_app
from app.config import load_settings
from app.models import ReviewQueueItem
from app.models.enums import ReviewKind, ReviewState
from app.review import report as reports
from app.review.extraction import ReviewError
from tests import test_report_compose as tc
from tests.test_stage1 import DATABASE_AVAILABLE, NOW

pytestmark = pytest.mark.skipif(not DATABASE_AVAILABLE, reason="no database reachable")

registry = tc.registry
world = tc.world

BANNED = "Финансирањето е гарантирано ако ги исполнувате условите."
FIXED = "Условот за дејноста е исполнет според текстот на повикот, но одлуката е на институцијата."


def draft_item(world, *replies) -> tuple:
    factory, run_id = tc.verified_run(world)
    item, _ = tc.composed(factory, run_id, *(replies or (tc.prose(),)))
    return factory, item.id


def fetch(factory, item_id) -> ReviewQueueItem:
    with factory() as s:
        return s.get(ReviewQueueItem, item_id)


def edit(factory, item_id, *, part="summary", call=None, n=1, text=FIXED, cites="1.1"):
    with factory() as s:
        item = s.get(ReviewQueueItem, item_id)
        reports.edit_statement(
            s, item, part=part, call=call, n=n, text_mk=text, cites=cites, now=NOW
        )
        s.commit()


# ------------------------------------------------------------------ approval is gated


def test_a_blocked_draft_cannot_be_approved(world):
    factory, item_id = draft_item(world, tc.prose(summary=[tc.statement(BANNED)]))

    with factory() as s:
        item = s.get(ReviewQueueItem, item_id)
        with pytest.raises(ReviewError, match="не може да се одобри"):
            reports.approve(s, item, note="", now=NOW)
        s.rollback()
    assert fetch(factory, item_id).state == ReviewState.PENDING


def test_a_reviewer_edits_a_blocked_draft_clean_and_then_approves_it(world):
    factory, item_id = draft_item(world, tc.prose(summary=[tc.statement(BANNED)]))

    edit(factory, item_id)

    item = fetch(factory, item_id)
    assert item.payload["summary"][0]["text_mk"] == BANNED  # what the model wrote stays
    assert item.corrected_payload["summary"][0]["text_mk"] == FIXED
    [logged] = item.corrected_payload["edits"]
    assert logged["where"] == "summary 1" and logged["before"]["text_mk"] == BANNED
    with factory() as s:
        item = s.get(ReviewQueueItem, item_id)
        assert reports.approval_problems(s, item) == []
        reports.approve(s, item, note="", now=NOW)
        s.commit()
    assert fetch(factory, item_id).state == ReviewState.EDITED


def test_a_clean_draft_is_approved_as_composed(world):
    factory, item_id = draft_item(world)
    with factory() as s:
        reports.approve(s, s.get(ReviewQueueItem, item_id), note="во ред", now=NOW)
        s.commit()
    item = fetch(factory, item_id)
    assert item.state == ReviewState.APPROVED and item.reviewer_note == "во ред"
    assert item.corrected_payload is None


def test_a_decided_report_cannot_be_decided_again(world):
    factory, item_id = draft_item(world)
    with factory() as s:
        item = s.get(ReviewQueueItem, item_id)
        reports.close(s, item, note="не е за испраќање", now=NOW)
        s.commit()
        with pytest.raises(ReviewError):
            reports.approve(s, item, note="", now=NOW)
        with pytest.raises(ReviewError):
            reports.edit_statement(
                s, item, part="summary", call=None, n=1, text_mk=FIXED, cites="1.1", now=NOW
            )


def test_closing_needs_a_reason(world):
    factory, item_id = draft_item(world)
    with factory() as s, pytest.raises(ReviewError, match="причина"):
        reports.close(s, s.get(ReviewQueueItem, item_id), note="  ", now=NOW)


# ------------------------------------------------------------------ an edit cannot undo the checks


@pytest.mark.parametrize(
    ("text", "cites", "said"),
    [
        ("Ќе добиете грант до крајот на годината, ако аплицирате.", "1.1", "забранет израз"),
        (FIXED, "2.1", "не е услов на овој повик"),
        (FIXED, "", "меѓу еден и осум услови"),
        (FIXED, "први", "броеви како 1.2"),
        ("Кратко.", "1.1", "меѓу 10 и 700 знаци"),
    ],
)
def test_an_edit_that_would_not_pass_the_checks_is_refused_and_changes_nothing(
    world, text, cites, said
):
    factory, item_id = draft_item(world)

    with pytest.raises(ReviewError, match=said):
        edit(factory, item_id, part="explanation", call=1, text=text, cites=cites)

    assert fetch(factory, item_id).corrected_payload is None


def test_the_last_explanation_of_a_call_cannot_be_removed_but_a_next_step_can(world):
    factory, item_id = draft_item(world)
    with factory() as s:
        item = s.get(ReviewQueueItem, item_id)
        with pytest.raises(ReviewError, match="единствената"):
            reports.remove_statement(s, item, part="explanation", call=1, n=1, now=NOW)
        reports.remove_statement(s, item, part="next_steps", call=1, n=1, now=NOW)
        s.commit()
    item = fetch(factory, item_id)
    assert item.corrected_payload["calls"][0]["next_steps"] == []
    assert item.corrected_payload["edits"][0]["after"] is None


def test_verdicts_and_quotes_are_not_the_reviewers_to_edit(world):
    """Only prose has an edit path: a statement address cannot reach a condition."""
    factory, item_id = draft_item(world)
    with pytest.raises(ReviewError):
        edit(factory, item_id, part="conditions", call=1)
    with pytest.raises(ReviewError):
        edit(factory, item_id, part="explanation", call=7)


# ------------------------------------------------------------------ words for the reviewer


def test_every_problem_compose_can_raise_is_said_in_macedonian():
    for english in [
        "banned phrase: гарантирано / гарантираме",
        "no citation",
        "no source URL or retrieval date",
        "snapshot 12 has no stored text",
        "the quote is not at 10–15",
        "a statement that cites nothing",
        "cites 2.1, not a condition here",
        "there is no such call",
        "no explanation",
        "unknown draft version 0",
    ]:
        assert not re.search("[a-z]{3}", reports.describe(english).replace("гарант", "")), english


@pytest.mark.parametrize(
    ("where", "anchor"),
    [
        ("summary 2", "izjava-summary-2"),
        ("call 1 next_steps 3", "izjava-1-next_steps-3"),
        ("call 2", "povik-2"),
        ("condition 1.4", "uslov-1-4"),
        ("condition 1.4 evidence", "uslov-1-4"),
    ],
)
def test_a_problem_links_to_where_it_is_on_the_page(where, anchor):
    assert reports.place(where)[1] == anchor


# ------------------------------------------------------------------ the screen


@pytest.fixture
def admin(world, monkeypatch):
    factory = world[0]
    app = create_app(load_settings(env="testing", secret_key="test"))
    monkeypatch.setattr("app.web.admin._sessions", lambda: factory)
    return app.test_client()


def csrf(client, path) -> str:
    page = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def test_the_report_is_listed_and_shows_each_quote_where_the_stored_text_has_it(world, admin):
    factory, item_id = draft_item(world)

    queue = admin.get("/admin/").get_data(as_text=True)
    assert f"/admin/izveshtaj/{item_id}" in queue and "1 повик за проверка" in queue

    html = admin.get(f"/admin/izveshtaj/{item_id}").get_data(as_text=True)
    assert "<mark>цитат</mark>" in html
    assert 'id="uslov-1-1"' in html and 'href="#uslov-1-1"' in html
    assert "https://gov.example/call" in html
    assert "Прифати го извештајот</button>" in html
    assert "disabled" not in html.split("Прифати го извештајот")[0][-120:]


def test_a_blocked_report_says_why_and_the_screen_refuses_it(world, admin):
    factory, item_id = draft_item(world, tc.prose(summary=[tc.statement(BANNED)]))
    path = f"/admin/izveshtaj/{item_id}"

    html = admin.get(path).get_data(as_text=True)
    assert 'href="#izjava-summary-1">Резиме, изјава 1</a>: забранет израз' in html
    assert re.search(r"disabled[^>]*>Прифати го извештајот", html)

    response = admin.post(f"{path}/odobri", data={"csrf": csrf(admin, path)})
    assert response.status_code == 422
    assert "не може да се одобри" in response.get_data(as_text=True)
    assert fetch(factory, item_id).state == ReviewState.PENDING


def test_editing_through_the_screen_and_approving_reports_the_minutes(world, admin):
    factory, item_id = draft_item(world, tc.prose(summary=[tc.statement(BANNED)]))
    path = f"/admin/izveshtaj/{item_id}"
    token = csrf(admin, path)

    response = admin.post(
        f"{path}/izjava",
        data={"csrf": token, "part": "summary", "call": "", "n": "1", "text_mk": FIXED,
              "cites": "1.1"},
    )  # fmt: skip
    assert response.status_code == 302 and response.location.endswith("#izjava-summary-1")

    response = admin.post(f"{path}/odobri", data={"csrf": token})
    assert response.status_code == 302
    assert "Прегледот траеше околу" in admin.get("/admin/").get_data(as_text=True)
    assert fetch(factory, item_id).state == ReviewState.EDITED


def test_a_refused_edit_is_shown_with_what_was_typed(world, admin):
    factory, item_id = draft_item(world)
    path = f"/admin/izveshtaj/{item_id}"

    response = admin.post(
        f"{path}/izjava",
        data={"csrf": csrf(admin, path), "part": "explanation", "call": "1", "n": "1",
              "text_mk": "Ќе добиете средства, тоа е сигурно.", "cites": "1.1"},
    )  # fmt: skip

    html = response.get_data(as_text=True)
    assert response.status_code == 422
    assert "Не е зачувано." in html and "забранет израз" in html
    assert "Ќе добиете средства, тоа е сигурно.</textarea>" in html
    assert fetch(factory, item_id).corrected_payload is None


def test_output_the_gateway_refused_can_only_be_closed(world, admin):
    factory, run_id = tc.verified_run(world)
    uncited = tc.prose(summary=[tc.statement(cites=[])])
    item, _ = tc.composed(factory, run_id, uncited, uncited)
    path = f"/admin/izveshtaj/{item.id}"

    html = admin.get(path).get_data(as_text=True)
    assert "Одговорот на моделот не ја помина шемата" in html
    assert "Прифати го извештајот" not in html
    response = admin.post(f"{path}/odobri", data={"csrf": csrf(admin, path)})
    assert response.status_code == 422
    response = admin.post(
        f"{path}/zatvori", data={"csrf": csrf(admin, path), "note": "составете повторно"}
    )
    assert response.status_code == 302
    assert fetch(factory, item.id).state == ReviewState.REJECTED


def test_a_report_page_does_not_open_other_kinds_of_item(world, admin):
    factory = world[0]
    with factory() as s:
        other = ReviewQueueItem(kind=ReviewKind.EXTRACTION, reason="x", payload={})
        s.add(other)
        s.commit()
        other_id = other.id
    assert admin.get(f"/admin/izveshtaj/{other_id}").status_code == 404
    assert admin.get("/admin/izveshtaj/999999999").status_code == 404


def test_a_draft_whose_citation_moved_is_shown_as_blocked(world, admin):
    """The screen re-checks on every view; the composer's findings are not trusted."""
    factory, item_id = draft_item(world)
    with factory() as s:
        item = s.get(ReviewQueueItem, item_id)
        edited = copy.deepcopy(item.payload)
        edited["calls"][0]["conditions"][0]["citation"]["char_start"] += 1
        item.corrected_payload = edited
        s.commit()

    html = admin.get(f"/admin/izveshtaj/{item_id}").get_data(as_text=True)
    assert 'href="#uslov-1-1">Услов 1.1</a>: цитатот не стои на знаците' in html
