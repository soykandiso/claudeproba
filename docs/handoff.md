# Handoff — read this first when resuming

The working memory of this project across Claude Code sessions. `CLAUDE.md` holds the rules,
`docs/roadmap.md` the plan; this file holds **where we actually are, what was learned, and how a
session is finished**. It is updated at the end of every roadmap session, in the same commit.

**Last updated:** 22.09.2026, after P2 s24 (stage 1 over the registry). s22, s23 and s24 were all
taken out of order because P1 s21 is still blocked on D1 and D2; the user chose to carry on down P2
rather than decide D1/D2 first.

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
| P2 | **s22, s23 and s24 done 22.09**, all out of order while s21 is blocked. `data/` holds the activity classification, the 80 municipalities and the 8 planning regions as versioned files; `app/matching/normalise.py` is stage 0; `app/matching/intake.py` is the questionnaire and `/profil` (`app/web/intake/`) is the first real customer screen. The demo now renders the same form and runs the same stage 0. `app/matching/stage1.py` is stage 1 over the real registry, with `call.eligibility_gap` carrying invariant 3 for calls whose conditions are not all read. **Next P2 row is s25 (evaluation harness skeleton), then s26, the user's own evening of marking ~40 expected verdicts.** s26 cannot be done by anyone else, and s27's scoring should not be built before it. Ask the user: decide D1/D2 and do the demand test, or do s25 and then sit down with s26 |
| Demo stage | `/demo` clickable on invented data (commit `ce8c9ed`); `/demo/vodic` maps features to sessions and must be kept true when a session makes something real |

s21 stays the commercial test and the roadmap still says **not to build P2 as specified if it comes
back negative**. s22, s23 and s24 are the rows that cost nothing either way: correct reference data,
a form a company can describe itself in, and a filter that cannot silently exclude anyone are worth
having whatever the answer is. **s27 is where that stops being true** — scoring weights are tuned to
a product the demand test may reshape. s25 and s26 sit in between: the harness is cheap and s26 is
the user's own judgement, which is worth having early either way.

### Session log

| Date | Session | Commit | Outcome, and what it left open |
|---|---|---|---|
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
- `sleep` in the foreground is blocked; wait with `run_in_background` until-loops.

## 6. How a session is finished

1. Code with docstrings that explain *why*, matching the surrounding style.
2. Tests: unit tests without the database where possible; database tests via the rollback fixtures;
   acceptance of the roadmap row proven by a test whenever it can be.
3. `uv run ruff check . && uv run ruff format --check .` and the full suite green (the strict
   `xfail`s listed in `KNOWN_MISSES` in `test_retrieval_paraphrase.py` are expected).
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
- **Snapshots normalised before 21.09.2026 hold the wrong rates and the garbled Albanian.** The `%` fix is live
  (`sources.md` §6.10) but normalised text is written once and never recomputed, and an unchanged
  document is never re-fetched (content hash), so a document ingested under `2026-09-13.1` keeps
  "755" forever. **There is no re-normalisation path and nothing warns a reviewer** that an old
  snapshot predates the fix — `raw_snapshot.normaliser_version` is the only way to tell. In the dev DB
  that is the s20 IPARD run. Nothing has reached a customer, so the cheap answer is to delete those
  snapshots before launch rather than build a migration; decide it before P2 s29 writes verdicts from
  them. The two 21.09 fixes are separate bumps -- `2026-09-21.1` restored `%` only, `2026-09-21.2`
  added the Albanian blocks -- so `normaliser_version == 2026-09-21.2` is the test for "read by the
  current normaliser". Nothing was ingested under `.1`.
- **IPARD 02/2024** was never given a ranking on the site, so it stays in scope; the pipeline closes
  it from its extracted deadline, a reviewer rejects it. Notice-only calls stay ANNOUNCED until rejected.
- **D9 rule 1 is only half built**: the admin marks OCR quotes and links the document, but does not
  show the page image beside the quote.
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
- **Nothing writes an `applicant_profile` row yet.** `/profil` keeps the answers in the signed
  session cookie (`decisions.md`, "Decided in code"). The order flow (P4) is where an account and a
  versioned row have to appear, together, or a delivered report will not be reproducible against the
  profile that produced it — which is the same hole `reference.version()` has below.
- **The `/demo` forms carry no CSRF token** while `/admin` and `/profil` do (`app/web/csrf.py`).
  Acceptable only because the demo is registered outside production and writes nothing but the
  visitor's own session cookie. `csrf.protect(bp)` plus a hidden field in the eleven demo forms is
  the fix, the day any of them touches the database.
- **Stage 1a's array clauses do not use the GIN indexes**, and cannot while "empty array means no
  restriction" is expressed as `cardinality = 0 OR overlap` (`matching.md` §3). The partial index
  `ix_call_open` does the narrowing and the arrays filter what survives. Fine for hundreds of open
  calls, **never measured at scale** — check it before blaming anything else if s28 misses its
  3-second budget.
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
