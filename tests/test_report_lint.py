import pytest

from app.reports.lint import find_banned


@pytest.mark.parametrize(
    "text",
    [
        "Финансирањето е гарантирано.",
        "Гарантираме дека ќе поминете.",
        "Your application is approved.",
        "You will receive 30.000 EUR.",
        "Барањето е одобрено.",
        "Ќе добиете грант до крајот на годината.",
        "Financimi është i garantuar.",
    ],
)
def test_banned_phrases_are_caught(text):
    assert find_banned(text)


def test_honest_report_prose_passes():
    text = (
        "Условите што може да се проверат од профилот се исполнети. "
        "Одлуката за доделување ја носи Фондот за иновации и технолошки развој. "
        "Се финансира значително подобрен производ."  # "подобрен" contains "одобрен"
    )
    assert find_banned(text) == []
