"""How stage 1 behaves when the registry is large. Nothing is kept.

    PYTHONPATH=. uv run python ops/dev/bench_stage1.py [--calls 200,2000,20000]

`docs/handoff.md` §8 has carried an unknown since P2 s24: stage 1a's array clauses
cannot use the GIN indexes while "an empty array means no restriction" is written
as `cardinality = 0 OR overlap` (`docs/matching.md` §3), so the partial index on
open calls does the narrowing and the arrays filter whatever survives. That is
fine for hundreds of open calls and had never been measured — and an unmeasured
budget is the thing that gets blamed at P2 s28, when the shortlist has three
seconds and the registry is whatever it is by then.

This writes a synthetic registry inside a transaction it rolls back, times stage
1a and 1b separately over it, and prints the planner's own account of the query.
The shapes are deliberately unkind: two thirds of the calls are national (empty
arrays, so the overlap short-circuit does not help), and every candidate carries
criteria for the interpreter to read.
"""

import argparse
import datetime as dt
import random
import time
import uuid

from sqlalchemy import create_engine, delete, insert, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import sessionmaker

from app.config import load_settings
from app.matching import stage1
from app.matching.normalise import normalise
from app.models import Call, EligibilityCriterion, Programme, RawSnapshot, SourceFeed
from app.models.enums import AccessMethod, CallStatus, CriterionKind

TODAY = dt.date(2026, 6, 1)
NOW = dt.datetime(2026, 6, 1, 12, 0, tzinfo=dt.UTC)
SLUG = "bench-stage1"

# The applicant the timings are for: every question answered, so every clause in
# 1a is switched on. A profile that answers less is a *shorter* query.
COMPANY = {
    "entity": "dooel",
    "municipality": "MK00814",
    "founded": "2022",
    "employees": "2-9",
    "nace": "62.01",
    "turnover": "lt10",
    "amount": "1-3",
}

SECTIONS = ["A", "C", "F", "G", "J", "M"]
DIVISIONS = ["01", "10", "13", "25", "41", "47", "62", "70"]
REGIONS = [f"MK00{n}" for n in range(1, 9)]
ENTITY_SETS = [["micro"], ["micro", "small"], ["small", "medium"], ["farm"], ["ngo"]]


def registry(session, source, snapshot, count: int, rng: random.Random) -> None:
    """A synthetic open registry: national calls, sector calls, regional calls."""
    programme = Programme(
        source_feed_id=source.id,
        slug=f"bench-{uuid.uuid4()}",
        name_mk="Мерка",
        institution="Bench",
        is_singleton=False,
    )
    session.add(programme)
    session.flush()

    calls, criteria = [], []
    for index in range(count):
        shape = rng.random()
        row = {
            "id": uuid.uuid4(),
            "programme_id": programme.id,
            "source_feed_id": source.id,
            "title_mk": f"Повик {index}",
            "canonical_url": f"https://gov.example/{index}",
            "status": CallStatus.OPEN,
            "deadline_at": NOW + dt.timedelta(days=rng.randint(1, 200)),
            "is_published": True,
            "allowed_entity_types": [],
            "allowed_nace_prefixes": [],
            "allowed_regions": [],
        }
        if shape > 0.65:  # a sector call
            row["allowed_nace_prefixes"] = [rng.choice(DIVISIONS), rng.choice(SECTIONS)]
            row["allowed_entity_types"] = rng.choice(ENTITY_SETS)
        if shape > 0.85:  # a regional one
            row["allowed_regions"] = [rng.choice(REGIONS)]
        if shape > 0.9:
            row["min_company_age_months"] = rng.choice([6, 12, 24])
        calls.append(row)
        for _ in range(rng.randint(3, 8)):
            criteria.append(
                {
                    "id": uuid.uuid4(),
                    "call_id": row["id"],
                    "kind": rng.choice(
                        [
                            CriterionKind.HARD_STRUCTURED,
                            CriterionKind.APPLICANT_ATTEST,
                            CriterionKind.NARRATIVE_VERIFY,
                        ]
                    ),
                    "label_mk": "Услов",
                    "field": "entity_type",
                    "operator": "not_in",
                    "value_json": {"values": ["large"]},
                    "source_quote": "цитат",
                    "snapshot_id": snapshot.id,
                    "quote_start": 0,
                    "quote_end": 5,
                    "is_approved": True,
                }
            )
    session.execute(insert(Call), calls)
    session.execute(insert(EligibilityCriterion), criteria)
    session.execute(text("ANALYZE call"))  # the planner is judged on real statistics
    session.flush()


def timed(fn, repeat: int = 5) -> float:
    """Median of a few runs, in milliseconds. The first one warms the cache."""
    fn()
    times = []
    for _ in range(repeat):
        started = time.perf_counter()
        fn()
        times.append((time.perf_counter() - started) * 1000)
    return sorted(times)[len(times) // 2]


def run(counts: list[int]) -> None:
    settings = load_settings()
    if settings.is_production:
        raise SystemExit("refusing to benchmark against a production database")
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    profile = normalise(COMPANY, today=TODAY)

    with factory() as session:
        source = session.scalars(select(SourceFeed).where(SourceFeed.slug == SLUG)).first()
        if source is None:
            source = SourceFeed(
                slug=SLUG,
                name_mk="Bench",
                name_en="Bench",
                institution="Bench",
                base_url="https://gov.example",
                access_method=AccessMethod.HTML,
                expected_cadence=dt.timedelta(days=1),
                staleness_sla=dt.timedelta(days=7),
            )
            session.add(source)
            session.flush()
        snapshot = RawSnapshot(
            source_feed_id=source.id,
            url="https://gov.example/doc",
            content_sha256="0" * 64,
            http_status=200,
            storage_key="bench",
            normalised_text="цитат",
        )
        session.add(snapshot)
        session.execute(delete(Call).where(Call.is_published.is_(True)))
        session.flush()

        header = f"{'calls':>8} {'candidates':>11} {'ids only':>9} {'1a (ORM)':>9}"
        print(f"{header} {'criteria':>9} {'1b':>7} {'run()':>8}")
        rng = random.Random(1)
        written = 0
        for count in counts:
            registry(session, source, snapshot, count - written, rng)
            written = count
            found = stage1.candidates(session, profile, NOW)
            grouped = stage1._criteria_by_call(session, found)
            criteria = {c.id: grouped.get(c.id, []) for c in found}
            # The SQL on its own, before 13.000 rows become objects.
            ids_only = timed(
                lambda: session.execute(
                    stage1.candidate_query(profile, NOW).with_only_columns(Call.id)
                ).all()
            )
            one_a = timed(lambda: stage1.candidates(session, profile, NOW))
            load = timed(lambda found=found: stage1._criteria_by_call(session, found), repeat=3)
            one_b = timed(
                lambda found=found, criteria=criteria: [
                    stage1.judge(c, criteria[c.id], profile) for c in found
                ],
                repeat=3,
            )
            whole = timed(lambda: stage1.run(session, profile, NOW), repeat=3)
            print(
                f"{count:>8,} {len(found):>11,} {ids_only:>7.0f}ms {one_a:>7.0f}ms "
                f"{load:>7.0f}ms {one_b:>5.0f}ms {whole:>6.0f}ms"
            )

        plan = session.execute(
            text("EXPLAIN (ANALYZE, BUFFERS, SUMMARY OFF) " + _sql(profile))
        ).scalars()
        print("\nThe planner on the largest registry:")
        for line in plan:
            print(f"  {line}")

    transaction.rollback()
    connection.close()
    engine.dispose()


def _sql(profile) -> str:
    """The real stage 1a query, with its parameters written in (never user input).

    Compiled against the PostgreSQL dialect on purpose: the default one renders an
    array cast as `CAST(... AS ARRAY)`, which no server will parse.
    """
    query = stage1.candidate_query(profile, NOW)
    return str(query.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calls", default="200,2000,20000")
    args = parser.parse_args()
    run([int(n) for n in args.calls.split(",")])


if __name__ == "__main__":
    main()
