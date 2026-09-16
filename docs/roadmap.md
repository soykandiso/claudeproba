# Roadmap

**Sizing basis:** one evening-session ≈ 2–3 focused hours. You committed to 4–5 sessions/week
(~12 h). Calendar dates below assume a 2026-09-15 start at 4.5 sessions/week and **exclude any
buffer** — see §8 for the honest version.

**Session counts:** P0.5 = 5 · P1 = 16 · P2 = 16 · P3 = 10 · P4 = 8 · P5 = 12 · P6 = 6 = **73 sessions**.

Each phase ends in a demonstrable increment. Nothing is "done" without its acceptance criterion met.

---

## P0.5 — Foundation and first production deploy · 5 sessions · → ~22 Sep 2026

The brief puts the first deployment at P3. That is a trap: you discover TLS, DNS, migrations and
backups in the same week you are trying to launch (architecture §9.8). Deploy an empty app first.

| # | Task | Acceptance |
|---|------|-----------|
| 1 | Repo skeleton, `uv`, `ruff`, `pytest`, Flask app factory, config loading, `/healthz` | `pytest` green, `flask run` serves `/healthz` locally |
| 2 | Docker Compose: caddy, web (gunicorn), worker (rq), redis, postgres+pgvector; `.env.example` | `docker compose up` gives a working stack; `vector`, `pg_trgm`, `citext` all present |
| 3 | SQLAlchemy models + first Alembic migration from `docs/schema.sql` | `alembic upgrade head` creates every table; `pg_dump --schema-only` regenerates `docs/schema.sql` cleanly |
| 4 | VPS provision (EU), domain, DNS, Cloudflare Full (Strict), deploy a hello page | `https://<domain>` serves from the real box with a valid certificate |
| 5 | Nightly `pg_dump` → `age` → EU object storage; heartbeat ping; **completed restore drill**; `docs/runbook.md` | A restore from last night's dump into a scratch container succeeds and the schema matches. **Not done until the restore has actually run.** |

---

## P1 — Ingestion · 16 sessions · → ~19 Oct 2026

Two sources first, then four repetitions (architecture §9.1, `sources.md` §1).

| # | Task | Acceptance |
|---|------|-----------|
| 6 | **Reconnaissance of all six sources** per `sources.md` §4 | Matrix filled in, every `UNVERIFIED` deleted, 3 page fixtures per source committed, real cadences recorded |
| 7 | LLM gateway: model routing config, Pydantic validation, content-hash cache, `model_call` audit, **PII scrubber** | Scrubber test passes on a fixture containing name, EMBS, EDB, address, phone, email; a deliberately invalid model response fails closed rather than publishing |
| 8 | Snapshot store, fetcher base class, change detector | Fetching one URL twice creates one snapshot row; bytes land in object storage; second fetch spends zero tokens |
| 9 | Normaliser: HTML (`selectolax`) and PDF (`pypdf`/`pdfplumber`) with **character-offset preservation** | A known quote's `(start, end)` in `normalised_text` round-trips to exactly that text |
| 10 | Extraction prompt v1 + `CallExtraction` schema | On 3 FITR fixtures, criteria extract with citations; a malformed response lands in the review queue |
| 11 | **FITR fetcher, end to end** — *built for AV instead (16.09.2026): FITR unreachable, `sources.md` §6.1* | **Brief's own P1 criterion:** a newly published FITR call is in the database within 24 hours, with a snapshot and working citations |
| 12 | Chunker, embedder, hybrid retrieval query (vector + trigram) | A clause retrieved by paraphrase appears in the top 3 |
| 13 | EU Funding & Tenders fetcher — *built 16.09.2026, no interface change needed; scope is `decisions.md` D10, linked call documents not yet extracted (`sources.md` §6.6)* | Same pipeline, different access method. Any interface change this forces is the point of building it second |
| 14 | Source health, staleness SLA, alerting, external heartbeat — *built 16.09.2026: `flask ingest health` + healthchecks.io; delivery drill waits for the VPS (P0.5 s4), `runbook.md` §4* | Break a source deliberately in staging → alert reaches you **outside the app** within its SLA |
| 15 | Admin review queue UI (extraction items) — *built 16.09.2026: `/admin`, not registered in production until operator sign-in (`decisions.md` D11); approval fills the stage-1 prefilter columns* | Approve / edit / reject works; only approved calls get `is_published = true` |
| 16 | Manual source entry (`access_method='manual'`) | Paste a URL → snapshot → extraction → review, same citation quality |
| 17 | Агенција за вработување fetcher — *built in s11; this slot goes to FITR once it is reachable* | Calls in registry with citations |
| 18 | Министерство за економија fetcher | Calls in registry; news items correctly *not* ingested |
| 19 | Град Скопје fetcher | Calls in registry; the fetcher is configurable enough that a second municipality is config, not code |
| 20 | АФПЗРР / IPARD fetcher (hardest parse, PDF tables) | Calls in registry; tabular eligibility extracted or explicitly routed to manual review |
| 21 | **Demand test** — landing page, email capture, a deep report offered at a real price and fulfilled *by hand* | Page live; ≥20 emails captured **or** a clear negative signal; ≥5 prospects have given you a yes or a no at the real price |

> Session 21 is the cheapest possible test of the biggest commercial risk, and it runs **30 sessions
> before** the brief would have tested it (architecture §9.9). If nobody buys a hand-written report,
> do not build P2 as specified — go back to `decisions.md` D1.

---

## Demo stage — 16.09.2026, between P1 s12 and s13

Paused P1 to make the whole product clickable before building more of it: `/demo` runs every
phase's customer and operator screens on invented calls, with state in the session cookie. Built for
real along the way, ahead of their sessions and with tests: the stage-1 rule interpreter and
verdict taxonomy (part of **s24**) and the banned-phrase lint (part of **s32**). Everything else on
`/demo` is simulated and is replaced, not extended, when its session arrives. `/demo/vodic` maps
each feature to its session. The demo was tried and approved on 16.09.2026; P1 continued with s13.

---

## P2 — Matching · 16 sessions · → ~12 Nov 2026

| # | Task | Acceptance |
|---|------|-----------|
| 22 | Reference data (NACE, municipalities, regions) + `normalise()` | 30 fixture intakes normalise correctly; reference data is versioned files, not production rows |
| 23 | Intake form in Macedonian, HTMX, mobile-first | A real person completes it in **under 3 minutes**, timed |
| 24 | Stage 1: SQL filter + rule interpreter — *also: a call whose eligibility lives in a document not yet extracted (EU call-document PDFs, `sources.md` §6.6) never reaches `eligible`* | Unit tests for all 9 operators; missing profile data yields `needs_verification`, never `not_eligible` |
| 25 | Evaluation harness tier A skeleton + 10 generated boundary profiles | Harness runs in CI (red, with no cases yet) |
| 26 | **Your session: mark expected verdicts for ~40 cases** | Cases committed with a one-line reason each. Highest-value evening in P2 |
| 27 | Stage 2 scoring + `config/weights/v1.yaml` | Tier A green; rank quality ≥ 90%; **zero false `eligible`** |
| 28 | Shortlist page: verdict badges, reasons, deadlines, `last_verified_at`, citation links | p50 latency < 3 s measured on the VPS |
| 29 | Verification prompt, `VerificationResult` schema, verdict clamping, verbatim-quote check | Tier B green against cassettes; a paraphrased "quote" is rejected |
| 30 | Retrieval tuning for verification — *includes the query for documents not in Macedonian: a Macedonian label over an English EU quote ranks other documents' clauses first (`CROSS_LANGUAGE_MISS` in `tests/test_retrieval_paraphrase.py`)* | Correct clause in top 6 for ≥ 90% of criteria |
| 31 | Stage 3 orchestration on RQ | Enqueue → outcomes and evidence persisted for top 5 calls |
| 32 | Report composer (MK prose) + banned-phrase lint + citation completeness check | Lint blocks a deliberately bad draft containing "гарантирано" |
| 33 | Report review UI with the quote highlighted in the stored snapshot | You can approve or edit a full report in under 45 minutes |
| 34 | Nightly review → eval case job | A rejected item appears in `evals/cases/from_review/` on the next run |
| 35 | PDF rendering (WeasyPrint) with correct Cyrillic typography | MK renders correctly using fonts actually installed on the VPS |
| 36 | Tier C live eval + cost-per-report dashboard | Weekly job runs; you know the marginal model cost of one report |
| 37 | Mobile and performance pass | Shortlist usable on a mid-range Android over throttled mobile data (brief §12) |

**Phase acceptance (brief P2):** ten test profiles produce correct shortlists, every criterion cited.

---

## P3 — Public surface · 10 sessions · → ~27 Nov 2026

| # | Task | Acceptance |
|---|------|-----------|
| 38–39 | Landing page and pricing page in Macedonian | Explains the free shortlist honestly; no dark patterns in the upgrade path (brief §12) |
| 40 | i18n scaffolding verified: Babel, `dd.mm.yyyy`, МКД/EUR formatting | Locale switch works correctly with only MK content present |
| 41–42 | Public SEO archive: durable programme pages + closed call pages | Indexed; **summaries, short quotes and links — not full reproductions** |
| 43 | Copyright/reuse check for official publications (architecture §9.7) | Written conclusion in `docs/legal-notes.md`; archive adjusted if needed |
| 44 | Magic-link auth, account area, saved profiles | Sign-in works with no password anywhere in the system |
| 45 | ToS, privacy policy, subprocessor list, consent capture | Liability framing per `risks.md` R6 is explicit and in plain Macedonian |
| 46 | Sitemap, structured data, privacy-respecting analytics, Search Console | Archive pages indexed |
| 47 | Accessibility and performance audit | Works on a mid-range Android over mobile data; every page states `last_verified_at` |

---

## P4 — Money · 8 sessions · → ~10 Dec 2026 · **first revenue**

| # | Task | Acceptance |
|---|------|-----------|
| 48 | Product/order model, `PaymentProvider` interface, `InvoiceProvider` implementation | A card gateway could be added later without touching order logic (brief §3.2) |
| 49 | Proforma PDF with correct fiscal fields: ДДВ 18%, ЕДБ, ЕМБС, gapless numbering per fiscal year | An accountant reviews a sample and confirms it is compliant |
| 50 | Checkout: order → invoice emailed | Customer receives a valid proforma within a minute |
| 51 | Manual reconciliation in admin: mark paid with bank reference | Two-click reconciliation from a bank statement line |
| 52 | Order → deep analysis wiring + notification emails | Paid order enqueues analysis; customer is told what happens and when |
| 53 | Delivery: reviewed PDF emailed, order state machine complete | Delivered within one business day of payment |
| 54 | Fiscal-year and numbering edge cases | Year rollover produces no gap and no duplicate |
| 55 | **End-to-end rehearsal with a real bank transfer** | **Brief §14:** profile → shortlist → order → invoice → transfer → reviewed report delivered |

---

## P5 — Document packages · 12 sessions · → ~29 Dec 2026

Which two programmes get templates first is `decisions.md` D3. **My recommendation is not IPARD
first**, despite it being the highest-value segment — reasoning is in that document.

| # | Task | Acceptance |
|---|------|-----------|
| 56 | Template engine: `docxtpl`, field registry, unfilled-field marking | Financial and legal fields are **marked as requiring the applicant's real data, never invented** (brief §8) |
| 57 | Checklist model and rendering | Every package ships a list of what the applicant must still provide |
| 58–61 | Template set 1 | A complete draft package for a real call, human-reviewed |
| 62–65 | Template set 2 | Same |
| 66 | AI-assisted labelling and "draft for human completion" copy throughout | Labelling appears on the artefact itself, not only on the web page |
| 67 | Package delivery + review gate | **Brief P5:** a complete draft package produced and human-reviewed for a real call |

---

## P6 — Monitoring subscription · 6 sessions · → ~8 Jan 2027

| # | Task | Acceptance |
|---|------|-----------|
| 68 | Saved profiles + subscription model | Profile versioning preserved (architecture §9.3) |
| 69 | New-call matching against saved profiles | Runs after each ingestion, not on a separate schedule |
| 70 | Alert email with full citation quality | An alert is as trustworthy as a report line |
| 71 | Recurring invoicing | Renewal invoice issued automatically, reconciled manually |
| 72 | Unsubscribe and consent handling | One click, no dark pattern |
| 73 | Digest behaviour in quiet and busy periods | Bursty call seasons do not produce email spam (`risks.md` R4) |

---

## 8. The honest schedule

The table above is arithmetic, not a forecast. Three adjustments:

1. **Ingestion estimates are the least reliable numbers here.** A single source whose HTML turns out
   to be generated by JavaScript, or whose PDFs are scanned images, can cost three sessions instead
   of one. Session 6 (reconnaissance) exists precisely to find that out before it is expensive.
2. **Apply a 25% buffer.** Realistic first revenue: **late December 2026 to mid-January 2027**, not
   10 December. Say that number to yourself now rather than feeling behind in November.
3. **The holidays fall inside P5.** Assume two weeks of nothing between late December and early
   January; P5 and P6 will slip into late January 2027 and that is fine.

One thing worth checking during session 6: North Macedonian calls are **seasonal**, and the archive
data you collect will tell you when. If your launch window lands in a dead period for open calls, the
demand test in session 21 will read as a false negative. Know the seasonal shape before you interpret
that result.
