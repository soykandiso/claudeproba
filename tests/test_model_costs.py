"""What the model costs (roadmap P2 s36): by month, task and report; the ceiling's alarm.

Against PostgreSQL in a rolled-back transaction. The model calls are written in 2031,
a month no real row is in, so the sums are this test's own.
"""

import datetime as dt
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import update

from app import create_app
from app.ai import costs
from app.config import load_settings
from app.ingestion.health import OVER_CEILING, SPEND, report, spend_state
from app.models import MatchRun, ModelCall, Order
from app.models.enums import OrderState
from tests.test_reconcile import _ordered
from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

TZ = ZoneInfo("Europe/Skopje")
NOW = dt.datetime(2031, 3, 20, 9, 0, tzinfo=dt.UTC)
RATE = 0.5  # round, so the euros are easy to read


def _call(s, task, usd, at, *, cached=False, ok=True, run=None):
    s.add(
        ModelCall(
            task=task,
            model="claude-opus-5",
            input_hash="x" * 64,
            cache_hit=cached,
            ok=ok,
            input_tokens=1000,
            output_tokens=100,
            cost_usd=usd,
            match_run_id=run,
            created_at=at,
        )
    )
    s.flush()


def test_a_month_starts_at_midnight_in_skopje_not_in_utc():
    # 31.03 at 23:30 UTC is already 01.04 in Skopje (UTC+2 in summer time).
    late = dt.datetime(2031, 3, 31, 23, 30, tzinfo=dt.UTC)
    assert costs.month_start(late, TZ) == dt.datetime(2031, 4, 1, tzinfo=TZ)


def test_the_median_of_an_even_count_is_the_middle_two():
    assert costs.median([]) is None
    assert costs.median([3.0, 1.0, 2.0]) == 2.0
    assert costs.median([4.0, 1.0, 3.0, 2.0]) == 2.5


def test_the_rate_is_written_down_in_the_routing_file():
    assert 0.5 < costs.eur_per_usd() < 1.5


@db
def test_this_month_by_task_and_against_the_ceiling(registry):  # noqa: F811
    with registry[0]() as s:
        _call(s, "verify_criterion", 4, NOW - dt.timedelta(days=2))
        _call(s, "verify_criterion", 0, NOW - dt.timedelta(days=2), cached=True)
        _call(s, "extract_call", 1, NOW - dt.timedelta(days=1), ok=False)
        _call(s, "extract_call", 50, dt.datetime(2031, 2, 27, tzinfo=dt.UTC))  # last month

        spend = costs.month_to_date(s, NOW, TZ, ceiling_eur=30, rate=RATE)
        assert (spend.usd, spend.eur, spend.over) == (5, 2.5, False)

        tasks = {t.task: t for t in costs.by_task(s, spend.since, NOW)}
        assert (tasks["verify_criterion"].calls, tasks["verify_criterion"].cached) == (2, 1)
        assert (tasks["extract_call"].failed, tasks["extract_call"].cost_usd) == (1, 1)

        months = costs.by_month(s, NOW, TZ, months=3)
        assert [f"{m.start:%m.%Y}" for m in months] == ["03.2031", "02.2031", "01.2031"]
        assert [m.cost_usd for m in months[1:]] == [50, 0]


@db
def test_over_the_ceiling_alerts_once_like_a_source(registry):  # noqa: F811
    with registry[0]() as s:
        _call(s, "verify_criterion", 70, NOW - dt.timedelta(hours=2))
        state = spend_state(s, NOW, TZ, ceiling_eur=30, rate=RATE)
        assert state.slug == SPEND and state.status == OVER_CEILING
        assert state.newly_alerting
        assert "35.00 EUR of 30.00 EUR this month (117%)" in state.detail
        text = report([], NOW, TZ, state)
        assert "OVER_CEILING (new)  model spend" in text and "The model spend alert" in text
        assert "USD" not in text  # МКД and EUR only (CLAUDE.md)

        # A day later, still over: told already, not new.
        state = spend_state(s, NOW + dt.timedelta(days=1), TZ, ceiling_eur=30, rate=RATE)
        assert state.alerting and not state.newly_alerting

        # Under the ceiling: an ok line, no alarm.
        assert not spend_state(s, NOW, TZ, ceiling_eur=100, rate=RATE).alerting


@db
def test_a_report_costs_what_its_match_run_called(registry):  # noqa: F811
    with registry[0]() as s:
        order, invoice = _ordered(s)
        run = MatchRun(
            profile_id=order.profile_id, ruleset_version="t", weights_version="t", stage_reached=4
        )
        s.add(run)
        s.flush()
        _call(s, "verify_criterion", 1.5, NOW, run=run.id)
        _call(s, "verify_criterion", 0, NOW, run=run.id, cached=True)
        _call(s, "compose_report", 0.5, NOW, run=run.id)
        s.execute(
            update(Order)
            .where(Order.id == order.id)
            .values(
                match_run_id=run.id,
                state=OrderState.DELIVERED,
                delivered_at=NOW,
                report_storage_key="reports/test.pdf",
            )
        )
        [mine] = [r for r in costs.per_report(s, limit=200) if r.order_id == order.id]
        assert (mine.calls, mine.cached, mine.cost_usd) == (3, 1, 2.0)


@pytest.fixture
def admin(registry, monkeypatch):  # noqa: F811
    monkeypatch.setattr("app.web.admin._sessions", lambda: registry[0])
    monkeypatch.setattr("app.web.admin._now", lambda: NOW)
    return create_app(load_settings(env="testing")).test_client(), registry[0]


@db
def test_the_admin_page_shows_the_month_the_tasks_and_the_ceiling(admin):
    client, factory = admin
    with factory() as s:
        _call(s, "verify_criterion", 40, NOW - dt.timedelta(days=1))
        s.commit()
    page = client.get("/admin/troshoci").get_data(as_text=True)
    assert "Трошоци за моделот" in page and "Проверка на услов" in page
    assert "Над горната граница" in page  # 40 USD is over 30 EUR at any sane rate
    assert "03.2031" in page and "USD" not in page
