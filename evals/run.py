"""Run the evaluation harness. Tier A today; B is P2 s29, C is P2 s36.

    PYTHONPATH=. uv run python evals/run.py              # the gate
    PYTHONPATH=. uv run python evals/run.py --worksheet  # the case files to fill in

Exit code 0 means the gate passed and this code may be deployed; 1 means it did
not. **It is 1 today, on purpose**: there are no expected verdicts yet, and an
empty suite proves nothing (roadmap P2 s25 → s26).

The suite runs inside a transaction that is rolled back, over the development
database, and it refuses to touch a production one: `load_registry` deletes the
published calls so the frozen ones are the whole registry, which is correct for a
measurement and catastrophic anywhere else.
"""

import argparse
import sys
from pathlib import Path
from textwrap import wrap

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import load_settings
from app.matching import intake
from evals import harness

ROOT = Path(__file__).resolve().parent


QUOTE_LIMIT = 400


def quote_words(quote: str) -> str:
    """One criterion's quote on the page, whitespace flattened and very long cut."""
    said = " ".join((quote or "").split())
    if len(said) > QUOTE_LIMIT:
        said = said[:QUOTE_LIMIT].rsplit(" ", 1)[0] + " …"
    return f"„{said}“"


def worksheet() -> int:
    """Write the case files for the user's evening (roadmap P2 s26).

    One file per call, one blank row per profile, and everything needed to decide
    in the comments: what the call requires, and what the applicant answered. The
    system's own verdict is deliberately **not** shown. The whole value of these
    forty lines is that they were written by someone reading the call, and a
    number already on the page is the fastest way to stop reading.
    """
    suite = harness.load_suite()
    profiles, fixtures = harness.load_profiles(), harness.load_fixtures()
    harness.CASES.mkdir(parents=True, exist_ok=True)
    written = 0

    for slug, roster in suite["worksheet"].items():
        fixture = fixtures[slug]
        keys = list(profiles) if roster == "all" else list(roster)
        path = harness.CASES / f"{slug}.yaml"
        existing = harness.load_cases(profiles, {slug: fixture})[0] if path.exists() else []
        if existing:
            print(f"{path.name}: {len(existing)} answered row(s) already — left alone")
            continue

        # dd.mm.yyyy, like everything else a person reads here (CLAUDE.md).
        deadline = fixture.data["deadline_at"]
        deadline = f"{deadline:%d.%m.%Y}" if deadline else "нема"
        lines = [
            f"# {fixture.title}",
            f"# {fixture.data['institution']} · {fixture.data['canonical_url']}",
            f"# Рок: {deadline} · состојба: {fixture.data['status']}",
        ]
        if fixture.data["eligibility_gap"]:
            lines.append(f"# Празнина: {fixture.data['eligibility_gap']}")
        lines.append(f"# Целиот текст: evals/fixtures/{slug}/document.txt")
        lines.append("#")
        # The call's own sentences, not only our labels: the judgement in a case is
        # supposed to come from reading the call, and nobody should have to open a
        # PDF to do it. A long quote is cut, and the document is there in full.
        lines.append("# Условите на повикот, онака како се одобрени, со неговите зборови:")
        for criterion in fixture.criteria:
            lines.append(f"#   [{criterion['kind']}] {criterion['label_mk']}")
            for part in wrap(quote_words(criterion["quote"]), width=88):
                lines.append(f"#       {part}")
        lines += [
            "#",
            "# За секој профил впишете еден од: eligible, likely_eligible,",
            "# needs_verification, not_eligible, not_shown — и една реченица зошто.",
            "# Се пишува вистинскиот одговор, не она што системот денес го кажува.",
            "",
            f"call: {slug}",
            "cases:",
        ]
        for key in keys:
            case_profile = profiles[key]
            profile = case_profile.profile(suite["as_of"])
            lines.append(f"  # {case_profile.name}")
            for label, value in intake.describe(profile):
                lines.append(f"  #   {label}: {value if value else '—'}")
            lines += [f"  - profile: {key}", "    expect:", '    reason: ""', ""]
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        print(f"{path.name}: {len(keys)} row(s) to fill in")
        written += len(keys)
    print(f"\n{written} blank case(s) written to evals/cases/")
    return 0


def gate() -> int:
    settings = load_settings()
    if settings.is_production:
        raise SystemExit("refusing to run the harness against a production database")
    engine = create_engine(settings.sqlalchemy_url)
    connection = engine.connect()
    transaction = connection.begin()
    factory = sessionmaker(bind=connection, join_transaction_mode="create_savepoint")
    try:
        with factory() as session:
            report = harness.run(session)
    finally:
        transaction.rollback()
        connection.close()
        engine.dispose()
    print(report.text())
    return 1 if report.blocking() else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--worksheet",
        action="store_true",
        help="write the blank case files instead of running the gate",
    )
    args = parser.parse_args()
    return worksheet() if args.worksheet else gate()


if __name__ == "__main__":
    sys.exit(main())
