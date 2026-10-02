"""The operator screens' design pass (DS7): the admin in Macedonian, the decision one jump
away, removal as a second step, and the shell like the site's."""

from pathlib import Path

import pytest

from app.review import reasons
from tests import test_report_compose as tc
from tests.test_report_render import admin, needs_db, registry, world  # noqa: F401 (fixtures)

TEMPLATES = Path(__file__).resolve().parents[1] / "app" / "web" / "templates" / "admin"


@pytest.mark.parametrize(
    ("reason", "said"),
    [
        (
            "new call from av: approve before publishing",
            "Нов повик од av: прегледајте пред објавување.",
        ),
        (
            "call document changed at economy: re-approve",
            "Документ на повикот се промени кај economy",
        ),
        ("extract_call: 7 of 8 quotes not found verbatim in the documents", "7 од 8 цитати"),
        (
            "extract_call: the model says this is not a funding call; no call was written",
            "не е повик",
        ),
        ("compose_report: model output failed validation twice", "Нацрт на извештај: одговорот"),
        ("normalising snapshot 12 needs a human", "снимката 12 бара човек"),
        ("manual entry: the URLs could not be fetched", "адресите не можеа"),
        ("manual entry: fetched, but the call could not be processed", "не можеше да се обработи"),
        ("manual entry: nothing new, these documents are already known", "ништо ново"),
        ("verify_criterion: the quote is not at its offsets in the stored text", "своите знаци"),
        ("verify_criterion: passage 7 of 6 does not exist", "пасус 7, а има само 6"),
        ("verify_criterion: the quote is not in passage 3", "во пасусот 3"),
        ("compose_report: draft ready for review", "подготвен за преглед"),
        ("compose_report: blocked, 1 problem(s): lint", "1 проблем (забранет израз)"),
        (
            "compose_report: blocked, 4 problem(s): citation, deadline",
            "4 проблеми (цитат, поминат рок)",
        ),
    ],
)
def test_every_reason_the_pipeline_writes_is_said_in_macedonian(reason, said):
    """F32. The patterns are the writers' own f-strings; a new wording shows up here."""
    assert said in reasons.in_macedonian(reason)


def test_an_unknown_reason_is_shown_as_it_is_not_guessed():
    assert reasons.in_macedonian("something new: x") == "something new: x"
    assert reasons.in_macedonian(None) == ""


def test_the_writers_still_write_what_the_patterns_know():
    """If a writer changes its wording, this fails before the screen shows English."""
    sources = {
        "app/ingestion/pipeline.py": [
            "approve before publishing",
            ": re-approve",
            "not a funding call",
        ],
        "app/ingestion/extract.py": ["quotes not found verbatim in the documents"],
        "app/ai/gateway.py": ["model output failed validation twice"],
        "app/ingestion/normalise/snapshot.py": ["needs a human"],
        "app/ingestion/sources/manual.py": [
            "could not be fetched",
            "could not be processed",
            "already known",
        ],
        "app/matching/verify.py": ["does not exist", "the quote is not in passage"],
        "app/matching/deep.py": ["the quote is not at its offsets in the stored text"],
        "app/reports/compose.py": ["draft ready for review", "problem(s)"],
    }
    root = Path(__file__).resolve().parents[1]
    for path, phrases in sources.items():
        text = (root / path).read_text(encoding="utf-8")
        assert [p for p in phrases if p not in text] == [], path


def test_the_admin_shell_is_the_sites():
    """F08: no name decided before D2. F09: a skip link and a focusable main."""
    base = (TEMPLATES / "base.html").read_text(encoding="utf-8")
    assert "Грантови.мк" not in base and "Грантови и субвенции" in base
    assert 'class="skip" href="#main"' in base and '<main id="main" tabindex="-1">' in base


def test_removal_is_a_second_step_that_looks_like_removal():
    """F34: never a button like «Зачувај» directly under it."""
    for name in ("item.html", "report.html"):
        page = (TEMPLATES / name).read_text(encoding="utf-8")
        assert '<details class="confirm">' in page
        assert "kind='destructive'" in page
        assert 'btn btn--quiet" type="submit">Отстрани' not in page


def test_no_session_number_on_screen():
    """F35."""
    for page in TEMPLATES.glob("*.html"):
        assert "P2 s3" not in page.read_text(encoding="utf-8"), page.name


@needs_db
def test_the_decision_is_one_jump_away_and_says_why_it_is_shut(world, admin):  # noqa: F811
    """F33: a bar under the problems, a link to the decision and to each call, and the
    disabled approval says its reason beside it."""
    factory, run_id = tc.verified_run(world)
    item, _ = tc.composed(factory, run_id, tc.prose())
    page = admin.get(f"/admin/izveshtaj/{item.id}").get_data(as_text=True)

    assert 'class="decision-bar"' in page and 'href="#odluka"' in page
    assert 'id="odluka"' in page and 'href="#povik-1"' in page
    assert page.index('class="decision-bar"') < page.index('id="odluka"')
