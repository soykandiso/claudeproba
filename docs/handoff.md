# Handoff — read this first when resuming

The working memory of this project across Claude Code sessions. `CLAUDE.md` holds the rules,
`docs/roadmap.md` the plan; this file holds **where we actually are, what was learned, and how a
session is finished**. It is updated at the end of every roadmap session, in the same commit.

**Last updated:** 16.09.2026, after P1 s18, before P1 s19.

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
| P1 | s6–s16 done (s11 built AV instead of FITR). s17 deferred: FITR still unreachable (checked 16.09). s18 Economy done. **Next: s19, Град Скопје** (scanned PDFs, tenders mixed into the listing: `sources.md` §1, §6.2–6.3) |
| Demo stage | `/demo` clickable on invented data (commit `ce8c9ed`); `/demo/vodic` maps features to sessions and must be kept true when a session makes something real |

Then s18 Economy, s19 Skopje, s20 IPARD, s21 demand test. P2 starts at s22.

### Session log

| Date | Session | Commit | Outcome, and what it left open |
|---|---|---|---|
| 13.09 | P1 s6–s10 | `7b86575`…`cf7f80a` | Reconnaissance, gateway + scrubber, snapshots, normaliser + OCR, extraction schema |
| 16.09 | P1 s11 | `f7da509` | AV fetcher end to end (FITR unreachable from datacenters) |
| 16.09 | P1 s12 | `ee05448` | Chunker, local embeddings, hybrid retrieval |
| 16.09 | Demo | `ce8c9ed` | Whole platform clickable on invented calls; user tried it and approved |
| 16.09 | P1 s13 | `ae67c40` | EU portal fetcher; scope is D10 (39 topics). Call-document PDFs not extracted |
| 16.09 | P1 s14 | `bc6848e` | `flask ingest health` + healthchecks.io; delivery drill waits for the VPS |
| 16.09 | P1 s15 | `4ad9ef6` | `/admin` review queue; approval re-checks citations, fills prefilter columns. Not in production until D11 |
| 16.09 | Handoff | `01c46f0` | This file; `ops/dev/seed_review_queue.py` |
| 16.09 | P1 s18 | `git log --grep 'session 18'` | Economy fetcher: call text only; empty listing is normal; Livewire tokens stripped. Found: bilingual MK/AL PDFs fail the D9 OCR confidence rule on every page |
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
  `taxonomy.py` verdicts. Scoring and verification are P2.
- `app/ingestion/sources/manual.py` — pasted URLs; `run_entry` (always answers in the queue),
  `job` (RQ), `enqueue`. The only RQ job so far; queue `ingest`.
- `app/review/extraction.py` — every review decision. `app/web/admin/` only renders and posts
  (queue, item, manual entry form).
- `app/heartbeat.py` — healthchecks.io pings. `app/cli.py` — `flask ingest …` (what cron runs).
- `app/web/demo/` — simulated; **replace, do not extend**.

## 4. Waiting on the user

| # | Decision | Blocks |
|---|---|---|
| D1 | Report price | P1 s21 demand test |
| D2 | Domain and brand | P0.5 s4 deploy, transactional email, magic link |
| D10 | EU portal scope — default in code, user to confirm or widen | first EU approvals |
| D11 | Operator sign-in — recommended SSH tunnel, then magic link at s44 | production admin |
| D9 (reopened) | OCR confidence on bilingual MK/AL documents | noise in the queue for every Economy call; extraction reads garbled Albanian |
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
- The full suite takes several minutes (retrieval paraphrase tests embed with the local model): run it
  with `run_in_background` and wait on the notification.
- CLI outside cron: `uv run flask --app "app:create_app()" ingest <command>`. Scripts that import
  `app` need `PYTHONPATH=.`.
- Dev data: `PYTHONPATH=. uv run python ops/dev/seed_review_queue.py` fills `/admin` from fixtures.
  The dev DB currently holds items 347–349 from it, and AV runs that failed for lack of an API key
  (so `flask ingest health` reports AV failing; that is true).
- **The chrome-devtools MCP cannot start here (no X server).** Visual checks use the Playwright
  headless shell and Node over CDP instead — see §7.
- Pillow is in the venv (`uv run python`), useful for cropping tall screenshots before reading them.
- `sleep` in the foreground is blocked; wait with `run_in_background` until-loops.

## 6. How a session is finished

1. Code with docstrings that explain *why*, matching the surrounding style.
2. Tests: unit tests without the database where possible; database tests via the rollback fixtures;
   acceptance of the roadmap row proven by a test whenever it can be.
3. `uv run ruff check . && uv run ruff format --check .` and the full suite green (the one strict
   `xfail` in `test_retrieval_paraphrase.py` is expected).
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
"$CH" --no-sandbox --disable-gpu --hide-scrollbars --window-size=375,3000 \
  --screenshot=/path/in/scratchpad/page-375.png http://localhost:8080/admin/
```

Console messages, failed requests and horizontal overflow per width, over CDP (Node 24 has a global
`WebSocket`). Save as `cdp_check.mjs` in the scratchpad, run `node cdp_check.mjs <url>...`:

```js
import { spawn } from "node:child_process";
const CH = process.env.HOME + "/.cache/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-linux64/chrome-headless-shell";
const proc = spawn(CH, ["--no-sandbox", "--disable-gpu", "--remote-debugging-port=9333", "about:blank"], { stdio: "ignore" });
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

- **EU call documents are not extracted** (`sources.md` §6.6). Until they are, an EU call's criteria
  are incomplete by construction. **P2 s24 must not let such a call reach `eligible` or
  `likely_eligible`** (invariant 3); human approval is the only guard today.
- **Cross-language retrieval**: a Macedonian label over an English quote retrieves poorly across
  documents (strict xfail `CROSS_LANGUAGE_MISS`); P2 s30 decides the query for non-Macedonian text.
- **Stage-1 SQL** (P2 s24) must treat the prefilter columns as a superset filter only
  (`hard_filter.prefilter_columns` docstring). `min/max_company_age_months` are exact numbers; how a
  banded profile is compared to them is s24's to get right.
- **Removing an approved criterion** is refused once match outcomes reference it (the FK cascades into
  delivered reports). A proper "retire" needs a column; decide when P2 writes outcomes.
- **D9 rule 2 flags every bilingual MK/AL page** (`sources.md` §6.7). Fix in the normaliser (bump
  `NORMALISER_VERSION`), with a small test set of bilingual pages; not in a fetcher.
- **D9 rule 1 is only half built**: the admin marks OCR quotes and links the document, but does not
  show the page image beside the quote.
- **A closed review item is never re-asked** for the same snapshots. A retry path (e.g. after a prompt
  change) does not exist yet; the natural place is P2 s34 or a prompt-version bump.
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
