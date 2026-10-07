"""The P3 audit (roadmap s47): "every page states last_verified_at", held by a test.

The brief's promise (§12): a screen that shows a call says when it was last checked. P3 added
three such screens (the landing's example, the archive's programme and call pages); this checks
them with the two that came before (the shortlist and the passage).
"""

import datetime as dt

from sqlalchemy import select

from app.matching import shortlist
from app.models import EligibilityCriterion
from app.web import public
from tests.test_archive import _slug
from tests.test_archive import served as served  # noqa: F401 (fixture)
from tests.test_shortlist import FITS, db, make_call, registry, with_profile  # noqa: F401

CHECKED = dt.datetime(2026, 9, 28, 8, tzinfo=dt.UTC)


@db
def test_every_screen_showing_a_call_says_when_it_was_last_checked(client, served, monkeypatch):  # noqa: F811
    factory, source, snapshot = served
    with factory() as s:
        call = make_call(s, source, snapshot, title="Проверен повик", criteria=[FITS])
        call.last_verified_at = CHECKED
        s.commit()
        slug = _slug(s, call)
        criterion_id = s.scalar(
            select(EligibilityCriterion.id).where(EligibilityCriterion.call_id == call.id)
        )
    monkeypatch.setattr(shortlist, "SAMPLE_LENGTH", (1, 240))
    monkeypatch.setattr(public, "session_factory", lambda _settings: factory)
    with_profile(client)

    screens = {
        "the landing's example": "/",
        "the shortlist": "/povici/",
        "a passage": f"/povici/izvor/{criterion_id}",
        "an archive call": f"/arhiva/{slug}/{call.id}",
        "an archive programme": f"/arhiva/{slug}/",
    }
    for name, path in screens.items():
        page = client.get(path).get_data(as_text=True)
        assert "Проверен повик" in page, name
        assert "28.09.2026" in page, name
        assert "оследна проверка" in page, name  # «Последна проверка» or «последна проверка»
