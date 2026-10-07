"""The terms, the privacy policy and the processors (roadmap P3 s45).

The acceptance: "liability framing per risks.md R6 is explicit and in plain Macedonian".
"""

import re

from app.legal import legal
from app.reports.lint import find_banned


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))


def test_the_terms_say_what_the_service_is_not(client):
    """R6, said in so many words."""
    terms = _text(client.get("/uslovi").get_data(as_text=True))
    for promise in (
        "Не е правен, даночен ни финансиски совет",
        "Не одлучуваме за средствата и не ветуваме исход",
        "Не поднесуваме барања во ваше име",
        "прочитајте ја неговата последна верзија на страницата на институцијата",
        "Моделот никогаш не одлучува дека не можете да аплицирате",
    ):
        assert promise in terms, promise


def test_neither_text_promises_an_outcome(client):
    for path in ("/uslovi", "/privatnost", "/obrabotuvachi"):
        assert find_banned(_text(client.get(path).get_data(as_text=True))) == [], path


def test_an_undecided_fact_shows_as_undecided(client):
    """Until D4 and D2 are decided, the pages say so instead of inventing a company."""
    body = client.get("/uslovi").get_data(as_text=True)
    assert "[се утврдува]" in body
    assert legal().missing()  # and the launch check knows


def test_a_version_is_readable_by_its_date_and_nothing_else_is(client):
    current = legal().version
    assert client.get(f"/uslovi/{current}").status_code == 200
    assert client.get(f"/privatnost/{current}").status_code == 200
    assert client.get("/uslovi/2000-01-01").status_code == 404
    assert client.get("/uslovi/..%2f..%2fbase").status_code == 404


def test_the_processors_page_lists_nothing_as_fact_that_is_not(client):
    body = client.get("/obrabotuvachi").get_data(as_text=True)
    for p in legal().processors:
        assert p.role in body
    assert "сè уште не е избран" in body  # the backup and mail providers, today
    assert "Anthropic PBC" in body and "Никогаш име" in _text(body)


def test_the_launch_check_fails_while_anything_is_undecided(app):
    result = app.test_cli_runner().invoke(args=["legal", "check"])
    assert result.exit_code == 1 and "entity.name" in result.output


def test_every_page_links_the_terms_and_the_policy(client):
    footer = client.get("/ceni").get_data(as_text=True)
    assert 'href="/uslovi"' in footer and 'href="/privatnost"' in footer
