"""The review queue for extraction items (roadmap P1 s15).

Acceptance: approve / edit / reject work, and only approved calls get
is_published = true. Calls come from the real pipeline over the AV fixtures
(tests/test_pipeline.py), so what is reviewed is what ingestion writes.
"""

import datetime as dt
import re
import uuid

import pytest
from sqlalchemy import select

from app import create_app
from app.config import load_settings
from app.ingestion import pipeline
from app.ingestion.normalise import NORMALISER_VERSION
from app.matching.hard_filter import Stored, prefilter_columns
from app.matching.operators import Operator, ProfileField
from app.models import Call, EligibilityCriterion, RawSnapshot, ReviewQueueItem
from app.models.enums import CriterionKind, ReviewState
from app.review import extraction as review
from tests.test_extract import ScriptedProvider
from tests.test_extract_schema import cassette
from tests.test_pipeline import AvSite, run, sessions, store  # noqa: F401 -- fixtures

NOW = dt.datetime(2026, 8, 10, 12, 0, tzinfo=dt.UTC)
TZ = dt.timezone(dt.timedelta(hours=2))


# -- the prefilter columns (no database) ---------------------------------------------------


def crit(field, operator, value):
    return Stored(ProfileField(field), Operator(operator), value)


def test_one_in_on_entity_type_or_nace_becomes_the_prefilter_column():
    columns = prefilter_columns(
        [crit("entity_type", "in", ["small", "micro"]), crit("nace_code", "prefix_in", ["C"])]
    )
    assert columns.allowed_entity_types == ["micro", "small"]
    assert columns.allowed_nace_prefixes == ["C"]
    assert columns.allowed_regions == []


@pytest.mark.parametrize(
    "criteria",
    [
        # A startup that is also micro satisfies both; an intersection would drop it.
        [crit("entity_type", "in", ["startup"]), crit("entity_type", "in", ["micro"])],
        [crit("entity_type", "not_in", ["municipality"])],
        [crit("nace_code", "prefix_not_in", ["K"])],
    ],
)
def test_what_an_overlap_test_cannot_express_restricts_nothing_in_sql(criteria):
    columns = prefilter_columns(criteria)
    assert columns.allowed_entity_types == [] and columns.allowed_nace_prefixes == []


def test_age_bounds_are_the_tightest_and_rounded_outward():
    columns = prefilter_columns(
        [
            crit("age_months", "gte", 6.5),
            crit("age_months", "between", (12, 60.2)),
            crit("age_months", "lte", 48),
        ]
    )
    assert (columns.min_company_age_months, columns.max_company_age_months) == (12, 48)
    assert prefilter_columns([crit("age_months", "gte", 6.5)]).min_company_age_months == 6


def test_stored_value_json_reads_back_as_the_interpreter_expects():
    assert Stored.from_row("headcount", "between", {"min": 2, "max": 9}).value == (2, 9)
    assert Stored.from_row("headcount", "gte", {"min": 2}).value == 2
    assert Stored.from_row("entity_type", "in", {"values": ["micro"]}).value == ["micro"]


# -- decisions ----------------------------------------------------------------------------


@pytest.fixture
def site():
    return AvSite()


@pytest.fixture
def written(sessions, store, site):  # noqa: F811
    """AV announcement 819 through the pipeline: one unpublished call, one approval item."""
    result = run(sessions, store, site, ScriptedProvider(cassette("av-measure-819")))
    assert [p.outcome for p in result.processed] == [pipeline.CREATED]
    return result.processed[0]


def load(sessions, processed):  # noqa: F811
    s = sessions()
    return s, s.get(ReviewQueueItem, processed.review_item_id), s.get(Call, processed.call_id)


def criteria(s, call):
    return review.criteria_of(s, call)


@pytest.mark.usefixtures("store")
def test_approving_publishes_the_call_with_its_criteria(sessions, written):  # noqa: F811
    s, item, call = load(sessions, written)
    assert review.stage_of(item) == review.APPROVE_CALL and not call.is_published
    assert review.approval_problems(s, item) == []

    review.approve_call(s, item, note="прочитано", now=NOW)
    s.commit()

    assert call.is_published
    assert all(c.is_approved for c in criteria(s, call))
    assert item.state == ReviewState.APPROVED and item.resolved_at == NOW
    assert item.reviewer_note == "прочитано"
    # AV's only hard criterion is `not_in [municipality]`: the SQL prefilter cannot
    # express it, so the rule interpreter alone judges it.
    assert call.allowed_entity_types == []
    s.close()


def test_rejecting_publishes_nothing_needs_a_reason_and_is_not_asked_again(
    sessions,  # noqa: F811
    store,  # noqa: F811
    site,
    written,
):
    s, item, call = load(sessions, written)
    with pytest.raises(review.ReviewError, match="причина"):
        review.close(s, item, note="  ", now=NOW)

    review.close(s, item, note="вест, не повик", now=NOW)
    s.commit()
    assert item.state == ReviewState.REJECTED and not call.is_published
    with pytest.raises(review.ReviewError):
        review.approve_call(s, item, note=None, now=NOW)
    s.close()

    provider = ScriptedProvider()
    again = run(sessions, store, site, provider)
    assert [p.outcome for p in again.processed] == [pipeline.UNCHANGED]
    assert provider.requests == []
    with sessions() as s:
        assert not s.get(Call, written.call_id).is_published


def test_a_quote_that_no_longer_matches_its_snapshot_blocks_publishing(sessions, written):  # noqa: F811
    s, item, call = load(sessions, written)
    first = criteria(s, call)[0]
    first.quote_start += 1
    s.flush()

    problems = review.approval_problems(s, item)
    assert any("дословно" in p for p in problems)
    with pytest.raises(review.ReviewError):
        review.approve_call(s, item, note=None, now=NOW)
    assert not call.is_published and item.state == ReviewState.PENDING
    s.close()


def test_a_banned_phrase_in_customer_facing_text_blocks_publishing(sessions, written):  # noqa: F811
    s, item, call = load(sessions, written)
    criteria(s, call)[0].label_mk = "Гарантирано финансирање за работодавачи"
    s.flush()

    assert any("забранет израз" in p for p in review.approval_problems(s, item))
    s.close()


def form_from(c: EligibilityCriterion, **changes) -> review.CriterionForm:
    values = ", ".join((c.value_json or {}).get("values") or [])
    base = dict(
        kind=c.kind.value,
        label_mk=c.label_mk,
        quote=c.source_quote,
        field=c.field or "",
        operator=c.operator or "",
        values=values,
    )
    return review.CriterionForm(**(base | changes))


def test_an_edited_criterion_is_validated_relocated_recorded_and_published_as_edited(
    sessions,  # noqa: F811
    written,
):
    s, item, call = load(sessions, written)
    attest = next(c for c in criteria(s, call) if c.kind == CriterionKind.APPLICANT_ATTEST)
    quote = "се од приватен и од граѓански сектор"  # the quote of the hard criterion, shortened

    edited = review.edit_criterion(
        s,
        item,
        attest.id,
        form_from(
            attest,
            kind="hard_structured",
            label_mk="Само микро и мали работодавачи",
            quote=quote,
            field="entity_type",
            operator="in",
            values="small, micro",
        ),
        now=NOW,
    )
    s.flush()

    text = s.get(RawSnapshot, edited.snapshot_id).normalised_text
    assert text[edited.quote_start : edited.quote_end] == edited.source_quote == quote
    assert edited.value_json == {"values": ["small", "micro"]}
    [edit] = item.corrected_payload["edits"]
    assert edit["target"] == f"criterion:{attest.id}"
    assert (
        edit["before"]["kind"] == "applicant_attest" and edit["after"]["kind"] == "hard_structured"
    )

    review.approve_call(s, item, note=None, now=NOW)
    assert item.state == ReviewState.EDITED and call.is_published
    assert call.allowed_entity_types == []  # two hard criteria on entity_type: interpreter only
    s.close()


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"quote": "текст што не стои во документот"}, "не е пронајден дословно"),
        ({"kind": "hard_structured", "field": "", "operator": ""}, "field and an operator"),
        (
            {"kind": "hard_structured", "field": "headcount", "operator": "in", "values": "5"},
            "only these operators",
        ),  # noqa: E501
        (
            {"kind": "soft_scored", "field": "headcount", "operator": "gte", "minimum": "5"},
            "carries no field",
        ),  # noqa: E501
        (
            {
                "kind": "hard_structured",
                "field": "age_months",
                "operator": "gte",
                "minimum": "дванаесет",
            },
            "не е валиден",
        ),  # noqa: E501
    ],
)
def test_an_edit_that_would_break_the_contract_is_refused_and_changes_nothing(
    sessions,  # noqa: F811
    written,
    changes,
    message,
):
    s, item, call = load(sessions, written)
    target = next(c for c in criteria(s, call) if c.kind == CriterionKind.APPLICANT_ATTEST)
    before = review._criterion_state(target)

    with pytest.raises(review.ReviewError, match=message):
        review.edit_criterion(s, item, target.id, form_from(target, **changes), now=NOW)

    assert review._criterion_state(target) == before
    assert not (item.corrected_payload or {}).get("edits")
    s.close()


def test_removing_a_criterion_is_recorded(sessions, written):  # noqa: F811
    s, item, call = load(sessions, written)
    target = criteria(s, call)[-1]

    review.remove_criterion(s, item, target.id, now=NOW)
    s.flush()

    assert s.get(EligibilityCriterion, target.id) is None
    assert item.corrected_payload["edits"][0]["after"] is None
    s.close()


def test_title_and_deadline_can_be_corrected(sessions, written):  # noqa: F811
    s, item, call = load(sessions, written)

    review.edit_call(
        s, item, title_mk="  Практикантство   2026 ", deadline_date="31.08.2026",
        deadline_time="", tz=TZ, now=NOW,
    )  # fmt: skip
    assert call.title_mk == "Практикантство 2026"
    assert call.deadline_at == dt.datetime(2026, 8, 31, 23, 59, 59, tzinfo=TZ)

    review.edit_call(
        s, item, title_mk="Практикантство 2026", deadline_date="31.08.2026",
        deadline_time="16:00", tz=TZ, now=NOW,
    )  # fmt: skip
    assert call.deadline_at == dt.datetime(2026, 8, 31, 16, 0, tzinfo=TZ)
    assert len(item.corrected_payload["edits"]) == 2

    for date, time in (("2026-08-31", ""), ("31.08.2026", "4pm"), ("", "16:00")):
        with pytest.raises(review.ReviewError, match="дд.мм.гггг"):
            review.edit_call(
                s, item, title_mk="x", deadline_date=date, deadline_time=time, tz=TZ, now=NOW
            )
    with pytest.raises(review.ReviewError, match="празен"):
        review.edit_call(s, item, title_mk=" ", deadline_date="", deadline_time="", tz=TZ, now=NOW)
    s.close()


def test_a_document_that_changed_again_is_decided_on_its_newest_item(
    sessions,  # noqa: F811
    store,  # noqa: F811
    site,
    written,
):
    site.change_text(819, "до 21.08.2026 година", "до 28.08.2026 година")
    reply = (
        cassette("av-measure-819")
        .replace("21.08.2026", "28.08.2026")
        .replace("2026-08-21", "2026-08-28")
    )
    changed = run(sessions, store, site, ScriptedProvider(reply))
    assert [p.outcome for p in changed.processed] == [pipeline.UPDATED]

    s = sessions()
    old = s.get(ReviewQueueItem, written.review_item_id)
    new = s.get(ReviewQueueItem, changed.processed[0].review_item_id)
    assert review.superseded_by(s, old) == new.id
    assert any(str(new.id) in p for p in review.approval_problems(s, old))

    review.approve_call(s, new, note=None, now=NOW)
    assert old.state == ReviewState.REJECTED and f"ставка {new.id}" in old.reviewer_note
    assert s.get(Call, written.call_id).is_published
    s.close()


def test_items_without_a_call_can_only_be_closed(sessions, store, site):  # noqa: F811
    invented = cassette("av-measure-819").replace("се од приватен", "се од измислен")
    result = run(sessions, store, site, ScriptedProvider(invented))
    [processed] = result.processed
    assert processed.outcome == pipeline.REVIEW

    s = sessions()
    item = s.get(ReviewQueueItem, processed.review_item_id)
    assert review.stage_of(item) == review.EXTRACT
    assert review.approval_problems(s, item) == [
        "Оваа ставка нема повик за објавување; може само да се затвори."
    ]
    review.close(s, item, note="цитатот е измислен", now=NOW)
    assert item.state == ReviewState.REJECTED
    s.close()


# -- the screens --------------------------------------------------------------------------


@pytest.fixture
def admin(sessions, monkeypatch):  # noqa: F811
    app = create_app(load_settings(env="testing", secret_key="test"))
    monkeypatch.setattr("app.web.admin._sessions", lambda: sessions)
    return app.test_client()


def csrf(client, path) -> str:
    page = client.get(path).get_data(as_text=True)
    return re.search(r'name="csrf" value="([^"]+)"', page).group(1)


def test_the_queue_and_the_item_show_each_quote_where_the_snapshot_has_it(admin, written):
    queue = admin.get("/admin/").get_data(as_text=True)
    assert "Практикантство" in queue and f"/admin/stavka/{written.review_item_id}" in queue

    page = admin.get(f"/admin/stavka/{written.review_item_id}")
    html = page.get_data(as_text=True)
    assert page.status_code == 200
    assert "<mark>се од приватен и од граѓански сектор;</mark>" in html
    assert "Цитатот стои дословно во документот" in html
    assert "Последна проверка" in html and 'class="deadline">21.08.2026' in html
    assert (
        "Прифати и објави</button>" in html
        and "disabled" not in html.split("Прифати и објави")[0][-120:]
    )


def test_a_post_without_the_csrf_token_changes_nothing(admin, sessions, written):  # noqa: F811
    path = f"/admin/stavka/{written.review_item_id}/prifati"
    assert admin.post(path, data={"note": ""}).status_code == 400
    assert admin.post(path, data={"csrf": "guess"}).status_code == 400
    with sessions() as s:
        assert not s.get(Call, written.call_id).is_published


def test_approving_through_the_screen_publishes(admin, sessions, written):  # noqa: F811
    token = csrf(admin, f"/admin/stavka/{written.review_item_id}")

    response = admin.post(f"/admin/stavka/{written.review_item_id}/prifati", data={"csrf": token})

    assert response.status_code == 302 and response.location.endswith("/admin/")
    assert "е објавен" in admin.get("/admin/").get_data(as_text=True)
    with sessions() as s:
        assert s.get(Call, written.call_id).is_published


def test_a_refused_edit_is_shown_with_what_was_typed(admin, sessions, written):  # noqa: F811
    path = f"/admin/stavka/{written.review_item_id}"
    token = csrf(admin, path)
    with sessions() as s:
        target = s.scalars(
            select(EligibilityCriterion).where(EligibilityCriterion.call_id == written.call_id)
        ).first()

    response = admin.post(
        f"{path}/uslov/{target.id}",
        data={"csrf": token, "kind": "narrative_verify", "label_mk": "Нов опис",
              "quote": "нема го во документот"},
    )  # fmt: skip

    html = response.get_data(as_text=True)
    assert response.status_code == 422
    assert "Не е зачувано." in html and "не е пронајден дословно" in html
    assert "нема го во документот</textarea>" in html
    assert f'id="uslov-{target.id}"' in html


def test_an_unknown_item_or_criterion_is_a_404(admin, written):
    assert admin.get("/admin/stavka/999999999").status_code == 404
    token = csrf(admin, f"/admin/stavka/{written.review_item_id}")
    response = admin.post(
        f"/admin/stavka/{written.review_item_id}/uslov/{uuid.uuid4()}/otstrani",
        data={"csrf": token},
    )
    assert response.status_code == 422
    assert "не припаѓа на овој повик" in response.get_data(as_text=True)


def test_the_admin_does_not_exist_in_production():
    app = create_app(load_settings(env="production", secret_key="x"))
    assert app.test_client().get("/admin/").status_code == 404


def test_snapshot_text_in_a_context_passage_is_escaped_and_blank_lines_collapse():
    from app.web.admin import _in_context

    text = "пред\n\n\n<script>alert(1)</script> цитат & крај\n\nпотоа"
    start = text.index("<script>")
    html = str(_in_context(text, start, start + len("<script>alert(1)</script> цитат"), radius=10))

    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "<mark>&lt;script&gt;alert(1)&lt;/script&gt; цитат</mark>" in html
    assert "\n\n" not in html


def test_ocr_text_is_marked_on_each_quote_and_a_doubtful_read_is_not_called_unreadable(
    admin,
    sessions,  # noqa: F811
    written,
):
    from app.models.enums import ReviewKind, TextSource
    from app.web.admin import READ_WITH_DOUBT

    with sessions() as s:
        call = s.get(Call, written.call_id)
        snapshot = s.get(RawSnapshot, call.primary_snapshot_id)
        snapshot.text_source = TextSource.OCR
        snapshot.ocr_mean_confidence = 71
        doubt = ReviewQueueItem(
            kind=ReviewKind.EXTRACTION,
            reason=f"normalising snapshot {snapshot.id} needs a human",
            payload={"stage": "normalise", "snapshot_id": snapshot.id, "url": snapshot.url,
                     "reasons": ["page 1: OCR confidence 67 is below 85"]},
        )  # fmt: skip
        s.add(doubt)
        s.commit()
        doubt_id = doubt.id

    html = admin.get(f"/admin/stavka/{written.review_item_id}").get_data(as_text=True)
    assert "Текстот е прочитан со OCR</strong>, сигурност 71" in html

    assert READ_WITH_DOUBT in admin.get("/admin/").get_data(as_text=True)
    assert READ_WITH_DOUBT in admin.get(f"/admin/stavka/{doubt_id}").get_data(as_text=True)


# -- text an older normaliser wrote -------------------------------------------------------


def age_the_text(sessions, written, version="2026-09-13.1+tesseract-5.3.4", source=None):  # noqa: F811
    from app.models.enums import TextSource

    with sessions() as s:
        call = s.get(Call, written.call_id)
        snapshot = s.get(RawSnapshot, call.primary_snapshot_id)
        snapshot.normaliser_version = version
        snapshot.text_source = TextSource.OCR if source is None else source
        s.commit()
        return snapshot.url


@pytest.mark.usefixtures("store")
def test_a_document_read_before_the_repairs_is_flagged_to_the_reviewer(sessions, written):  # noqa: F811
    """The citation check cannot see this: the quote is verbatim against wrong text."""
    url = age_the_text(sessions, written)

    with sessions() as s:
        [notice] = review.stale_text_notices(s, s.get(Call, written.call_id))

    assert notice.url == url
    assert notice.version == "2026-09-13.1" and notice.current == NORMALISER_VERSION
    assert "755" in notice.text and "не се на македонски" in notice.text  # both repairs
    assert "Проверете го цитатот" in notice.text


@pytest.mark.usefixtures("store")
def test_only_the_repairs_the_text_predates_are_named(sessions, written):  # noqa: F811
    age_the_text(sessions, written, version="2026-09-21.1+tesseract-5.3.4")

    with sessions() as s:
        [notice] = review.stale_text_notices(s, s.get(Call, written.call_id))

    assert "755" not in notice.text  # the percent repair is already in this text
    assert "не се на македонски" in notice.text


@pytest.mark.usefixtures("store")
def test_current_text_raises_no_notice(sessions, written):  # noqa: F811
    with sessions() as s:
        assert review.stale_text_notices(s, s.get(Call, written.call_id)) == []


@pytest.mark.usefixtures("store")
def test_old_text_with_a_layer_raises_no_notice(sessions, written):  # noqa: F811
    """Both repairs are OCR-only. Warning about a DOCX would train the reviewer to skim."""
    from app.models.enums import TextSource

    age_the_text(sessions, written, source=TextSource.NATIVE)

    with sessions() as s:
        assert review.stale_text_notices(s, s.get(Call, written.call_id)) == []


@pytest.mark.usefixtures("store")
def test_the_warning_does_not_block_approval(sessions, written):  # noqa: F811
    """A block the reviewer cannot clear teaches them to stop reading the notices.

    There is no re-normalisation path: the remedy is to delete the snapshot and
    re-fetch, which is `flask ingest stale-text` and its own decision.
    """
    age_the_text(sessions, written)

    with sessions() as s:
        item = s.get(ReviewQueueItem, written.review_item_id)
        assert review.approval_problems(s, item) == []


@pytest.mark.usefixtures("store")
def test_the_reviewer_sees_the_warning_on_the_item(admin, sessions, written):  # noqa: F811
    age_the_text(sessions, written)

    html = admin.get(f"/admin/stavka/{written.review_item_id}").get_data(as_text=True)

    assert "Текстот е прочитан со постара верзија." in html
    assert "Прифати и објави</button>" in html  # still approvable
