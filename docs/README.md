# Docs index — P0 planning output

These documents are the output of the P0 planning phase defined in `PROJECT_BRIEF.md` §13.
No implementation code exists yet. Read them in this order.

| # | File | Read it for |
|---|------|-------------|
| 1 | [architecture.md](architecture.md) | System shape, components, data flow, deployment, and every point where I disagree with the brief |
| 2 | [schema.sql](schema.sql) | Draft DDL with per-table rationale |
| 3 | [sources.md](sources.md) | The ingestion matrix and which sources to build first |
| 4 | [matching.md](matching.md) | The matching algorithm, confidence taxonomy, evaluation harness |
| 5 | [roadmap.md](roadmap.md) | P0.5–P6 tasks sized in evening-sessions with acceptance criteria |
| 6 | [risks.md](risks.md) | Completed risk register with the cheapest test that reveals each risk |
| 7 | [decisions.md](decisions.md) | **Open questions only you can answer.** Start here if you only read one file |
| 8 | [repo-skeleton.md](repo-skeleton.md) | Proposed repository tree |
|   | [../CLAUDE.md](../CLAUDE.md) | Standing instructions for future Claude Code sessions |

## Status

- Written: 2026-09-12
- Phase: P0 complete pending your review
- Next: P0.5 (foundation + first production deploy) — see [roadmap.md](roadmap.md)
- Verified: `schema.sql` applies cleanly to PostgreSQL 16 + pgvector (28 tables, 10 enums, 27
  indexes), and the "no citation, no claim" check constraint was tested and rejects an approved
  criterion with no citation

## Two things that need your input before P1 starts

1. **[decisions.md](decisions.md)** — pricing, brand, which programmes to template. I have given a
   recommendation and the consequence of each option, but these are yours.
2. **[sources.md](sources.md)** — every access-method claim is marked `UNVERIFIED`. Session 1 of P1
   is reconnaissance to confirm them. You know these institutions; if a cadence assumption looks
   wrong, say so now rather than after a scraper is built against it.
