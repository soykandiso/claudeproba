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
| 16 | Manual source entry (`access_method='manual'`) — *built 16.09.2026: `/admin/rachen-vnes` queues an RQ job, `flask ingest manual` runs it now; every entry answers in the review queue* | Paste a URL → snapshot → extraction → review, same citation quality |
| 17 | Агенција за вработување fetcher — *built in s11; this slot goes to FITR once it is reachable. 16.09.2026: FITR still times out (`sources.md` §6.1); slot deferred, P1 continues with s18* | Calls in registry with citations |
| 18 | Министерство за економија fetcher — *built 16.09.2026: call text only (forms listed for the reviewer); bilingual MK/AL PDFs OCR'd at mean confidence ~70, so each call also raised an OCR-doubt item — **fixed 21.09.2026, `sources.md` §6.11**, the Albanian half is now read with `sqi`* | Calls in registry; news items correctly *not* ingested |
| 19 | Град Скопје fetcher — *built 16.09.2026 as `sources/municipal.py`: a municipality with the same page shape is an `options` block in `sources.yaml` (tested with a second, invented one)* | Calls in registry; the fetcher is configurable enough that a second municipality is config, not code |
| 20 | АФПЗРР / IPARD fetcher (hardest parse, PDF tables) — *built 18.09.2026: the call page is the call, so an advance notice and the published call are one call; decided calls (ranking listed) out of scope; tables routed to the reviewer by a note on every item. Found: OCR cannot read `%` (`sources.md` §6.9, D9) — **fixed 21.09.2026 out of order, `sources.md` §6.10*** | Calls in registry; tabular eligibility extracted or explicitly routed to manual review |
| 21 | **Demand test** — landing page, email capture, a deep report offered at a real price and fulfilled *by hand* | Page live; ≥20 emails captured **or** a clear negative signal; ≥5 prospects have given you a yes or a no at the real price |

> **Out of order, 21.09.2026 — both open OCR gaps, so D9 is now closed.** s21 is blocked on
> `decisions.md` D1 and D2, so the time went to the two accuracy bugs s18 and s20 found. (1) The
> `mkd` model has no `%`, so every OCR'd rate was a wrong number that passed the verbatim check
> (`sources.md` §6.10). (2) `mkd` cannot read Albanian, so every bilingual Economy call was flagged
> on every page while extraction indexed nonsense; the Albanian blocks are now read with `sqi`
> (§6.11). Both are normaliser changes with recorded test sets; no fetcher moved and no roadmap row
> moved. s21 is still next.

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

> **Out of order, 22.09.2026.** s21 is still blocked on `decisions.md` D1 and D2, so the evening
> went to s22, the one P2 row that needs nothing from anybody: reference data is either correct or
> it is not. It is also the row s23's intake form cannot start without. s21 remains next as soon as
> a price and a domain exist.
>
> **And then s23, same day, asked for and chosen by the user** over deciding D1/D2 first. It is the
> second row that costs nothing either way: whatever the demand test says, a company has to be able
> to describe itself, and the form is what the landing page of s21 would send people to. **s21 is
> still the next row**, and the warning below still stands — do not build s24 onwards before it.

| # | Task | Acceptance |
|---|------|-----------|
| 22 | Reference data (NACE, municipalities, regions) + `normalise()` — *built 22.09.2026 out of order (s21 still blocked on D1/D2): imported from the statistical office's own archives into `data/`, with the two systematic defects in the published workbook repaired and recorded (`data/README.md`)* | 30 fixture intakes normalise correctly; reference data is versioned files, not production rows |
| 23 | Intake form in Macedonian, HTMX, mobile-first — *built 22.09.2026: `/profil` over `app/matching/intake.py`; eleven questions, four of them required; the activity picker searches the 1000-row classification over HTMX and degrades to a typed code without JavaScript. `/demo/profil` now renders the same form and runs the real stage 0, so the demo's own thirteen municipalities and its own `normalise` are gone* | A real person completes it in **under 3 minutes**, timed — **not yet proven**: the page measures and reports the time, and the user has to run it once |
| 24 | Stage 1: SQL filter + rule interpreter — *built 22.09.2026 as `app/matching/stage1.py`: `candidates()` is the SQL, `judge()` the interpreter over approved criteria, `run()` both. A predicate the profile cannot answer is not applied at all, and an age band is filtered permissively but judged conservatively. The document gap is a new column, `call.eligibility_gap`, set on every EU topic and shown to the reviewer; a call carrying it can never reach `eligible` or `likely_eligible`. Geography stays out of the rule vocabulary until s25–26's harness — decided, `matching.md` §3* | Unit tests for all ~~9~~ **7** operators (the vocabulary settled at seven; `test_hard_filter.py` covers the interpreter, `test_stage1.py` the stored row); missing profile data yields `needs_verification`, never `not_eligible` — proven per field, in the SQL and in the interpreter |
| 25 | Evaluation harness tier A skeleton + 10 generated boundary profiles — *built 22.09.2026 out of order (s21 still blocked on D1/D2): `evals/` holds five real calls frozen with their documents and approved criteria, ten boundary profiles, the gate (`evals/run.py`) and the 41 blank case rows s26 fills in. Tier A loads the frozen registry into PostgreSQL in a rolled-back transaction, because stage 1a is SQL. Four properties are checked with no cases at all: quotes verbatim, stage 1a a superset of the rules, nothing but a rule excluding anyone, and no call with an unread document rising above `needs_verification`. CI is a command, not a hosted service — `docs/decisions.md`, "Decided in code"* | Harness runs in CI (red, with no cases yet) — **red for exactly one reason**, that an empty suite proves nothing; every property check is green and `tests/test_evals_harness.py` proves each of them can fail |
| 26 | **Your session: mark expected verdicts for ~40 cases** — *done 22.09.2026: all 41 rows of `evals/cases/*.yaml` marked with a reason each, under two written conventions (`evals/README.md`). The gate is green: 0 false eligible, 0 false exclusion, 22 exact, 14 under-decided, and **3 over-claimed** — the AV internship call shown as `likely_eligible` to applicants whose own answers (0–1 employees, founded ≤ 5 months ago) put its six-month employee condition in doubt* | Cases committed with a one-line reason each. Highest-value evening in P2 |
| 27 | Stage 2 scoring + `config/weights/v1.yaml` — *built 22.09.2026, scoped with the user: `app/matching/stage2.py`, every component with a Macedonian reason, missing data neutral, excluded calls last; weights **untuned** and marked so. `size_fit` departs from the design after measuring it (a grant cap is partial help, not a misfit — `matching.md` §4). Rank quality **not measured**: four open calls fit any top five, and the harness says so instead of printing 100%. Zero false eligible; a new property checks every ranked call has a reason and no excluded call ranks above an open one. `match_run` is not written until an `applicant_profile` row exists* | Tier A green; rank quality ≥ 90%; **zero false `eligible`** |
| 28 | Shortlist page: verdict badges, reasons, deadlines, `last_verified_at`, citation links — **rank before judging**: `stage1.run` reads every candidate's criteria, which is 2 s at 13.000 candidates (`matching.md` §3, measured 22.09.2026) — *built 22.09.2026: `/povici` over `app/matching/shortlist.py`, the top ten with every condition's quote found again in the stored text before it is shown (a quote that is not there downgrades the call to needs_verification, an exclusion included), and `/povici/izvor/<criterion>` showing the passage in a short window of the stored text. **Rank-before-judging deliberately not built** — 274 ms at 2.000 open calls, and the country is nowhere near that (`decisions.md`). Latency on this Codespace: 14 ms median over the five seeded calls; the VPS measurement waits for the VPS* | p50 latency < 3 s measured on the VPS; `ops/dev/bench_stage1.py` is the same measurement over a synthetic registry |
| 29 | Verification prompt, `VerificationResult` schema, verdict clamping, verbatim-quote check — *built 22.09.2026: `app/matching/verify.py`, `prompts/verify_criterion/2026-09-22.1.md` on `claude-opus-5`, tier B in `evals/tier_b.py` with hand-written cassettes. Tier B green: 28 of 45 cases exact (tier A 23), 0 false eligible, every recorded answer through the gates, a paraphrased quote rejected and sent to review (tested twice). Two decisions (`decisions.md`): a required document is the applicant's to bring, like an attestation; and verification reads attestations and may only lower them — tier B showed that without it a Bitola craftsman is "likely eligible" for a Skopje-only subsidy* | Tier B green against cassettes; a paraphrased "quote" is rejected |
| 30 | Retrieval tuning for verification — *includes the query for documents not in Macedonian: a Macedonian label over an English EU quote ranks other documents' clauses first (`KNOWN_MISSES` in `tests/test_retrieval_paraphrase.py`, which also lists standard clauses repeated across calls and conditions stated twice in one call)* — *built 23.09.2026: the cited chunk is pinned first (`hybrid_retrieve(pin=…)`, `verify.call_retriever`) and the query is the quote alone, which closed the cross-language and twice-stated misses; `evals/run.py --retrieval` measures it with the real embedder. Production 24/24 criteria and 8/8 cassette evidence in the top 6 — close to certain by construction; the unpinned search over all five documents pooled: 23/24 first, 24/24 in the top 6. Threshold and chunk size not retuned: five documents is no set to tune on (`matching.md` §5)* | Correct clause in top 6 for ≥ 90% of criteria |
| 31 | Stage 3 orchestration on RQ — *built 24.09.2026: `app/matching/deep.py` on the `analysis` queue, one job per stored `applicant_profile` (new column `answers`, read back through `normalise`). Stages 1–2 exactly as `/povici`, a committed `match_run` every model call points at, `verify_call` on the top five open calls, every model citation found again in the stored text, then results, per-criterion outcomes and evidence in one commit. Proven over the five frozen calls with tier B's answers and over hand-built failures. **Not proven live**: the worker was down on a network fault and there is no model key (`handoff.md` §4)* | Enqueue → outcomes and evidence persisted for top 5 calls |
| 32 | Report composer (MK prose) + banned-phrase lint + citation completeness check — *built 24.09.2026: `app/reports/compose.py` reads a finished stage-3 run from its stored rows only; code writes every verdict, condition, reason and citation, and the model (`compose_report`, prompt `2026-09-24.1`, `ReportProse`) writes a summary and per-call explanation and next steps in which **every statement cites condition numbers**. Two checks over the whole draft, either one blocking: the lint over everything said in the report's own voice (prose, condition labels, verification's reasons), and citation completeness against the stored text (every condition's quote at its offsets with URL and date, every model decision's evidence, every cited number a condition of the call it is about). The draft is a `report` review item, blocked ones first; `blockers()` re-runs both over a reviewer's edit. `deep` now also stores the calls the rules exclude (up to ten) so the report can say why. Not run against the real model — no key* | Lint blocks a deliberately bad draft containing "гарантирано" |
| 33 | Report review UI with the quote highlighted in the stored snapshot — *built 29.09.2026: `/admin/izveshtaj/<id>` over `app/review/report.py`. Every condition's quote and every model evidence shown marked inside the stored text, with URL, retrieval date, span, and the scanned page when OCR'd; problems listed first, each linked to where it is. **Approval calls `compose.blockers()` and is refused while it returns anything** (service and screen, tested). The reviewer edits the model's statements only — words and cited condition numbers — each edit checked by `ReportStatement` and the same checks, refused whole if it fails; verdicts and quotes have no edit path. Edits kept in `corrected_payload` with a log. The 45 minutes is a person's measure: the screen reports the minutes at the decision; `ops/dev/seed_report.py` puts a draft over the frozen calls in dev to time it on* | You can approve or edit a full report in under 45 minutes |
| 34 | Nightly review → eval case job — *built 30.09.2026: `app/review/cases.py`, `flask review export-cases`, cron 02:45 UTC. Every extraction or report item a person rejected or edited becomes `evals/cases/from_review/<kind>-<id>.yaml`, written once; an approval without an edit and a supersession write nothing, a run's failed verifications travel inside its report's case. Nothing identifying: the applicant as the bands a model sees, the note and edits through the scrubber with the customer's e-mail and label as known names (which found a scrubber gap — a phone number ending a sentence — fixed). On the VPS the files are written outside the checkout and pulled to be committed (`runbook.md` §5). The harness loads and shape-checks them but scores none: extraction cases wait for tier C, report cases for a person to write the verdict* | A rejected item appears in `evals/cases/from_review/` on the next run |
| 35 | PDF rendering (WeasyPrint) with correct Cyrillic typography — *built 30.09.2026: `app/reports/render.py` + `templates/report.html`/`report.css`; `/admin/izveshtaj/<id>/pdf` and `flask review render-report`. Only an approved or edited report; `compose.blockers()`, the lint over the whole printed text and a glyph-coverage check run again first, and a PDF embedding any font but ours is refused. **The first render had perfect extracted text and wrong digits and Latin**: WeasyPrint mixes the site's Latin and Cyrillic subsets, which share one font name — so the PDF merges each pair into one file at runtime, and a test reads the pixels back with Tesseract. Rendered inside the image, which has 6 system fonts: only Source Serif 4 and Fira Sans embedded. On the VPS itself once it exists* | MK renders correctly using fonts actually installed on the VPS |
| 36 | Tier C live eval + cost-per-report dashboard | Weekly job runs; you know the marginal model cost of one report |
| 37 | Mobile and performance pass | Shortlist usable on a mid-range Android over throttled mobile data (brief §12) |

**Phase acceptance (brief P2):** ten test profiles produce correct shortlists, every criterion cited.

---

## Design phase · 9 sessions (DS1–DS9) · after P2, before P3 · → ~2 weeks

> **Added 30.09.2026 at the user's request:** "after this phase implement design phase to be the
> best designed platform." It sits between P2 and P3 because every screen a customer will see
> now exists in a first form (`/profil`, `/povici`, the passage page, the report and its PDF, the
> admin), and P3's landing, pricing and archive pages should be built *on* the finished system, not
> retrofitted to it. The direction is fixed and does not change here: **the dossier, not the
> dashboard** (`.claude/skills/design-system`). "Best designed" is therefore measured, not claimed:
> a native reader finds no wrong letterform, a first-time user finishes the tasks unaided, the
> audits find nothing, and the budget holds on a cheap phone. Numbered DS so P3's session numbers
> (referenced elsewhere, e.g. "magic link at s44") stay what they are.
>
> **Moving parts:** none new. Jinja macros, `tokens.css`, `site.css`, Tailwind via the standalone
> binary, HTMX. No Node, no component framework, no JavaScript that has not earned its place.

| # | Task | Acceptance |
|---|------|-----------|
| DS1 | **Design audit** of every real screen at 375/768/1440 against the skill's rules — tokens, verdict marks, `last_verified_at`, deadlines, focus, all five interaction states, copy, Cyrillic forms. Written up in `docs/design.md` with a screenshot and a fix per finding — *built 01.10.2026: 10 screens and the PDF at three widths, 36 findings (3 severity A: F10 likely/needs-verification marks identical in greyscale, F13 passage page without `last_verified_at`, F29 a passed deadline shown as a plain date in the report), each owned by DS2–DS9; `docs/design/ds1/` holds the crops* | Every screen audited; every finding has an owner session below |
| DS2 | **Foundation**: `tokens.css` complete and the only source of values (a check that fails on a hex outside it); font subsets re-cut and verified for Ѓѓ Ќќ Љљ Њњ Џџ Ѕѕ Јј and the Macedonian `locl` italic бгдпт; type scale and measure; a dev-only `/stil` page rendering every token — *built 01.10.2026: F01/F02/F03/F05/F06/F27 closed and held by `tests/test_design_foundation.py`; upright subsets not re-cut (upstream Fira has no Cyrillic `locl`, the serif already keeps MKD); Source Serif 4 Italic cut with MKD б г д п т, on `/stil` only; `/stil` reads `tokens.css` live and measures contrast. **Open: the native reader's sign-off of the italic***  | No hardcoded colour or size left in templates; each font ≤ 40 KB; a native reader signs off the italic |
| DS3 | **Component set** as Jinja macros: verdict mark (four treatments), cited excerpt with its source line, deadline with days in words, date/amount, buttons and form controls with hover/focus-visible/active/disabled/loading, hairline lists, empty and error states. All on `/stil` — *built 01.10.2026: `_components.html`, every macro in every state on `/stil` (`?siv=1` greyscale), F04/F10/F11/F12/F25/F26/F31 closed, `submit.js` the first JavaScript of our own; marks tell apart in greyscale (seen at 375); contrast measured live on `/stil`, all pairs pass* | Every component in every state on `/stil`; verdicts tell apart in greyscale; every contrast pair re-measured |
| DS4 | **Intake** (`/profil`, `/profil/pregled`) rebuilt on the components; the activity picker's HTMX loading state — *built 01.10.2026: error summary with a link per field and plural agreement, error before hint, age in years, nav by blueprint, the picker's loading state on the field and on the picked row (seen live). **Open: the timed run**, which only a person can do; the review page says the time in minutes. Found: «пекар» finds nothing (НКД says «леб»), a synonym file in `data/` would help the run* | Timed run by a real person under 3 minutes (the s23 acceptance, finally proven) |
| DS5 | **Shortlist and passage** (`/povici`, `/povici/izvor/…`) — the cited passage as the memorable element; the reason for each verdict readable in one glance — *built 01.10.2026: F11/F13/F14/F15/F16/F17/F18 closed; one line under each verdict counts how its conditions came out; quotes and titles carry their language. **Open: the first-time-user test** (a person's), and F38 (stage 1a's discards never reach the excluded section; the user decides)* | A first-time user says, unaided, why a call is "needs verification" and where that comes from |
| DS6 | **The report, on screen and on paper**: s35's PDF and a web view sharing one set of components — numbered clauses, marginal citations, print typography — *built 01.10.2026: F07/F23/F28/F29/F30 closed; F29 (A) blocks approval and print of a report whose call has since closed; the screen view (`/admin/izveshtaj/<id>/dokument`) is the PDF's own template, the same text in the same order proven by a test; calls flow (11 → 10 pages); found and fixed on paper: the struck mark printed filled, the dotted ring as specks. **Open: whether a printed page reads as a document** (the user's eye on a real print), and the cover naming the customer (P4)* | PDF and web say the same thing in the same order; a printed page reads as a document, not a web page |
| DS7 | **Operator screens** (`/admin`, `/admin/izveshtaj/…`): density for a person reviewing every evening — keyboard paths, problems first, quotes in place — *built 02.10.2026: the admin in Macedonian (F32), a decision bar under the problems and the reason beside a disabled approval (F33), removal as a confirmed second step (F34), quote and scanned page side by side at ≥ 1200px (F36), the shell like the site's (F08, F09). **Open: the 45-minute review**, a person's* | A full report reviewed in under 45 minutes (the s33 acceptance, finally proven) |
| DS8 | **Your session: usability test** with five people from the target market (owners or consultants), on a mid-range Android, tasks scripted in Macedonian; findings fixed in the same session or listed | Five sessions run, notes committed, every task completed unaided by ≥ 4 of 5 |
| DS9 | **Accessibility and performance**: WCAG 2.1 AA (axe and a keyboard-only pass and a screen reader), Lighthouse on throttled mobile, the font and HTMX budget. Takes in P2 s37 if it has not been done — *built 02.10.2026: axe WCAG 2.1 A/AA zero violations on every real screen at three widths, 44px targets (F37), keyboard pass, budget measured (132-167 KB first visit) and held by `tests/test_budget.py`. **Not run here**: Lighthouse, a screen reader* | Zero AA violations; shortlist usable over throttled 3G; Lighthouse performance and accessibility ≥ 95 |

**Phase acceptance:** every customer screen passes DS1's checklist with no open findings, and five
real users complete the core tasks unaided. P3 then builds the landing, pricing and archive pages
from the same components without adding new ones.

---

## Design language · 7 sessions (DL1–DL7) · after DS9, before P3

> **Added 02.10.2026 at the user's request:** "a phase before P3 about the design language: a
> radical design improvement, font, colours, UI, elements, everything; inspired by Apple iOS
> design, glass." It **replaces the direction** of `.claude/skills/design-system` ("the dossier,
> not the dashboard": paper, iron-gall ink, serif, hairlines, no shadows, no glass) with an
> iOS-inspired one, recorded in `docs/design-language.md`. The user chose (02.10): **Inter**,
> **Apple-faithful glass** (the floating navigation layer only, never content), **light and dark
> following the phone**, a **deep-blue tint**. What does not change: the five invariants, the
> verdict grammar (a verdict told apart without colour), every cited claim, Macedonian first,
> `dd.mm.yyyy`, the banned words, one source of values, zero WCAG AA violations, the budget.
> The DS acceptances still owed by people (DS4's timed run, DS5's first-time user, DS7's 45
> minutes, DS8) are taken on the new design, not the old one.

| # | Task | Acceptance |
|---|------|-----------|
| DL1 | **Foundation**: `docs/design-language.md` and the skill rewritten; tokens for both themes (system grounds, label colours, separators, tint, the single-purpose colours), Inter subsets (Cyrillic + Latin, the weights used), the iOS type scale, continuous radii, soft elevation, the glass materials with their fallbacks and `prefers-reduced-transparency`, motion curves; `/stil` rebuilt to show both themes | Every token on `/stil` in light and dark; every contrast pair measured in both and passing; each font file ≤ 40 KB; the old checks updated, not deleted — *built 02.10.2026: 50 contrast pairs pass in both themes, Inter 7 KB per Cyrillic file, axe zero violations in both themes, italic retired, the PDF on its own print fonts until DL5* |
| DL2 | **Components** on the new language: glass navigation bar, phone tab bar, the four iOS button styles, inset grouped lists, form rows and controls, segmented control, the verdict marks re-drawn as symbols, the cited excerpt, disclosure and sheet, empty and error | Every component in every state, both themes, on `/stil`; verdicts tell apart in greyscale in both themes — *built 02.10.2026: glass navigation bar and phone tab bar, four capsule button styles, call cards, verdicts as SF-Symbol-style glyphs (masks in `tokens.css`), chevron disclosures, grouped list, segmented control, sheet; glass fenced in by a test; axe zero violations in both themes at 375/768/1440* |
| DL3 | **Intake** on the new components | Both themes at 375/768/1440; DS4's checks hold — *built 02.10.2026: each section an inset group card, the headcount a segmented control (radios, posts without script, a band never breaks at its dash), the purposes a multi-select list, a full-width submit on phones, the review page a grouped list; axe zero violations in both themes at three widths, the refused form included; DS4's tests unchanged and green* |
| DL4 | **Shortlist and passage** | DS5's checks hold; the citation still the one bold element — *built 02.10.2026: a grouped page with no rules between sections, the legend an inset group, the passage's back button an iOS chevron, its facts an inset group (the source a row), the stored text on a card with the quote the one marked element; every card one shared rule; stylesheet budget 14 → 15 KB as a recorded decision; axe zero violations in both themes at three widths; DS5's tests unchanged and green* |
| DL5 | **The report**: the screen view in the new language, the PDF a print rendering of it (paper is not glass) | PDF and screen say the same thing; the pixel test of the marks passes — *built 03.10.2026: the PDF set in Inter (400/600/700, merged per weight and renamed, since every cut is «Inter-Regular»), quotes recessed and rounded, the four printed marks unchanged; the screen view cards on the grouped ground with the site's symbols and the citation seal, dark with the device (it had fallen back to a serif since DL1); Fira Sans and Source Serif 4 removed; the same-text and pixel tests green* |
| DL6 | **Operator screens** | DS7's checks hold in both themes — *built 06.10.2026: the queue's lists inset cards of rows (each row one tap target with a chevron), item and report reviews a card per part with nested cards recessed, quote context rounded, the manual entry's fields on a card; the demo's and `/stil`'s rows the same; DS7's tests unchanged and green; axe zero violations on the five operator screens in both themes at three widths* |
| DL7 | **Audit**: axe in both themes at three widths, reduced transparency and reduced motion, keyboard, the budget with Inter and glass on a throttled phone | Zero AA violations in both themes; budget held; no glass where Apple's HIG says not to — *built 07.10.2026: axe zero violations on 13 customer, `/stil` and demo screens × 2 themes × 3 widths and the 5 operator screens × 2 themes (375 here, all widths in DL6); text on glass moved to `--label` (grey fell to 3:1 over what scrolls under); `scroll-padding` so focus never lands under a bar (2.4.11); the demo's bar given its glass back; first visit 112-115 KB (~1.2 s Slow 4G, computed); the citation seal as the icon. **Not run here**: a screen reader, Lighthouse, a real Android* |

---

## P3 — Public surface · 10 sessions · → ~27 Nov 2026

| # | Task | Acceptance |
|---|------|-----------|
| 38–39 | Landing page and pricing page in Macedonian | Explains the free shortlist honestly; no dark patterns in the upgrade path (brief §12) — *built 07.10.2026: `/` explains the service in three steps with a **real** condition and its quote, found again in the stored text before it is shown (none, no example); `/ceni` reads D1 (decided 07.10) from `config/prices.yaml`, every price without and with ДДВ, the founding price labelled, «наскоро» for what cannot be bought yet; no countdown, nothing blurred; the banned-phrase lint passes on both; axe zero violations in both themes at three widths. **Open: a native reader for the Macedonian copy** before launch (CLAUDE.md)* |
| 40 | i18n scaffolding verified: Babel, `dd.mm.yyyy`, МКД/EUR formatting | Locale switch works correctly with only MK content present — *built 07.10.2026 (there was no Babel before): Flask-Babel, Macedonian as the source language, a locale chosen only when its catalog exists (`?lang=`, cookie, browser), `<html lang>` the language the page is actually in; `?lang=sq` with only Macedonian present gets the Macedonian page labelled `mk`; the switch proven with a test English catalog; dates `dd.mm.yyyy` everywhere, numbers grouped per language, «МКД»/«EUR» as units; the shell, `/` and `/ceni` marked, extraction via `babel.cfg`. **Not yet marked**: the intake, the shortlist, `_components.html`, the verdict and reason words (`docs/i18n.md`)* |
| 41–42 | Public SEO archive: durable programme pages + closed call pages | Indexed; **summaries, short quotes and links — not full reproductions** — *built 07.10.2026 under `docs/legal-notes.md` §3: `/arhiva` by institution, a programme page per slug (it gains a row each year), a call page per id with its state first (open, announced, closed), our facts, each approved condition with its verified quote, source, date and credit, the whole call a link; closed calls stay, cancelled and unpublished do not, manual entries are left out (D12); conditions whose words moved are dropped and counted; contacts masked around passage quotes; `noindex` until production; axe zero violations in both themes at three widths. **Indexed** waits on the real site (P0.5 s4) and s46's sitemap* |
| 43 | Copyright/reuse check for official publications (architecture §9.7) | Written conclusion in `docs/legal-notes.md`; archive adjusted if needed — *built 07.10.2026, ahead of s41–42 because it sets what they may quote: Art. 16(2) (official texts are not works), Art. 52(7) (quotation for review, source named), Arts. 118–122 (the database maker's right, which the crawler and archive keep clear of), the Commission's CC BY 4.0; nine rules for anything public; the EU credit shown beside every EU quote (`credit_mk` in `config/sources.yaml`). **Not legal advice**: a lawyer before any full text; the draft open data law to check* |
| 44 | Magic-link auth, account area, saved profiles | Sign-in works with no password anywhere in the system — *built 07.10.2026: `/najava` mails a link (15 minutes, once: bound to the account's `last_seen_at`, nothing stored), the link opens a confirm page and its button signs in (mail scanners cannot spend it), the same answer for every address, an account created only when a link is used, three requests per ten minutes per browser; `/smetka` shows the saved profile, every form save a new version on the account, restored on another device; `app/mail.py` (an outbox in development, SMTP in production, which refuses to send unconfigured); production refuses the development secret; no password field anywhere (a test). **Waits on D2** for the domain mail is sent from; the admin is not yet gated by `account.is_admin` (D11)* |
| 45 | ToS, privacy policy, subprocessor list, consent capture | Liability framing per `risks.md` R6 is explicit and in plain Macedonian — *built 07.10.2026: `/uslovi` and `/privatnost` as versioned templates (`legal/<doc>/<version>.html`, old versions readable by date), R6 in its own section («Што услугата не е»); `/obrabotuvachi` from `config/legal.yaml`, a provider not chosen or not running said so; the entity (D4) and contact (D2) shown as «[се утврдува]» and `flask legal check` failing until they are decided (in the deploy steps); consent: a required, unticked box at sign-in, recorded in `consent_record` (purpose, version, time, IP), asked again when the version changes; no cookie banner because there are only a session and a language cookie. **Claude's draft**: a lawyer (R6's one hour) and a native reader before launch* |
| 46 | Sitemap, structured data, privacy-respecting analytics, Search Console | Archive pages indexed — *built 07.10.2026: `/robots.txt` (development: nothing; production: the public pages and the archive, never the form, shortlist, account, admin or demo), `/sitemap.xml` (the public pages, every archived programme and call with the date it was last checked), one switch `robots_meta()` so the landing, prices, legal pages and archive are indexable in production only (they had all inherited `noindex`), `MonetaryGrant` JSON-LD on call pages; analytics: none in the page, GoAccess over the server's log (D14). **Indexed** and Search Console wait on the domain (D2)* |
| 47 | Accessibility and performance audit | Works on a mid-range Android over mobile data; every page states `last_verified_at` — *built 07.10.2026: two screens did not state it (the landing's example, the archive's programme rows) and now do, held by `tests/test_p3_audit.py` over all five screens that show a call; axe zero WCAG A/AA violations on the twelve customer pages × 2 themes × 3 widths (72 scans), plus the sign-in, confirm and erased pages in their sessions; keyboard: every stop ringed, and a row link now keeps room below it so its row's ring is never under the tab bar; first visit 112–115 KB on every P3 page (~1.2 s Slow 4G, computed), server render ≤ 39 ms. **Not run here**: a real mid-range Android, a screen reader* |

---

## P4 — Money · 8 sessions · → ~10 Dec 2026 · **first revenue**

| # | Task | Acceptance |
|---|------|-----------|
| 48 | Product/order model, `PaymentProvider` interface, `InvoiceProvider` implementation | A card gateway could be added later without touching order logic (brief §3.2) — *built 07.10.2026: `app/orders/` — the state machine (`states.move`, the only way an order changes state), `PaymentProvider` (request, confirm) with `InvoiceProvider` (a proforma under a gapless number, the bank reference on confirmation), `service.create` at `config/prices.yaml`'s price (the founding price while it lasts, a cancelled order giving its place back); a test adds a card provider and runs an order through unchanged code. Numbering format in `config/invoicing.yaml`, **provisional until the accountant confirms it (D4)**; no migration* |
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
