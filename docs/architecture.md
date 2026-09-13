# Architecture

> Scope: the system described in `PROJECT_BRIEF.md`, built and operated by one person over years.
> Every decision below is justified against that constraint. Where I disagree with the brief, §9 of
> this document says so explicitly and gives the reasoning.

---

## 1. Design principles

1. **Deterministic code decides; the model describes.** Eligibility verdicts come from rules over
   structured fields. The model extracts, verifies against retrieved text, and writes prose. It
   never returns a verdict that can exclude an applicant.
2. **Nothing is published without a citation.** A claim without a `(snapshot, character span)`
   reference is a bug, not a degraded experience.
3. **One box, few moving parts.** Every added service must justify itself against being debugged
   alone on a weeknight.
4. **Reproducibility over freshness.** A delivered report must be regenerable byte-for-byte from
   stored inputs, months later, after the source website has changed.
5. **Fail into the review queue.** The correct response to uncertainty is always a human, never a
   guess and never a silent drop.

---

## 2. System diagram

```
                       ┌──────────────────────────────────────────────────┐
  Official sources     │                 INGESTION                        │
  (FITR, EU F&T,       │                                                  │
   AV, MoE, IPARD,     │  cron ──► fetcher ──► snapshot store (S3)        │
   Skopje)             │            │              │                      │
        │              │            │         content hash                │
        └──────────────┼──► httpx   ▼              ▼                      │
                       │        raw bytes ──► change detector             │
                       │                           │ changed only         │
                       │                           ▼                      │
                       │                      normaliser (html/pdf→text)  │
                       │                           │                      │
                       │                           ▼                      │
                       │                   extractor (LLM gateway)        │
                       │                           │ Pydantic validate    │
                       │                     ┌─────┴─────┐                │
                       │                  valid        invalid/low-conf   │
                       │                     │             │              │
                       └─────────────────────┼─────────────┼──────────────┘
                                             ▼             ▼
                    ┌────────────────────────────────┐  ┌──────────────────┐
                    │        REGISTRY (Postgres)     │  │  REVIEW QUEUE    │
                    │  programme / call / criterion  │◄─┤  (human sign-off)│
                    │  chunk+embedding / evidence    │  └──────────────────┘
                    │  account / profile / match     │           ▲
                    │  order / invoice / model_call  │           │
                    └────────────────────────────────┘           │
                             ▲             │                     │
            ┌────────────────┘             ▼                     │
            │                  ┌───────────────────────┐         │
   ┌────────┴────────┐         │   MATCHING ENGINE     │         │
   │   WEB (Flask)   │         │  0 normalise          │         │
   │  Jinja2 + HTMX  │◄────────┤  1 hard filter  (sync)│         │
   │  MK / SQ / EN   │  <5s    │  2 score & rank (sync)│         │
   │                 │         │  3 verify (async,RQ)  ├─────────┘
   │  intake         │         └───────────┬───────────┘
   │  shortlist      │                     │ structured JSON + citations
   │  report view    │                     ▼
   │  admin/review   │         ┌───────────────────────┐      ┌───────────────┐
   └────────┬────────┘         │   REPORT RENDERER     │      │  LLM GATEWAY  │
            │                  │   WeasyPrint → PDF    │◄────►│ routing/cache │
            ▼                  └───────────────────────┘      │ schema/audit  │
   ┌─────────────────┐         ┌───────────────────────┐      │ cost logging  │
   │  BILLING        │         │  DOCUMENT PACKAGES    │      │ PII scrubber  │
   │  proforma→PDF   │         │  docxtpl → .docx/.pdf │      └───────┬───────┘
   │  manual recon   │         └───────────────────────┘              │
   └────────┬────────┘                                                ▼
            │                                              model provider API
            ▼                                               (pseudonymised)
      email (transactional)
```

---

## 3. Component responsibilities

### 3.1 Ingestion

| Component | Responsibility | Notes |
|---|---|---|
| **Scheduler** | Host `cron` fires `flask ingest run --source=<slug>` on each source's cadence | Cron, not an in-process scheduler. It survives app restarts and is inspectable with `crontab -l`. |
| **Fetcher** | One small class per source. HTTP via `httpx` with an honest User-Agent (`grantbot/1.0 (+https://<domain>/crawler; contact@<domain>)`), per-source rate limit, `robots.txt` respected | No browser in P1. See §9.4. |
| **Snapshot store** | Writes raw bytes once under `snapshots/<source>/<sha256>` on a Docker volume, copied off-site nightly by `ops/backup.sh` with the same `rclone` remote as the database backups; records hash, URL, HTTP status, byte length, `fetched_at` and `last_seen_at` in Postgres | Bytes out of the database keeps nightly dumps small and restores fast. A directory rather than an S3 API: content-addressed files never change, so an incremental copy gives the same off-site guarantee without an S3 client or a MinIO container. |
| **Change detector** | Compares content hash to the last snapshot for that URL. Unchanged → stop, costs nothing | This is the single biggest cost control in the system. |
| **Normaliser** | HTML → text (`selectolax`), DOCX → text (standard library), PDF → text (`pypdf` text layer per page, Tesseract `mkd` for pages without one — `decisions.md` D9). Pages separated by `\f`. Written once per snapshot and never rewritten | Citations index into this text by offset, so it must be faithful (inline markup joins without spaces), deterministic, and immutable once cited. `pdfplumber` for tables waits for IPARD (P1 s20). |
| **Extractor** | LLM gateway call producing a `CallExtraction` Pydantic model: dates, budget, eligibility criteria, required documents | Schema failure → retry once → review queue. Never published unvalidated. |
| **Chunker + embedder** | Splits normalised text into overlapping chunks with offsets; embeds each; writes to `chunk` with a `vector` column | Only on changed documents. |
| **Health monitor** | Per-source freshness SLA. A source that returns nothing new past its expected cadence raises an alert | A silently dead scraper is the primary business failure mode (`risks.md` R1). |

### 3.2 Registry

PostgreSQL 16 with `pgvector` and `pg_trgm`. Single database, no sharding, no read replica. Sized for
tens of thousands of documents, per §3.5 of the brief. See `schema.sql`.

### 3.3 Matching engine

Four stages, detailed in `matching.md`. Stages 0–2 run synchronously inside the web request and must
complete in under 5 seconds; stages 3–4 run on the RQ worker and finish in minutes, with delivery
gated on human review.

### 3.4 LLM gateway

The **only** code path permitted to contact a model provider. Responsibilities:

- **PII scrubbing at the boundary.** Names, EMBS/EDB, addresses, phone numbers and emails are
  stripped or replaced with stable pseudonyms before prompt construction. Enforced by a unit test
  that asserts outgoing payloads match no PII pattern (`risks.md` R5).
- **Routing by task.** Cheap tier for extraction, classification, chunk relevance. Strong tier only
  for customer-facing Macedonian prose. Configured in `config/models.yaml`, not in code.
- **Strict schema validation.** Every call declares a Pydantic response model. Invalid → one retry
  with the validation error appended → then fail into the review queue. Never publish unvalidated.
- **Content-hash caching.** Key = `sha256(prompt_version + model + input_text_hash)`. Re-analysing an
  unchanged call is free.
- **Audit + cost.** Every call writes a `model_call` row: prompt version, model, token counts, cost,
  latency, outcome. This is how you find out a feature is expensive before the invoice does.
- **Prompts as files.** `prompts/<task>/<version>.md`, referenced by version. Never inline strings.

### 3.5 Web

Flask + Jinja2 + HTMX. Server-rendered. Blueprints: `public` (landing, intake, shortlist, SEO
archive), `account` (magic-link auth, saved profiles, orders), `admin` (review queue, source health,
invoice reconciliation). Macedonian Cyrillic is the launch language; the i18n scaffolding (Babel,
`_()` everywhere, locale-aware date and money formatting) is built from day one so Albanian and
English are content work, not refactoring.

### 3.6 Billing

`PaymentProvider` interface with a single `InvoiceProvider` implementation in v1: generate a proforma
PDF, email it, wait for a bank transfer, reconcile manually in the admin UI, then generate the final
fiscal invoice with VAT. The interface exists so CPay/CaSys or Payoneer can be added later without
touching order logic. No Stripe, no PayPal — neither works from North Macedonia.

---

## 4. Data flow: ingestion

```
cron → enqueue(ingest_source, slug)
  → fetch list page → discover call URLs
  → for each URL:
      fetch → hash → if unchanged: record fetch, stop
                     if changed:  store snapshot
                       → normalise (text + offset map)
                       → extract (LLM, schema-validated)
                       → if invalid or confidence low → review_queue_item
                       → if valid → upsert call + criteria + evidence spans
                       → chunk + embed
  → update source_health.last_success_at, last_new_item_at
  → if stale beyond SLA → alert
```

## 5. Data flow: free shortlist (synchronous, <5s)

```
POST /intake → validate → normalise profile (NACE, region, SME size band)
  → require email (magic link sent, results shown immediately)
  → stage 1 hard filter: indexed SQL → ≤200 candidate calls
  → stage 1b rule interpreter: hard_structured criteria in Python
  → stage 2 score & rank: weighted components, each with a reason string
  → render top 10 with verdict badge, deadline, last_verified_at, citation link
```

## 6. Data flow: paid deep report (asynchronous)

```
order created → invoice (proforma) emailed
  → payment reconciled in admin
  → enqueue(deep_analysis, match_run_id)
      → for top 5 calls:
          for each criterion:
            hybrid retrieve (vector + trigram) over that call's chunks
            → LLM verify → {verdict, confidence, quote, snapshot_id, span}
            → schema validate → persist evidence
      → compose report (prose via strong-tier model, MK)
      → banned-phrase lint ("guaranteed", "approved", "you will receive")
      → review_queue_item(kind=report)
  → human approves/edits in admin
  → WeasyPrint → PDF → email to customer
  → any reviewer correction written back as an eval case
```

---

## 7. Deployment topology

Single VPS in the EU (Hetzner, Falkenstein or Helsinki), Ubuntu LTS, Docker Compose:

| Service | Image | Notes |
|---|---|---|
| `caddy` | caddy:2 | Automatic TLS, reverse proxy, static file serving |
| `web` | app | gunicorn, 2–3 sync workers |
| `worker` | app | `rq worker ingest analysis` — same image, different command |
| `redis` | redis:7-alpine | Queue only. `maxmemory-policy noeviction`, AOF on |
| `postgres` | pgvector/pgvector:pg16 | Single instance, volume-backed |

Host `cron` runs `docker compose exec web flask ...` for scheduling. Cloudflare sits in front in
**Full (Strict)** mode — Caddy already terminates real TLS, so Flexible would be a downgrade.

**Backups.** Nightly `pg_dump -Fc` encrypted with `age` and pushed to EU object storage (Hetzner
Storage Box or Backblaze B2 EU), 30 daily + 6 monthly retention. Snapshots are copied off-site by the same
job; being content-addressed, they never change once written. **A restore drill into a scratch container is a calendar task on the
first Saturday of every month** — an untested backup is not a backup.

**Observability.** Sentry free tier for exceptions. An external heartbeat service
(healthchecks.io free tier) pinged by the nightly backup job and the ingestion run, so that failure
of the box itself is noticed by something that is not the box.

**Cost.** VPS €6–8 · backup storage ~€1 · domain ~€1/mo amortised · transactional email free tier ·
models €5–20/mo depending on volume. **Total €15–30/mo**, not €15 (see §9.5).

---

## 8. Data protection posture

| Concern | Implementation |
|---|---|
| Residency | Postgres, snapshots and backups all in the EU. Nothing personal is stored outside it. |
| Minimisation to the model | The LLM gateway is the only egress path and scrubs identity fields first. The model receives the *shape* of an applicant — sector code, size band, region code, investment band — never a name, EMBS/EDB, address or contact detail. |
| Transfers | The model provider is a US processor under SCCs, disclosed in the subprocessor list. Cloudflare terminates TLS in transit and is disclosed for the same reason. |
| Consent | `consent_record` rows with purpose, text version, timestamp, IP. Marketing consent is separate from service consent. |
| Retention | Profiles 24 months after last activity; invoices retained per tax law (see `decisions.md` D5); snapshots indefinitely — they contain no personal data. |
| Deletion | A documented erasure routine that anonymises accounts and profiles while preserving invoice records required by law. |
| Record of processing | `docs/gdpr/` — maintained from P3, when real users arrive. |

---

## 9. Where I disagree with the brief

### 9.1 Start with **two** sources, not six (§5)

The brief says start with six and prove the pipeline. Six first attempts produce six chances to build
the wrong abstraction. Build the complete pipeline against **FITR** (domestic, hard HTML, and the
brief's own P1 acceptance criterion) and the **EU Funding & Tenders Portal** (international,
structured feed). Those two sit at opposite ends of the difficulty range, so the fetcher/normaliser/
extractor interfaces get stress-tested in both directions before they calcify. The remaining four
then land as repetitions of a proven pattern, roughly one evening each instead of three. P1's end
state is unchanged: six sources live.

### 9.2 "Deep analysis under 3 minutes" contradicts the review gate (§2.3 vs §6.4)

If a human approves every paid report, delivery is measured in hours. Two different numbers are being
conflated. Publish: *analysis completes in minutes; your reviewed report arrives within one business
day.* Promising three minutes and delivering next morning is the fastest way to burn the trust this
product is entirely built on.

### 9.3 `Applicant` conflates account and profile (§4)

Split into `account` (identity, email, language, consent) and `applicant_profile` (the answers, with
`version` and `superseded_at`). A profile edited after a report was purchased must not retroactively
change the inputs that report was computed from. Without this, §4's own reproducibility goal is
impossible and any dispute with a customer is unresolvable.

### 9.4 Playwright is listed too early (§9)

Playwright with browser binaries adds roughly 1 GB to the image and real RAM pressure on a €7 VPS
that is also running Postgres, Redis and an embedding workload. P1 uses `httpx` + `selectolax` only,
and **a source that requires a browser is disqualified from the first six**. If a high-value source
later genuinely needs one, it arrives as a separate scheduled container that writes snapshots to the
same store — not as a dependency of the main image.

### 9.5 The €15/month figure covers infrastructure, not run cost (§3.5)

Infrastructure fits comfortably. The budget omits model spend, domain and email. Realistic total is
**€15–30/month** at v1 volumes. More importantly: the dominant cost of a report is *your review
time*, not tokens. `decisions.md` models pricing against review-minutes per report, because that is
the resource that actually runs out.

### 9.6 `schema.sql` will drift from the code (§13.2)

SQLAlchemy models plus Alembic become the source of truth the moment P0.5 lands. Hand-maintaining
`schema.sql` alongside them guarantees they disagree within a month. The file in this repo is a
**design artifact for the planning phase**; from P0.5 it is regenerated from the live database
(`pg_dump --schema-only`) and never hand-edited. Its header says so.

### 9.7 The public archive has an unresolved reuse question (§10 P3)

Republishing the full text of official calls may or may not be permitted; official works in North
Macedonia are generally freely reusable, but "generally" is not a legal position. Until confirmed,
the archive publishes structured summaries, short quoted extracts and links back to the source — which
is also the better SEO strategy, since it is not duplicate content. One evening of checking, scheduled
in P3.

### 9.8 Deploy in P0.5, not P3 (§10)

The brief's phases put public surface at P3, which implies the first real deployment happens then. A
solo operator who defers the first production deploy discovers TLS, DNS, migrations and backups in
the same week they are trying to launch. P0.5 ships a "hello" page on the real domain with TLS,
automated backups and a **completed restore drill** before a single feature exists.

### 9.9 Test willingness to pay before building the matching engine (§11)

P2 is the largest phase at ~16 sessions. The brief's risk register flags low willingness to pay, but
the sequencing tests it only at P4, roughly 40 sessions in. Add a demand test at the end of P1: a
landing page, email capture, and a report offered at a real price and fulfilled by hand from the
registry data you already have. If nobody buys a manually written report, an automated one will not
sell either — and you will have learned it 30 sessions earlier.

### 9.10 Agreements worth stating

Flask over FastAPI (§9): correct — you know it, and no request handler here needs async. Keep
Pydantic anyway as the schema layer. No SPA (§9): correct, and HTMX is the right amount of JavaScript
for a mid-range Android on mobile data. pgvector (§9): correct, and for a sharper reason than the
brief gives — Postgres full-text search has no Macedonian dictionary, so lexical-only retrieval over
Cyrillic would be weak. Hybrid vector + `pg_trgm` covers both prose and exact codes without adding a
search service. Human review gate as a first-class feature (§6.4): strongly correct; it is also the
mechanism that generates the evaluation suite.

### 9.11 One change of my own: cron + RQ, not APScheduler

The brief asks which is simpler for solo operation. APScheduler is simpler to *start* and worse to
*live with*: jobs share the web process, a crash takes the schedule with it, and a failed overnight
ingestion leaves no durable record to inspect the next evening. Use host `cron` for timing (no
`rq-scheduler` dependency) and RQ for execution, which gives retries, process isolation and failed-job
introspection. Redis is one extra container, ~10 MB of RAM, and effectively zero operational
attention.

---

## 10. Brief coverage table

Audit that nothing was dropped.

| Brief section | Where addressed |
|---|---|
| §2 product journey | architecture §5–6, `roadmap.md` P2–P6 |
| §3.1 jurisdiction, language, formats | architecture §3.5, `CLAUDE.md` formatting rules |
| §3.2 payments, no Stripe/PayPal | architecture §3.6, `schema.sql` `invoice`/`order`, `roadmap.md` P4 |
| §3.3 data protection | architecture §8, `risks.md` R5, `decisions.md` D5 |
| §3.4 accuracy contract | `matching.md` §2–5, `CLAUDE.md` invariants, `schema.sql` `evidence` |
| §3.5 cost and scale | architecture §7, §9.5 |
| §4 domain model | `schema.sql` with the §4 challenge answered in its header |
| §5 data sources and ingestion rules | `sources.md`, architecture §3.1 |
| §6 matching engine | `matching.md` |
| §7 AI usage rules | architecture §3.4, `CLAUDE.md` |
| §8 document generation | `roadmap.md` P5, `schema.sql` `document_*` tables |
| §9 proposed stack | architecture §7 and §9 (disagreements) |
| §10 delivery phases | `roadmap.md` |
| §11 risk register | `risks.md` |
| §12 quality bars | architecture §3.5, `CLAUDE.md`, `roadmap.md` P3 acceptance |
| §13 plan deliverables | this directory |
| §14 MVP definition of done | `roadmap.md` P4 acceptance |
