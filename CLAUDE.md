# CLAUDE.md

Standing instructions for Claude Code sessions on this repository.
Read `PROJECT_BRIEF.md` for intent and `docs/` for design. This file is the short version of the
rules that must never be broken.

---

## What this is

A grant and subsidy matching platform for North Macedonia. A company enters a profile, gets a cited
shortlist of funding calls it can realistically apply for, and can buy a verified deep report and
prepared application documents.

Operated by **one person**, evenings and weekends, for years. Every suggestion should be weighed
against that: boring and documented beats clever. If a change adds a moving part, justify it.

---

## The five invariants

Violating any of these is a bug, regardless of how well the code works.

1. **The model never decides eligibility.** Only `app/matching/hard_filter.py`, evaluating
   `kind='hard_structured'` criteria over structured profile fields, may produce `not_eligible`.
   The model returns `satisfied` / `not_satisfied` / `unclear`; `app/matching/taxonomy.py` maps those
   to the user-facing verdict, and a model's `not_satisfied` maps to **`needs_verification`**.
2. **No citation, no claim.** Every eligibility statement shown to a user carries
   `(snapshot_id, char_start, char_end)` plus source URL and retrieval date. A quote must be found
   **verbatim** in the chunk it cites — checked in code, not trusted.
3. **Absence of evidence downgrades, never upgrades.** Missing profile data, low confidence, failed
   retrieval, unverifiable citation — all terminate in `needs_verification`. There is no path from
   uncertainty to `eligible`.
4. **No identity data reaches a model.** `app/ai/gateway.py` is the only module permitted to contact a
   provider, and it scrubs first. The model receives the *shape* of an applicant — NACE, size band,
   region code, age band, investment band — never names, EMBS/EDB, addresses, phones or emails.
5. **Unvalidated model output is never published.** Every call declares a Pydantic schema. Invalid →
   one retry → review queue. Never a fallback that guesses.

---

## Language and formatting

- **Macedonian Cyrillic is the launch language** and must be correct, with proper domain terminology.
  Machine-mangled Macedonian in front of a customer is a product failure, not a rough edge.
- Any AI-produced Macedonian passes human review before reaching a customer. Same rule will apply to
  Albanian, which additionally needs a named reviewer before it ships at all (`docs/decisions.md` D7).
- Dates are **`dd.mm.yyyy`**. Currency is **МКД** and **EUR**. Never USD, never `mm/dd`.
- UI is Macedonian-first with i18n scaffolding in place from day one (`mk`, then `sq`, `en`, `tr`).

## Words that must never appear in customer-facing output

`гарантирано` · "guaranteed" · "approved" · "you will receive", and their Macedonian and Albanian
equivalents. Enforced by a lint in the report pipeline. If you are adding output copy, assume the lint
is right and you are wrong.

---

## Working rules

- **Prompts are versioned files** in `prompts/<task>/<version>.md`. Never an inline string. Changing a
  prompt means a new version file and an evaluation run.
- **Scoring weights live in `config/weights/<version>.yaml`.** Never hardcoded. The version used is
  recorded on every `match_run` so any delivered report is reproducible.
- **Reference data (NACE, municipalities, regions) is versioned files in `data/`,** not rows edited in
  production. A reclassification must show up in a diff.
- **Never hand-edit `docs/schema.sql`.** Change the models, autogenerate a migration, then run
  `./ops/dump-schema.sh`. Two check constraints carry the accuracy contract into the database
  (`has_citation`, `structured_has_predicate`) — do not drop them to make a test pass.
- **Adding an ingestion source touches only `app/ingestion/sources/` and `config/sources.yaml`.** If it
  forces changes elsewhere, say so — the abstraction is wrong and that is worth knowing.
- **Content-hash everything fetched.** Re-analysing an unchanged document is pure waste and the main
  cost control in the system.
- **Crawl honestly.** Real User-Agent with contact details, `robots.txt` respected, ~0.2 req/s per
  host. There is no scenario where crawling a ministry faster is worth the phone call.
- **Store the raw snapshot even when parsing fails** — especially then.
- **The review queue is the destination for all uncertainty.** The correct response to an ambiguous
  case is a human, never a guess and never a silent drop.

---

## Stack

Python 3.12 · Flask + Jinja2 + HTMX (no SPA) · PostgreSQL 16 + pgvector + pg_trgm · SQLAlchemy +
Alembic · cron → RQ + Redis · Pydantic v2 for all model output · WeasyPrint and docxtpl for documents
· Docker Compose + Caddy on a single EU VPS · Tailwind via the standalone binary (no Node in this
project) · `uv`, `ruff`, `pytest`.

**No Playwright in the main image.** If a source needs a browser, it is disqualified from the first
six and later arrives as a separate scheduled container (`docs/architecture.md` §9.4).

---

## Before you finish a change

- Does it keep the five invariants above?
- Does any new customer-facing statement carry a citation?
- Does the evaluation harness still pass? **A false `eligible` is zero-tolerance and blocks deploy.**
- Does anything new leave the EU, or reach a model provider unscrubbed?
- Would the author of this repo be able to debug it alone, on a weeknight, in a year?

---

## Where things are

| Question | File |
|---|---|
| Why is it built this way? | `docs/architecture.md` (§9 lists disagreements with the brief) |
| What does the data look like? | `app/models/` is the truth; `docs/schema.sql` is generated |
| Why is the schema shaped that way? | `docs/data-model.md` |
| Where do calls come from? | `docs/sources.md` |
| How does matching work? | `docs/matching.md` |
| Where did the last session stop? What was learned? | `docs/handoff.md` — **read first when resuming**, update at the end of every session |
| What am I building next? | `docs/roadmap.md` |
| What could go wrong? | `docs/risks.md` |
| What is still undecided? | `docs/decisions.md` |
| How do I restore the database? | `docs/runbook.md` |

## UI work
Read .claude/skills/design-system before any frontend change.
After implementing UI: run the dev server, use chrome-devtools to screenshot
at 375/768/1440, check the console, fix, re-screenshot. Do not report done
before the visual check.