# Handoff — read this first when resuming

The working memory of this project across Claude Code sessions. `CLAUDE.md` holds the rules,
`docs/roadmap.md` the plan; this file holds **where we actually are, what was learned, and how a
session is finished**. It is updated at the end of every roadmap session, in the same commit.

**Last updated:** 22.09.2026, after the craftsman entity form (out of order, found by s26). Before
it: P2 s26 — the 41 expected verdicts, marked with the user in one walk-through — stage 1 at scale, the OCR page image, the stale-text warning and P2
s25 (the evaluation harness). s22–s25 were all taken out of
order because P1 s21 is still blocked on D1 and D2; the user chose to carry on down P2 rather than
decide D1/D2 first.

---

## 1. Resume in five minutes

1. Read this file, then `CLAUDE.md`.
2. `git log --oneline | head` and `git status --short`. The user keeps an uncommitted edit in
   `CLAUDE.md` (a stray backtick at the end); never commit that hunk (§6).
3. Open `docs/roadmap.md` at the next session in §2 below and read its row and acceptance.
4. Read the modules that session touches before designing anything. The docstrings are the design.
5. When the user says "continue", do the next roadmap session in order unless §4 says it is blocked.

## 2. Where we are

| Phase | State |
|---|---|
| P0.5 | s1, s2, s3, s5 done. **s4 (VPS, domain, TLS) not done:** blocked on D2 (domain) and on a VPS the user has not provisioned |
| P1 | s6–s16 done (s11 built AV instead of FITR). s17 deferred: FITR still unreachable (checked 16.09). s18 Economy, s19 Skopje, s20 IPARD done. **Both OCR gaps are fixed and D9 is closed** (21.09, `sources.md` §6.10 and §6.11). **s21, the demand test, is still the next P1 row and still blocked** on D1 (price) and on a live page (D2 domain, VPS) |
| P2 | **s22–s25 done 22.09**, all out of order while s21 is blocked. `data/` holds the activity classification, the 80 municipalities and the 8 planning regions as versioned files; `app/matching/normalise.py` is stage 0; `app/matching/intake.py` is the questionnaire and `/profil` (`app/web/intake/`) is the first real customer screen; `app/matching/stage1.py` is stage 1 over the real registry, with `call.eligibility_gap` carrying invariant 3. **`evals/` is the measurement** (s25): five frozen calls, ten boundary profiles, four properties checked on every run, and **since s26 marked cases: the gate is green** — 45 now, with p11 (0 false eligible, 0 false exclusion, 4 over-claimed, 16 under-decided). A registered craftsman is an entity type and a form on `/profil` since the same evening. **The next P2 row is s27, scoring** — technically unblocked, but it is the row the roadmap names as the point where building before the demand test (s21) stops costing nothing. Ask the user before starting it; the over-claim in §8 is a candidate that does not depend on s21 |
| Demo stage | `/demo` clickable on invented data (commit `ce8c9ed`); `/demo/vodic` maps features to sessions and must be kept true when a session makes something real |

s21 stays the commercial test and the roadmap still says **not to build P2 as specified if it comes
back negative**. s22–s25 are the rows that cost nothing either way: correct reference data, a form a
company can describe itself in, a filter that cannot silently exclude anyone, and a way to measure
whether a change made any of it better. **s27 is where that stops being true** — scoring weights are
tuned to a product the demand test may reshape. s26 sits in between: it is the user's own judgement
about real calls, which is worth having whatever the demand test says.

### Session log

| Date | Session | Commit | Outcome, and what it left open |
|---|---|---|---|
| 22.09 | Craftsman form | `git log --grep 'craftsman'` | Out of order, the first §8 item s26 found. `EntityType.CRAFTSMAN` (hand-written migration `1b093080ae25` — autogenerate cannot see a new enum value), «Занаетчија» on `/profil`, sized like a sole trader under the EU SME definition. **The extraction prompt was deliberately not changed** (`decisions.md`): Skopje's call is also for permit holders, so `entity_type in [craftsman]` would be a false exclusion by rule. New boundary profile **p11**, p07 with only the form changed; the user accepted its four verdicts. `run.py --worksheet` now appends rows for a new profile to a marked file instead of skipping the file. Gate green at 45 cases; p11's Economy and Skopje rows are under-decided, which is the measurement of what a prompt version would buy. Checked at 375/768/1440 |
| 22.09 | P2 s26 | `git log --grep 'session 26'` | **The expected verdicts**, marked by the user: I read the five calls in full, drafted a verdict and a Macedonian reason for each of the 41 rows, and the user accepted every one and two conventions, now written in `evals/README.md` — the truth is what an expert would say from the answers and the call's text (not what the system can do), and `not_shown` is for location only. 9 likely_eligible, 18 needs_verification, 7 not_eligible, 7 not_shown; no `eligible`, because every call but the notice has an attestation outstanding. **The gate is green**: 22 exact, 0 false eligible, 0 false exclusion. **What it found**: 3 over-claims, all on AV — `likely_eligible` for p03 (≤ 5 months old) and p07/p08 (0–1 employees), whose own answers put the six-month employee attestation in doubt (§8); 7 Skopje rows where geography would say `not_shown` and the rules can only say `needs_verification` — the measurement the geography decision was waiting for (§8). The report now names over-claimed cases instead of counting them. Also found reading the calls, all in §8: the intake has no *занаетчија* form, the frozen Economy criteria miss four conditions, and the suite's clock predates the AV call |
| 22.09 | Stage 1 at scale | `git log --grep 'bench'` | Out of roadmap order, closing a §8 unknown rather than guessing at s28. `ops/dev/bench_stage1.py` writes a synthetic registry in a rolled-back transaction (two thirds national, every call with criteria), times each step and prints the planner's own account. **The array clauses are not the bottleneck** — 66 ms of SQL over 20.000 open calls, and a seq scan is correct because while most calls are national every profile matches most rows. **The cost is per candidate**: 2 s of it is loading their criteria. `stage1.run` is 26 ms at 200 open calls, 274 ms at 2.000 and 3,3 s at 20.000, so the three-second budget breaks somewhere above 2.000 and the fix is to rank before judging (s28), not an index. Noted for later: the planner estimates 9 rows where 13.311 match |
| 22.09 | OCR page image | `git log --grep 'page image'` | Out of roadmap order, the other half of **D9 rule 1**: an OCR'd quote is now shown with the scanned page underneath it on the review item. `render_page` in `normalise/pdf.py` (pdftoppm, 110 dpi, colour — a stamp and a date are what the reviewer is looking for) and `/admin/dokument/<snapshot>/strana/<page>`, rendered on demand from the content-addressed bytes and never stored, with an ETag so a page is fetched once. **Only OCR and mixed text gets an image**: a photograph of a document that already gave us its characters proves nothing and would make the mark meaningless. The page number comes from `page_of` over the form feeds, so the reviewer gets the page the quote is actually on. ~200 KB and ~0.4 s per page, lazy-loaded; PNG not JPEG, because artefacts on small Cyrillic are the one thing this image must not add. Checked at 375/768/1440 over the real Skopje scan |
| 22.09 | Stale text | `git log --grep 'stale text'` | Out of roadmap order: s26 is the user's own evening and nothing else in P2 may go first. Closed the §8 hole "nothing warns a reviewer": `app/ingestion/normalise` now remembers **which repair each version brought** (`REPAIRS`, `missing_repairs`), `/admin` says on the item which documents were read by an older version and what to distrust in them, and `flask ingest stale-text` lists every such snapshot with the criteria and published calls that cite it. Three decisions. **It warns, it does not block** — most quotes out of an old document are right, there is no re-normalisation path, and a block the reviewer cannot clear teaches them to skim notices. **Nothing is rewritten in place**: re-normalising moves every offset that cites the text, so the remedy is delete-and-re-fetch, its own deliberate job. **Only OCR text is at risk** — both repairs were OCR-only, so a DOCX read in September raises nothing. In the dev database the command finds three snapshots (the s20 IPARD run and one Skopje document) with nothing published on them |
| 22.09 | P2 s25 | `git log --grep 'session 25'` | The evaluation harness, tier A. `evals/` holds five real calls frozen with their document and their approved criteria (`ops/dev/freeze_eval_fixtures.py`, from the captured documents and the extraction cassettes), ten boundary profiles as intake answers, `suite.yaml` (one clock — 01.06.2026 — and the gate's thresholds), `harness.py` and `run.py`. **Tier A loads the frozen calls into PostgreSQL in a rolled-back transaction**: stage 1a is SQL, and a harness that simulated the registry would measure a different program. Three things it settled. **The harness is worth running before anyone marks a case**: four properties hold over every profile × call with no expected verdicts at all — quotes verbatim at their offsets, stage 1a discarding only what the rules would exclude anyway, nothing but a rule excluding anyone, and no call with an unread document ever rising above `needs_verification`. **An expected verdict may be `not_shown`**, and for the gate that counts as an exclusion: a call silently missing from the shortlist is worse for the customer than one listed with a reason. **Being less certain than the truth is not a failure** — expected `eligible`, produced `needs_verification` is reported as under-decided and gated by nothing, because it is the distance s27 and s29 have to close. CI stays a command, not a hosted service (`decisions.md`, "Decided in code"). Acceptance: the gate runs and is red for exactly one reason — no cases yet — and 24 tests prove each property can fail. Also fixed, found by the worksheet: `intake.entity_label` no longer says "Земјоделско стопанство, земјоделско стопанство" |
| 22.09 | P2 s24 | `git log --grep 'session 24'` | Stage 1 over the registry. `app/matching/stage1.py`: `candidates()` is the SQL on the denormalised columns, `judge()` the interpreter over **approved** criteria only, `run()` both. Three things it settled. **A predicate the profile cannot answer is not applied at all** — no activity means no NACE clause, not an overlap against an empty array; filtering on a blank is the easiest way to break invariant 3 where no test would look. **An age band is filtered permissively and judged conservatively**: 1a keeps a call if any month in the range could pass, 1b answers unclear where it straddles — 1a may only throw away what 1b would certainly exclude. **`narrative_verify` and `documentary` are not decided at all** until s29, so most calls are `needs_verification` today; that is honest, not a placeholder. New column **`call.eligibility_gap`** (migration `3adfce186d77`) closes the EU hole in `sources.md` §6.6: the fetcher sets it on every topic, the reviewer sees it on `/admin`, and such a call can never be `eligible` or `likely_eligible` — but `not_eligible` still stands, because an unread document adds conditions, never removes one. **Geography stays out of the rule vocabulary** (the decision s24 owed, `matching.md` §3); 1a's region clause is written and tested so filling the column is the only work left. Acceptance: 42 tests, including the whole path fetch → extract → human approval → stage 1 with nothing hand-built |
| 22.09 | P2 s23 | `git log --grep 'session 23'` | The intake form. `app/matching/intake.py` is the one questionnaire — eleven questions, their Macedonian wording, the validation, and the labels that say a profile back; `app/web/intake/` renders it at `/profil` and `/profil/pregled`. **Only four answers are required** (form, municipality, founding year, headcount): everything else is skippable because a missing answer is *unclear*, not an exclusion, and the acceptance is a three-minute completion. **The one loud failure is an activity we cannot resolve** — everything else degrades quietly, but a discarded НКД code has to be said. The picker searches all 1000 classes over HTMX and needs no JavaScript to work (a typed code resolves). **The demo's own 13 municipalities and its own `normalise` are gone**: `/demo/profil` includes the same partial and the real stage 0, and the `/demo/vodic` row is now `real`. CSRF moved to `app/web/csrf.py`, shared with `/admin`. Left open: **the timed run is the user's to do** — the review page reports the seconds it took, but nobody has run it yet; and the profile lives in the session cookie, not a row (`decisions.md`, "Decided in code") |
| 22.09 | P2 s22 | `git log --grep 'session 22'` | Reference data + stage 0. Imported from the statistical office's own archives (`ops/dev/import_reference_data.py`, hash-pinned in `data/reference.yaml`) rather than typed: НКД Рев.2 (1000 rows) and НТЕС 2013 (8 regions, 80 municipalities). **The published workbook has two systematic defects**, both repaired and recorded in `data/README.md`: fourteen division rows carry their first group's code (division 10 typed `10.0`, so `10` did not exist), and Latin `x` stands for Cyrillic `х` in 92 names. **A Macedonian section letter is not the Latin one** (manufacturing is `C`, written `В`) — `resolve_nace` takes either. `normalise()` is total: any dict at all produces a profile, unresolved answers are None, and None is unclear. Acceptance: 36 intakes in `tests/fixtures/intake/profiles.yaml`. Left open: geography is still out of the rule vocabulary (see §8), and the demo still uses its own 13-municipality list |
| 21.09 | Bilingual OCR | `git log --grep "Albanian"` | The other half of D9. `mkd` cannot read Albanian, so every bilingual Economy call was flagged on every page and extraction indexed nonsense. Tesseract already segments the two languages into **separate blocks**, so a page with an unreadable block is re-read with `sqi` and whole blocks are swapped where the gap is unambiguous. Over all 20 pages of both calls the block sets matched and no block was within the margin; call 1 end to end: mean 71.03 → 90.31, review reasons **12 → 2**. Cost 155 s → 263 s (1.7×). `sqi` and `eng` added to the image. **D9 is now closed.** New: a model can quote Albanian into a criterion — a second reason for D7's named reviewer |
| 21.09 | OCR `%` fix | `git log --grep "percent"` | Out of roadmap order (s21 blocked on D1/D2). `mkd` has no `%`, so every OCR'd rate was a wrong number that passed the verbatim check. Fixed by a second `mkd+eng` pass over the same image, matched **by box**, carrying across nothing but `%`. 6 of 6 rates on the IPARD fixture; diffed against the single pass, those six tokens were the only changes in three pages. `NORMALISER_VERSION` → `2026-09-21.1`. **Bilingual MK/AL confidence (the other half of D9) untouched** |
| 13.09 | P1 s6–s10 | `7b86575`…`cf7f80a` | Reconnaissance, gateway + scrubber, snapshots, normaliser + OCR, extraction schema |
| 16.09 | P1 s11 | `f7da509` | AV fetcher end to end (FITR unreachable from datacenters) |
| 16.09 | P1 s12 | `ee05448` | Chunker, local embeddings, hybrid retrieval |
| 16.09 | Demo | `ce8c9ed` | Whole platform clickable on invented calls; user tried it and approved |
| 16.09 | P1 s13 | `ae67c40` | EU portal fetcher; scope is D10 (39 topics). Call-document PDFs not extracted |
| 16.09 | P1 s14 | `bc6848e` | `flask ingest health` + healthchecks.io; delivery drill waits for the VPS |
| 16.09 | P1 s15 | `4ad9ef6` | `/admin` review queue; approval re-checks citations, fills prefilter columns. Not in production until D11 |
| 16.09 | Handoff | `01c46f0` | This file; `ops/dev/seed_review_queue.py` |
| 18.09 | P1 s20 | `git log --grep 'session 20'` | IPARD: call page is the call (notice → published updates one call); ranking = out of scope and closed; tables routed by a note on every item. Live: 3 calls (02/2024 published but never ranked, deadline 20.12.2024). **Found: `mkd` OCR cannot read `%`** — fixed 21.09 |
| 16.09 | P1 s19 | `git log --grep 'session 19'` | Skopje via generic `municipal.py` + `options` in sources.yaml (the one change outside sources/). Live: 1 open call, OCR 92.75 |
| 16.09 | P1 s18 | `git log --grep 'session 18'` | Economy fetcher: call text only; empty listing is normal; Livewire tokens stripped. Found: bilingual MK/AL PDFs fail the D9 OCR confidence rule on every page — fixed 21.09 |
| 16.09 | P1 s17 | `git log --grep 'session 17'` | FITR re-checked from the host: still no TCP connection. Slot deferred, nothing built |
| 16.09 | P1 s16 | `git log --grep 'session 16'` | Manual entry by URL: `/admin/rachen-vnes` → RQ job (the first one) → pipeline; failures answer in the queue. Live-checked through the real worker |

## 3. What is built, in one screen

- `app/ingestion/` — `http.py` polite client (robots, UA, rate) → `fetcher.py` base + `sources/`
  (`av.py`, `eu_portal.py`) → `snapshots.py` content-hashed store → `normalise/` (HTML, PDF+OCR,
  DOCX; offset-stable) → `extract.py` (quotes located in code) → `pipeline.py` (unpublished call +
  review item; never publishes) → `health.py` (failing / not_running / quiet).
- `app/ai/` — `gateway.py` is the only provider path; scrubs; content-hash cache; invalid → review.
- `app/retrieval/` — chunker, local embedder, hybrid search.
- `app/matching/` — `operators.py` vocabulary, `hard_filter.py` interpreter + `prefilter_columns`,
  `taxonomy.py` verdicts, `reference.py` over `data/` (activities, municipalities, regions),
  `normalise.py` stage 0 (intake answers → `Profile`, every number a `Range`), `intake.py` the
  questionnaire (the eleven questions, their validation, and the labels that say a profile back),
  `stage1.py` the SQL candidate filter and the interpreter over a call's approved criteria.
  Scoring (s27) and verification (s29) are still to come.
- `evals/` — the measurement (P2 s25). `harness.py` loads `profiles/` (ten applicants),
  `fixtures/` (five frozen calls + their documents) and `cases/` (expected verdicts, empty until
  s26), writes the frozen registry into PostgreSQL in a rolled-back transaction, runs stage 1 and
  scores it. `run.py` is the gate (`--worksheet` writes the blank case files). Fixtures are rebuilt
  by `ops/dev/freeze_eval_fixtures.py`, never hand-edited.
- `data/` — versioned reference data, rebuilt only by `ops/dev/import_reference_data.py`
  (`uv run --with xlrd …`), provenance and repairs in `data/README.md`.
- `app/ingestion/sources/economy.py`; `ipard.py` (call page = primary document, stages by file label); `municipal.py` registers one fetcher per `sources.yaml` entry
  with `options.kind: municipal_listing` (Skopje today).
- `app/ingestion/sources/manual.py` — pasted URLs; `run_entry` (always answers in the queue),
  `job` (RQ), `enqueue`. The only RQ job so far; queue `ingest`.
- `app/review/extraction.py` — every review decision. `app/web/admin/` only renders and posts
  (queue, item, manual entry form).
- `app/heartbeat.py` — healthchecks.io pings. `app/cli.py` — `flask ingest …` (what cron runs).
- `app/web/intake/` — `/profil` (the form), `/profil/dejnosti` (the HTMX activity picker),
  `/profil/pregled` (what the answers were read as). Templates in `templates/intake/`;
  `_form.html` is the shared partial `/demo/profil` includes. Registered **everywhere**, including
  production — it is the first real customer screen. `templates/base.html` is the site shell.
- `app/web/csrf.py` — one CSRF check; `csrf.protect(bp)` is called by `/admin` and `/profil`.
- `app/web/demo/` — simulated; **replace, do not extend**. Intake and stage 0 are no longer
  simulated: `/demo/profil` renders the real form and `engine.py` runs the real `normalise`.

## 4. Waiting on the user

| # | Decision | Blocks |
|---|---|---|
| D1 | Report price | P1 s21 demand test |
| D2 | Domain and brand | P0.5 s4 deploy, transactional email, magic link |
| D10 | EU portal scope — default in code, user to confirm or widen | first EU approvals |
| D11 | Operator sign-in — recommended SSH tunnel, then magic link at s44 | production admin |
| D7 | Named Albanian reviewer — **now bites earlier than `sq` shipping** | since 21.09 a model can quote real Albanian into a criterion, and a reviewer who does not read Albanian cannot check it (`sources.md` §6.11) |
| — | **Whether to build s27 before s21** — the roadmap's own line; s26 is done and s27 is technically free | P2 s27 onwards |
| — | healthchecks.io account + two checks, then `flask ingest health --drill` | proving alerts reach them |
| — | Model API key in the dev/prod environment | real extraction runs (dev runs fail "processing") |

Ask with `AskUserQuestion` only for decisions that are genuinely theirs; otherwise pick the
conservative default, record it in `docs/decisions.md`, and say so in the report.

## 5. Environment facts that cost time to rediscover

- **The dev stack is already running** in Docker (`./run.py --detach`): web on port 8080 through
  Caddy, Postgres on `localhost:5432`, live reload. Browser URL:
  `https://$CODESPACE_NAME-8080.app.github.dev` (port private to the user).
- **Containers reach the internet now** (16.09.2026: the worker fetched economy.gov.mk). The README
  troubleshooting note about iptables applies if that changes. Live probes are still simplest on
  the host with `uv run python`.
- **The RQ worker does not reload code**: `docker compose restart worker` after changing anything it
  imports. The web container reloads itself (a request during the reload gets a 404).
- A new source row in `config/sources.yaml` reaches the dev DB only after
  `uv run flask --app "app:create_app()" ingest sync-sources`.
- **Tests run against the development database** inside a transaction that is rolled back. Fixtures
  delete what they need to start clean. **Clear `ModelCall`/`ModelCallPayload` in any fixture that
  scripts model replies**: the gateway's content-hash cache otherwise replays a stored reply
  (bit s15 after the dev DB held real calls).
- **A backgrounded `pytest … | tail` always exits 0**: read the summary line for `failed`, never
  the exit code.
- **Run the full suite to a log file**: `uv run pytest -p no:cacheprovider -rfE > log 2>&1; echo
  exit=$?`, then read the last line (`671 passed, 3 xfailed` on 22.09). `addopts = "-q"` already, so
  an extra `-q` or `-rN` hides the summary, and filtering the output with `grep -v` can hide a
  `FAILED` line — both happened on 22.09 and nearly let a drift test's failure through.
- The full suite takes several minutes (retrieval paraphrase tests embed with the local model): run it
  with `run_in_background` and wait on the notification.
- CLI outside cron: `uv run flask --app "app:create_app()" ingest <command>`. Scripts that import
  `app` need `PYTHONPATH=.`.
- Dev data: `PYTHONPATH=. uv run python ops/dev/seed_review_queue.py` fills `/admin` from fixtures.
  The dev DB currently holds items 347–349 from it, and AV runs that failed for lack of an API key
  (so `flask ingest health` reports AV failing; that is true).
- **The chrome-devtools MCP cannot start here (no X server).** Visual checks use the Playwright
  headless shell and Node over CDP instead — see §7 (the sandbox works; do not pass `--no-sandbox`, auto mode refuses it).
- **After a Codespace restart the containers cannot reach each other** (Caddy 503 "no upstreams",
  worker restarting on a Redis timeout) unless the stack was started by `./run.py`. Add the three
  `iptables-legacy` rules in README troubleshooting (18.09.2026), or restart with `./run.py`.
- **OCR now costs ~1.7× what it did before 21.09** (measured: 155 s → 263 s on a 12-page bilingual
  call). A page is read again for the `%` if it contains a digit, and again with `sqi` if it has a
  block below confidence 60 — so a clean Macedonian page still pays once and a bilingual one pays
  three times. `TesseractOcr(percent_pass=None, foreign_pass=None)` is the old behaviour when a probe
  needs to be quick. A first IPARD run is ~15-20 minutes; run it with `run_in_background`.
- **`tesseract-ocr-sqi` and `tesseract-ocr-eng` are in the image but may not be on a dev host.**
  Install with `sudo apt-get install -y tesseract-ocr-sqi tesseract-ocr-eng` before any live OCR
  probe, or the foreign pass is silently skipped (`TesseractOcr.installed()` guards it) and a
  bilingual page reads as it did before the fix.
- **Tests that quote OCR text use `RecordedOcr`** (`tests/test_extract_schema.py`), replaying a
  recorded Tesseract output (`tests/fixtures/skopje/call-12149.ocr.json`); OCR differs between
  Tesseract versions. Tesseract 5.3.4 with `mkd` is installed on the host and in the image.
  The `%` and bilingual tests replay recorded **word tables** (`ipardpa/call-32.words.json` and
  `economy/call-1.words.json`, made by `ops/dev/record_ocr_words.py`) because both repairs match
  boxes, not text. The Economy PDFs are too large to commit; both re-fetched on 21.09 and still hash
  as `tests/fixtures/README.md` records, and their real URLs are inside the committed `call-N.html`.
- Hand-written extraction cassettes live in `tests/cassettes/extract_call/`; adding one to `CASES`
  in `test_extract_schema.py` also runs it through the scrubbing gateway and the retrieval tests.
- Pillow is in the venv (`uv run python`), useful for cropping tall screenshots before reading them.
- **Reference data is rebuilt, never edited**: `uv run --with xlrd python ops/dev/import_reference_data.py`.
  `xlrd` is deliberately not a project dependency — it reads two 2003-era `.xls` files once a decade.
  The run refuses to write if either upstream archive's hash has moved (`data/reference.yaml`);
  `--accept-new-hashes` is how you say you looked. `stat.gov.mk` serves no robots.txt, so the polite
  client allows it; it is slow but reachable from the host.
- **`data/` is bind-mounted in dev and `COPY`d into the image** (`docker-compose.dev.yml`,
  `Dockerfile`). A re-import is visible after `docker compose restart web worker`; production needs a
  rebuild. `/data/` used to be in `.gitignore` as "local data" — it never was, and s22 removed it.
- **The dev database can be behind the migrations.** `uv run alembic current` vs `alembic heads`;
  it was one revision behind on 22.09 and autogenerate refuses to run until you upgrade. After any
  migration: `uv run alembic upgrade head` then `./ops/dump-schema.sh` (which needs the stack up).
- **Alembic's autogenerated migrations do not pass ruff as emitted** — the template imports every
  custom type in `app/models/` whether the migration uses it or not. `F401` is in the
  `migrations/versions/*` per-file-ignores for that reason; run `uv run ruff format` on the new file.
- **A DB test that publishes calls must clear published calls first** (`tests/test_stage1.py`'s
  `registry` fixture): the development database holds rows from earlier sessions, and stage 1 selects
  across the whole registry, so anything left published joins every candidate set.
- **HTMX is vendored**, not loaded from a CDN: `app/web/static/js/htmx.min.js`, version 2.0.10,
  `sha256 71ea67185bfa8c98c39d31717c6fce5d852370fcdfd129db4543774d3145c0de` (the same bytes from
  jsdelivr and unpkg). 50 KB raw, served gzipped by Caddy. Fonts are vendored for the same reason
  (no visitor IP to a US processor, `architecture.md` §8); a CDN link would undo that.
- **The activity picker is the only HTMX on the site.** Two swaps and no JavaScript of our own:
  typing swaps `#nace-results`, picking re-renders the whole `#nace-field` (`outerHTML`), which is
  how the value gets written into the input without a line of script. With JS off it is a text
  input and a typed code still resolves — keep it that way.
- **The evaluation gate needs the stack up and takes seconds**:
  `PYTHONPATH=. uv run python evals/run.py`. It deletes every published call — inside a transaction
  it rolls back — so the frozen fixtures are the whole registry, and it refuses to run against a
  production database. It exits 0 since s26; exit 1 means something blocks.
- **After a Codespace restart docker can refuse to start a container** with "RWLayer of container …
  is unexpectedly nil" (seen 22.09.2026). `docker rm -f` the five containers and run `./run.py
  --detach` again; the data is in named volumes (`grants_postgres-data` and friends), so nothing is
  lost. This is a different failure from the iptables one below it and the cure is not the same.
- **The admin renders scanned pages with `pdftoppm`** (poppler), which is in the image and on this
  host. Without it the review item simply shows no image — `can_render_pages()` guards it, so a dev
  host missing poppler is not a broken page. A page costs ~0.4 s and ~200 KB at 110 dpi.
- **`ops/dev/bench_stage1.py` takes about two minutes and leaves nothing behind** (one rolled-back
  transaction, and it refuses a production database). Re-run it after any change to stage 1's SQL or
  to how a call's criteria are loaded, and compare with the table in `matching.md` §3.
- `sleep` in the foreground is blocked; wait with `run_in_background` until-loops.

## 6. How a session is finished

1. Code with docstrings that explain *why*, matching the surrounding style.
2. Tests: unit tests without the database where possible; database tests via the rollback fixtures;
   acceptance of the roadmap row proven by a test whenever it can be.
3. `uv run ruff check . && uv run ruff format --check .` and the full suite green (the strict
   `xfail`s listed in `KNOWN_MISSES` in `test_retrieval_paraphrase.py` are expected).
   **Matching touched → also run the gate**, `PYTHONPATH=. uv run python evals/run.py`, and read the
   properties: they fail before any case does. Read the **over-claimed** lines too — they do not
   block, but they are the nearest thing to a false eligible.
4. UI touched → load the design-system skill first; afterwards the §7 check at 375/768/1440, fix,
   re-check. Keep `/demo/vodic` rows true.
5. Docs in the same commit: roadmap row marker (*built dd.mm.yyyy: …*), README status line, and
   whichever of `sources.md` / `decisions.md` / `runbook.md` / `risks.md` the session changed.
   **Update this file** (§2 log, §4, §5, §8).
6. Commit only the session's files — `git add <paths>`, never `-A` (the user's `CLAUDE.md` edit).
   Message: `P1 session N: <what>`, a body of short bullets, ending
   `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Then `git push`.
7. Report to the user: what was built, what the acceptance proved and what it did not, decisions
   needed from them, and the next session.

## 7. Visual check without the MCP

```bash
CH=~/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell
"$CH" --disable-gpu --hide-scrollbars --window-size=375,3000 \
  --screenshot=/path/in/scratchpad/page-375.png http://localhost:8080/admin/
```

Console messages, failed requests and horizontal overflow per width, over CDP (Node 24 has a global
`WebSocket`). Save as `cdp_check.mjs` in the scratchpad, run `node cdp_check.mjs <url>...`:

```js
import { spawn } from "node:child_process";
const CH = process.env.HOME + "/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell";
const proc = spawn(CH, ["--disable-gpu", "--remote-debugging-port=9333", "about:blank"], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let targets;
for (let i = 0; i < 50; i++) { try { targets = await (await fetch("http://127.0.0.1:9333/json/list")).json(); break; } catch { await sleep(200); } }
const ws = new WebSocket(targets.find((t) => t.type === "page").webSocketDebuggerUrl);
await new Promise((r) => (ws.onopen = r));
let id = 0; const pending = new Map(); const events = [];
ws.onmessage = (m) => { const msg = JSON.parse(m.data); if (msg.id) pending.get(msg.id)?.(msg); else events.push(msg); };
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
for (const d of ["Runtime", "Log", "Network", "Page"]) await send(`${d}.enable`);
for (const url of process.argv.slice(2)) for (const width of [375, 768, 1440]) {
  events.length = 0;
  await send("Emulation.setDeviceMetricsOverride", { width, height: 900, deviceScaleFactor: 1, mobile: width < 768 });
  await send("Page.navigate", { url }); await sleep(1500);
  const v = (await send("Runtime.evaluate", { returnByValue: true, expression: "({sw: document.documentElement.scrollWidth, iw: innerWidth})" })).result.result.value;
  const logs = events.filter((e) => /consoleAPICalled|entryAdded|exceptionThrown/.test(e.method));
  const failed = events.filter((e) => e.method === "Network.loadingFailed" || (e.method === "Network.responseReceived" && e.params.response.status >= 400));
  console.log(`${width}px ${url}: overflow=${v.sw > v.iw} console=${logs.length} failed=${failed.length}`);
}
ws.close(); proc.kill();
```

`scrollWidth` 15px under the width at 768/1440 is the scrollbar, not overflow. A POST-only state
(a refused form) can be captured by saving the response HTML with `curl` (cookie jar + CSRF token
from the page), inserting `<base href="http://localhost:8080/">`, and screenshotting the file.

## 8. Carried forward — do not lose these

- **EU call documents are still not extracted** (`sources.md` §6.6), so an EU call's criteria remain
  incomplete by construction — but that is now carried in data: `call.eligibility_gap` is set on
  every EU topic and `app/matching/stage1.py` refuses `eligible` and `likely_eligible` for a call
  holding it. **When those PDFs are finally fetched and extracted, the fetcher must stop setting the
  gap**, or every EU call stays capped forever.
- **Cross-language retrieval**: a Macedonian label over an English quote retrieves poorly across
  documents; standard clauses repeat across calls; a condition stated twice ranks its other chunk first. All three are strict xfails in `KNOWN_MISSES` (`tests/test_retrieval_paraphrase.py`); P2 s30 decides.
- **Stage-1 SQL** (P2 s24) must treat the prefilter columns as a superset filter only
  (`hard_filter.prefilter_columns` docstring). `min/max_company_age_months` are exact numbers; how a
  banded profile is compared to them is s24's to get right.
- **Removing an approved criterion** is refused once match outcomes reference it (the FK cascades into
  delivered reports). A proper "retire" needs a column; decide when P2 writes outcomes.
- **Snapshots normalised before 21.09.2026 still hold the wrong rates and the garbled Albanian.**
  Normalised text is written once and an unchanged document is never re-fetched, so this does not
  heal on its own. **What exists now** (22.09): `flask ingest stale-text` lists every such snapshot
  with what cites it and exits non-zero if a published call does, and `/admin` warns the reviewer on
  the item, per document, what to distrust. **What does not exist**: any way to re-read them.
  Clearing `normalised_text` moves every offset citing it, so the remedy is to delete the snapshot
  and let the next run fetch it again — a deliberate job with its own session. In the dev DB it is
  three snapshots, nothing published on them. **P2 s29 must not write verdicts from a snapshot the
  command still lists**, and the decision is recorded (`decisions.md`, "Decided in code").
  `normaliser_version == 2026-09-21.2` is still the test for "read by the current normaliser";
  nothing was ingested under `.1`.
- **IPARD 02/2024** was never given a ranking on the site, so it stays in scope; the pipeline closes
  it from its extracted deadline, a reviewer rejects it. Notice-only calls stay ANNOUNCED until rejected.
- **D9 rule 1 is complete since 22.09**: the admin marks OCR quotes, links the document *and*
  renders the cited page beside the quote. What is still missing is narrower — the quote is not
  highlighted *on the image* (the OCR word boxes are not stored with the text), so on a dense page
  the reviewer still has to find the passage by eye.
- **A closed review item is never re-asked** for the same snapshots. A retry path (e.g. after a prompt
  change) does not exist yet; the natural place is P2 s34 or a prompt-version bump.
- **Geography stays out of the rule vocabulary — decided at s24** (`matching.md` §3). Adding
  `region_code` to `FIELDS` lets an extracted criterion *exclude* on location, which needs a new
  extraction prompt version with an evaluation run behind it, so it waits for s25–26's harness. A
  location condition stays `applicant_attest` and `prefilter_columns` still returns an empty
  `allowed_regions`. **What changed: stage 1a's clause is written and tested**
  (`allowed_regions && ARRAY[region_code, municipality_code]`), so filling the column is the only
  work left when the harness exists.
- **Град Скопје is not the Skopje region**, and the answer is settled: a City of Skopje call lists
  its ten municipality codes in `allowed_regions`, and stage 1a's overlap handles that with no
  special case (tested). Nothing fills the column yet — see the geography item above.
- **The reference-data version is not yet recorded on anything.** `reference.version()` exists and
  `Profile.reference_version` carries it, but no `match_run` row is written until s27. A report
  delivered before that is not reproducible against the classification that produced it.
- **The published classification is maintained by hand and will break again.** Two systematic
  defects were repaired in the 22.09 import (`data/README.md`); `tests/test_reference_data.py` is
  what catches the next one, so run it after any re-import and read the failure rather than
  relaxing it.
- **The three-minute acceptance for s23 is not proven.** The form is built and `/profil/pregled`
  reports how many seconds the completion took (the clock starts when the form is first rendered in
  a session), but only the user can run it as a real person would. Do that once before s28 uses the
  profile for anything, and if it is over three minutes the thing to cut is questions, not hints.
- **An attestation the profile already contradicts still reads `likely_eligible`** (found by s26:
  the only 3 over-claims). AV's "a permanent employee for six months" is `applicant_attest`, so a
  company founded ≤ 5 months ago or with 0–1 employees is told it only has to confirm it. Not a
  false eligible — the attestation is genuinely outstanding — but the customer is shown a condition
  their own answers make unlikely as a formality. The fix belongs to s27/s29 (an attestation whose
  subject the profile answers, and answers doubtfully, caps at `needs_verification`), not to the
  extraction: making it `hard_structured` would let a rule *exclude* on a headcount band.
- **Geography now has a number**: 7 of the 19 mismatches are Skopje-only rows where the expected
  verdict is `not_shown` and stage 1 says `needs_verification`. This is the evaluation run the
  geography decision (below) was waiting for; filling `allowed_regions` should turn exactly those
  seven, and the gate will say if it turns anything else.
- **A craftsman is in the profile but in no rule.** The form exists since 22.09 (`decisions.md`),
  but `prompts/extract_call/2026-09-13.1.md` does not list `craftsman`, so p11's Economy and Skopje
  rows stay under-decided. The next prompt version should add it **together with** a craft-permit
  question on the intake — alone it would exclude permit-holding companies from Skopje's call by
  rule. Not asked yet: whether a company or sole trader holds a craft permit (p07/p08's verdicts).
- **The frozen Economy criteria are incomplete**: the call text also excludes anyone subsidised by
  the ministry in 2024 or 2025, exempts craftsmen and craft-permit holders from the sector and
  headcount conditions (§2.2 of the call), lowers the headcount to one for a woman-owned company,
  and excludes craftsmen taxed at a flat rate. None of the four is a criterion. The cases were
  written against the call's text, so they stay right; the fixture is what is short, and it is
  rebuilt from the cassette, not edited.
- **The suite's clock predates one of its calls**: `as_of` is 01.06.2026 and the AV call was
  published 05.08.2026. Nothing uses `published_at` yet so no verdict moves, but the day something
  does, move the clock or the call, not the verdict.
- **The IPARD notice row disagrees with the design, harmlessly**: the user's truth is
  `needs_verification`, stage 1 never shortlists an advance notice (`not_shown`, tested). Neither
  counts in the gate. Whether an announcement appears in the shortlist at all is s28's to decide.
- **A frozen eval fixture is a hand-written extraction, not a real approval.** The criteria in
  `evals/fixtures/*/call.yaml` come from `tests/cassettes/extract_call/`, which earlier sessions
  wrote by hand. They are read and plausible, but no reviewer has ever approved them in `/admin`.
  When real approvals exist in the database, re-freeze from those instead — the script is the place
  to change, and the cases' reasons have to be re-read if a criterion changes.
- **Only one call in the suite exercises stage 1a's filter at all**: the Economy call's minimum age.
  Every other frozen call has an empty prefilter (their structured criteria are `not_in`, which the
  SQL cannot express), so the superset property is checked on one pair out of forty. It will get
  stronger on its own as calls with `in`/`prefix_in` criteria are approved — but do not read "1
  checked, ok" as coverage of stage 1a.
- **Nothing writes an `applicant_profile` row yet.** `/profil` keeps the answers in the signed
  session cookie (`decisions.md`, "Decided in code"). The order flow (P4) is where an account and a
  versioned row have to appear, together, or a delivered report will not be reproducible against the
  profile that produced it — which is the same hole `reference.version()` has below.
- **The `/demo` forms carry no CSRF token** while `/admin` and `/profil` do (`app/web/csrf.py`).
  Acceptable only because the demo is registered outside production and writes nothing but the
  visitor's own session cookie. `csrf.protect(bp)` plus a hidden field in the eleven demo forms is
  the fix, the day any of them touches the database.
- **Stage 1a's array clauses do not use the GIN indexes, and it does not matter** — measured
  22.09.2026, `ops/dev/bench_stage1.py`, table in `matching.md` §3. The SQL is 66 ms over 20.000 open
  calls; a sequential scan is the right plan while most calls are national, because then every
  profile matches most rows and no index on those columns can be selective. **What does cost is
  everything after the SQL**, all of it per candidate: 358 ms to hydrate 13.311 calls, **2 s to load
  their criteria**, 882 ms in the interpreter — `stage1.run` is 3,3 s there and 274 ms at 2.000
  calls. So the budget breaks between 2.000 and 20.000 open calls and the fix is **rank before
  judging** (P2 s28), not an index. One caveat kept: the planner estimates 9 rows where 13.311 match,
  so the day this query is joined or wrapped in a subquery, that estimate will pick a bad plan.
- **`reviewer_id`** stays empty until operator accounts exist (D11).
- **D11 implementation** (if SSH tunnel): register `/admin` in production only on an internal port,
  and make Caddy refuse `/admin` from outside.
- **AV `staleness_sla_days: 45`** may raise quiet alerts in December–January.
- **FITR** is still unreachable from datacenters; check from the VPS once it exists.
- **Manual entry normalises the whole page body** (no content selector is known for an arbitrary
  site), so navigation text can reach citations; the reviewer is the guard. New chunks for a manual
  entry are embedded by the next `flask ingest due` (its index step), not by the job.
- **Manual URL safety** refuses non-http(s), bare hostnames, `localhost`/`.internal`/`.local` and
  non-global IP literals; it does not resolve DNS, so a public name pointing inward is not caught.
  Acceptable while the admin is operator-only (D11).
- The alert **delivery drill** (`runbook.md` §4) and the backup heartbeat both wait for the VPS.
