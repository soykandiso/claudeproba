"""Put a composed report draft in the DEVELOPMENT review queue. Refuses production.

`/admin/izveshtaj/<id>` (P2 s33) reviews a report, and nothing writes one in the dev
database: there is no model key and no order flow yet. This runs the real path over
the five frozen evaluation calls without a model:

1. publishes the frozen calls, as `seed_shortlist.py` does (and, like it, **deletes
   every other published call first**);
2. stores an evaluation profile as an `applicant_profile` row;
3. `deep.run` verifies its top five with tier B's recorded answers (`evals/cassettes/verify/`);
4. `compose.compose` drafts the report with scripted prose below instead of a model,
   every statement citing the conditions of its own call.

    PYTHONPATH=. uv run python ops/dev/seed_report.py [--profile p02_bitola_bakery_small]
        [--blocked]

`--blocked` puts "гарантирано" in the summary, so the draft is queued blocked and
the screen can be seen refusing it. The prose is placeholder Macedonian, written to
pass the checks, not to be read as advice; a real draft comes from `compose_report`.
"""

import argparse
import datetime as dt
import json

from app.ai.gateway import Gateway, ProviderReply
from app.config import load_settings
from app.db import session_factory
from app.matching import deep, normalise
from app.models import Account
from app.reports import compose
from evals import harness, tier_b


class Uncached(Gateway):
    """The gateway without its cache, for the scripted prose only: the same run's
    prompt is the same input, so a second seed would otherwise replay the first
    draft whatever `--blocked` says. Nothing is deleted from the audit rows."""

    def _from_cache(self, *args, **kwargs):
        return None


class ScriptedProse:
    """Answers the one `compose_report` request with prose built from the draft."""

    def __init__(self, blocked: bool):
        self.blocked = blocked
        self.refs: list[list[str]] = []

    def complete(self, request) -> ProviderReply:
        summary = (
            "Финансирањето е гарантирано за барател со овој профил."
            if self.blocked
            else "Прегледани се условите на повиците според нивниот текст и одговорите во профилот."
        )
        prose = {
            "summary": [{"text_mk": summary, "cites": [r[0] for r in self.refs if r][:8]}],
            "calls": [
                {
                    "call": n,
                    "explanation": [
                        {
                            "text_mk": "Овие услови се прочитани од текстот на повикот; оние што "
                            "треба да се проверат се наведени подолу со нивниот цитат.",
                            "cites": refs[i : i + 8],
                        }
                        for i in range(0, len(refs), 8)
                    ],
                    "next_steps": [
                        {
                            "text_mk": "Пред да аплицирате, побарајте од институцијата потврда "
                            "за условите што треба да се проверат.",
                            "cites": refs[:1],
                        }
                    ],
                }
                for n, refs in enumerate(self.refs, 1)
            ],
        }
        return ProviderReply(
            text=json.dumps(prose, ensure_ascii=False),
            stop_reason="end_turn",
            input_tokens=0,
            output_tokens=0,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", default="p02_bitola_bakery_small")
    parser.add_argument("--blocked", action="store_true")
    args = parser.parse_args()

    settings = load_settings()
    if settings.is_production:
        raise SystemExit("refusing to seed a production database")
    factory = session_factory(settings)
    fixtures = harness.load_fixtures()
    as_of = dt.datetime.combine(harness.load_suite()["as_of"], dt.time(12), dt.UTC)

    with factory() as s:
        calls = harness.load_registry(s, fixtures)
        account = Account(email=f"seed-{dt.datetime.now().timestamp()}@example.invalid")
        s.add(account)
        s.flush()
        answers = harness.load_profiles()[args.profile].answers
        row = normalise.to_row(normalise.normalise(answers, as_of.date()), account.id)
        s.add(row)
        s.commit()
        profile_id = row.id

    slug_of = {call.id: slug for slug, call in calls.items()}
    provider = tier_b.CassetteProvider(tier_b.load_cassettes(), profile=args.profile)
    fixture_retriever = tier_b.FixtureRetriever(
        {call.id: (call.primary_snapshot_id, fixtures[slug].text) for slug, call in calls.items()}
    )

    def retriever_for(session):
        def retrieve(call, criterion):
            provider.call = slug_of[call.id]
            return fixture_retriever(call, criterion)

        return retrieve

    report = deep.run(factory, Gateway(factory, provider), retriever_for, profile_id, as_of)

    prose = ScriptedProse(args.blocked)
    with factory() as s:
        draft = compose.load(s, report.match_run_id)
    prose.refs = [[c["ref"] for c in call["conditions"]] for call in draft["calls"]]
    item_id = compose.compose(factory, Uncached(factory, prose), report.match_run_id)
    print(f"report review item {item_id}: http://localhost:8080/admin/izveshtaj/{item_id}")


if __name__ == "__main__":
    main()
