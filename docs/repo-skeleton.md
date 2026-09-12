# Proposed repository skeleton

Shaped by one rule: **a file's location should tell you what it is allowed to do.** The accuracy
contract is enforceable only if there is exactly one place a model call can happen and exactly one
place an eligibility verdict can be produced.

```
.
├── CLAUDE.md                    standing instructions for Claude Code sessions
├── PROJECT_BRIEF.md             the original brief (unchanged, source of truth for intent)
├── README.md                    what this is, how to run it locally
├── pyproject.toml               deps via uv; ruff + pytest config
├── docker-compose.yml           caddy · web · worker · redis · postgres
├── Caddyfile
├── Dockerfile                   one image, different commands for web and worker
├── .env.example
│
├── app/
│   ├── __init__.py              Flask app factory
│   ├── config.py                env-driven settings, no secrets in code
│   ├── extensions.py            db, migrate, babel, rq
│   ├── cli.py                   flask ingest / flask eval / flask backup — what cron calls
│   │
│   ├── models/                  SQLAlchemy models — the ONLY definition of the schema
│   │   ├── registry.py          source_feed, raw_snapshot, programme, call, criterion, chunk
│   │   ├── applicant.py         account, consent_record, applicant_profile
│   │   ├── matching.py          match_run, match_result, outcome, evidence
│   │   ├── commerce.py          product, order, invoice, subscription
│   │   ├── documents.py         template, package, generated_document
│   │   └── ai.py                prompt_version, model_call, model_call_payload
│   │
│   ├── ingestion/
│   │   ├── base.py              Fetcher ABC: discover() → fetch() → snapshot()
│   │   ├── sources/             one module per source; adding a source touches ONLY this dir
│   │   │   ├── fitr.py
│   │   │   ├── eu_portal.py
│   │   │   ├── av_gov.py
│   │   │   ├── economy_gov.py
│   │   │   ├── skopje.py
│   │   │   ├── ipard.py
│   │   │   └── manual.py        admin-pasted URL, same pipeline, same citation quality
│   │   ├── normalise.py         HTML/PDF → text WITH character offsets preserved
│   │   ├── extract.py           snapshot → CallExtraction (schema-validated)
│   │   ├── chunking.py          chunk + embed changed documents only
│   │   └── health.py            staleness SLA, alerting, heartbeat ping
│   │
│   ├── matching/
│   │   ├── normalise.py         stage 0 — NACE, region, SME band
│   │   ├── hard_filter.py       stage 1 — SQL prefilter + rule interpreter
│   │   ├── operators.py         the nine allowed operators. Fixed dict, field whitelist
│   │   ├── scoring.py           stage 2 — weighted components, each returning (value, reason)
│   │   ├── verify.py            stage 3 — retrieval + model, clamping, verbatim quote check
│   │   └── taxonomy.py          the verdict enum and the ONLY code that assigns one
│   │
│   ├── ai/
│   │   ├── gateway.py           the ONLY module permitted to contact a model provider
│   │   ├── scrub.py             PII removal at the egress boundary
│   │   ├── schemas.py           Pydantic response models; invalid → review queue
│   │   ├── cache.py             content-hash keyed
│   │   └── routing.py           reads config/models.yaml
│   │
│   ├── review/                  the human gate — a feature, not a workaround
│   │   ├── queue.py
│   │   └── to_eval.py           reviewer corrections → evaluation cases
│   │
│   ├── billing/
│   │   ├── provider.py          PaymentProvider interface
│   │   ├── invoice_provider.py  v1: proforma + bank transfer, manual reconciliation
│   │   └── numbering.py         gapless per fiscal year
│   │
│   ├── documents/               P5 — docxtpl rendering, checklists, unfilled-field marking
│   ├── reports/                 composition, banned-phrase lint, WeasyPrint → PDF
│   │
│   ├── web/
│   │   ├── public/              landing, intake, shortlist, SEO archive
│   │   ├── account/             magic-link auth, saved profiles, orders
│   │   ├── admin/               review queue, source health, reconciliation
│   │   ├── templates/           Jinja2. MK-first, i18n from day one
│   │   └── static/
│   │
│   └── i18n/                    Babel catalogues: mk (launch), sq, en, tr
│
├── prompts/                     VERSIONED FILES, never inline strings (brief §7)
│   ├── extract_call/2026-09-12.1.md
│   ├── verify_criterion/2026-09-12.1.md
│   └── compose_report/2026-09-12.1.md
│
├── config/
│   ├── models.yaml              task → model tier routing
│   ├── weights/v1.yaml          scoring weights; version recorded on every match_run
│   └── sources.yaml             cadences, SLAs, rate limits
│
├── data/                        versioned reference data, NOT production rows
│   ├── nace.csv
│   ├── municipalities.csv
│   └── regions.csv
│
├── migrations/                  Alembic. The source of truth from P0.5 onward
│
├── evals/
│   ├── profiles/                applicant fixtures
│   ├── fixtures/                frozen snapshots + extracted criteria
│   ├── cases/                   expected verdicts with a human reason
│   │   └── from_review/         auto-generated from reviewer corrections
│   ├── cassettes/               recorded model responses (tier B)
│   └── run.py                   tiers A/B in CI, C weekly
│
├── tests/
│   ├── fixtures/                real page samples per source
│   ├── test_scrub.py            PII must never leave. Runs on every commit, forever
│   ├── test_operators.py
│   └── test_citations.py        every quote verbatim in its cited chunk
│
├── ops/
│   ├── backup.sh                pg_dump → age → EU object storage → heartbeat
│   ├── restore.sh               the drill, run monthly
│   └── cron.d/
│
└── docs/                        this directory
    ├── architecture.md · schema.sql · sources.md · matching.md
    ├── roadmap.md · risks.md · decisions.md · repo-skeleton.md
    ├── runbook.md               written in P0.5 s5
    ├── legal-notes.md           written in P3 s43
    └── gdpr/                    record of processing, subprocessors (P3)
```

## The three boundaries that matter

1. **`app/ai/gateway.py` is the only module that may contact a model provider.** Enforced by review
   and by a grep in CI. If a provider SDK is imported anywhere else, that is a bug regardless of what
   the code does.
2. **`app/matching/taxonomy.py` is the only module that may assign a user-facing verdict.** The model
   returns `satisfied`/`not_satisfied`/`unclear`; only this module maps those onto the enum a customer
   sees, and only `hard_filter.py` can reach `not_eligible`.
3. **Adding a source touches only `app/ingestion/sources/` and `config/sources.yaml`.** If it forces a
   change anywhere else, the abstraction is wrong — which is exactly what building FITR and the EU
   portal together in P1 is designed to surface early.
