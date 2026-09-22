"""Publish the five frozen evaluation calls in the DEVELOPMENT database. Refuses production.

`/povici` shows published calls only, and nothing real has been approved in the dev
database yet, so the page would always be empty. This writes the calls from
`evals/fixtures/` the way the harness does (`evals.harness.load_registry`: the same
columns, the same approved criteria citing a stored snapshot) and commits them.

    PYTHONPATH=. uv run python ops/dev/seed_shortlist.py

Like the harness, it first **deletes every published call**,
so run it only on a database whose published calls are disposable — which, until
production ingests anything (D11), is every development database. Re-running
replaces the five calls.

Their deadlines are the calls' real ones (2026), so which of them are still open
depends on the day it is run.
"""

from app.config import load_settings
from app.db import session_factory
from evals import harness


def main() -> None:
    settings = load_settings()
    if settings.is_production:
        raise SystemExit("refusing to seed a production database")
    with session_factory(settings)() as session:
        calls = harness.load_registry(session, harness.load_fixtures())
        session.commit()
    for slug, call in calls.items():
        print(f"{slug}: published, deadline {call.deadline_at or 'none'}")


if __name__ == "__main__":
    main()
