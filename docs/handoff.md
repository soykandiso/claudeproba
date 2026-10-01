# Handoff — read this first when resuming

The working memory of this project across Claude Code sessions. `CLAUDE.md` holds the rules,
`docs/roadmap.md` the plan; this file holds **where we actually are, what was learned, and how a
session is finished**. It is updated at the end of every roadmap session, in the same commit.

**Last updated:** 01.10.2026, after **DS4 — the intake on the components** (pushed: since DS2 the user asked that every session is committed, pushed and merged by Claude). Before it the same day, **DS3 — the component set**. Before it the same day, **DS2 — the design foundation** (first session on the user's Windows machine, stack run natively, §5). Before it the same day, **DS1 — the design audit** (`docs/design.md`), taken ahead of P2 s36/s37 at the user's choice because s36 needs a model key and this session (a claude.ai cloud container, not the Codespace) had none. Before it, 30.09: P2 s35 — the report as PDF. Same day: the **design phase (DS1–DS9)** was added to the roadmap after P2 at the user's request, and P2 s34 (reviewer decisions become evaluation cases). Before it: P2 s33 (the report review screen), P2 s32 (the report composer), P2 s31 (stage 3 on the worker), P2 s30 (retrieval
tuned for verification), P2 s29
(the verification pass and tier B), P2 s28
(the shortlist page at `/povici`), P2 s27
(stage 2 scoring, scoped with the user), the craftsman entity form (out of order, found by s26), P2 s26 — the 41 expected verdicts, marked with the user in one walk-through — stage 1 at scale, the OCR page image, the stale-text warning and P2
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
| P2 | **s22–s25 done 22.09**, all out of order while s21 is blocked. `data/` holds the activity classification, the 80 municipalities and the 8 planning regions as versioned files; `app/matching/normalise.py` is stage 0; `app/matching/intake.py` is the questionnaire and `/profil` (`app/web/intake/`) is the first real customer screen; `app/matching/stage1.py` is stage 1 over the real registry, with `call.eligibility_gap` carrying invariant 3. **`evals/` is the measurement** (s25): five frozen calls, ten boundary profiles, four properties checked on every run, and **since s26 marked cases: the gate is green** — 45 now, with p11 (0 false eligible, 0 false exclusion, 4 over-claimed, 16 under-decided). A registered craftsman is an entity type and a form on `/profil` since the same evening. **s27 is built, scoped** (`app/matching/stage2.py`, `config/weights/v1.yaml`): the user chose to carry on past the point the roadmap calls the end of "costs nothing either way", with the weights marked untuned and rank quality reported as not measurable. **s28 is built**: `/povici` (`app/web/shortlist/`, `app/matching/shortlist.py`) is the second real customer screen — the top ten, every quote found again before it is shown, a passage page per condition; `ops/dev/seed_shortlist.py` publishes the five frozen calls in dev so it has something to show. **s29 is built**: `app/matching/verify.py` and tier B (`evals/run.py --tier b`, green: 28 of 45 exact, 0 false eligible). **s30 is built** (23.09): stage 3 is shown the chunk a criterion cites first (`hybrid_retrieve(pin=…)`) and searches with the quote alone; `verify.call_retriever` is the production retriever and `evals/run.py --retrieval` measures it. **s31 is built** (24.09): `app/matching/deep.py` — one job per stored `applicant_profile` on the `analysis` queue; the top five verified, results, outcomes and evidence stored. Proven by tests, **not yet drilled through the live worker** (§4). **s32 is built** (24.09): `app/reports/compose.py` drafts the report from the stored run, the model writes cited explanation only, the lint and citation completeness block delivery, and the draft is a `report` review item; `deep.job` composes after the run. **s33 is built** (29.09): `/admin/izveshtaj/<id>` (`app/review/report.py`) — every quote marked in the stored text, the model's statements editable and re-checked, approval refused while `compose.blockers()` finds anything. **s34 is built** (30.09): `app/review/cases.py` + `flask review export-cases` (cron 02:45 UTC) write every rejected or edited extraction/report item to `evals/cases/from_review/<kind>-<id>.yaml`, once, nothing identifying; the harness loads and shape-checks them, scores none. **s35 is built** (30.09): `app/reports/render.py`, the approved report as PDF in our own fonts only, every check run again. **Still open in P2: s36** (tier C + cost per report — needs the model key) and **s37** (mobile/performance, may fold into DS9). |
| Design | **DS1 done 01.10** (out of order, before s36/s37): `docs/design.md`, 36 findings with an owner each, crops in `docs/design/ds1/`. Three are severity A — F10 (likely vs needs-verification marks identical in greyscale), F13 (passage page has no `last_verified_at`), F29 (a passed deadline reads as a plain date in the report/PDF). **DS2 built 01.10**: tokens are the only source of values (`tests/test_design_foundation.py`), `/stil` renders them, Source Serif 4 Italic cut for Macedonian and shown on `/stil` only. **Open in DS2: the user (or a native reader) signs off the italic on `/stil`.** **DS3 built 01.10**: `_components.html`, every component in every state on `/stil` (`?siv=1` greyscale); F10 closed (the four marks tell apart alone). **DS4 built 01.10**: the intake on the components; **its acceptance, the timed run under 3 minutes, is the user's to do**. **Next: DS5** (shortlist and passage; F13, a severity A, is there) |
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
| 01.10 | DS4 | `git log --grep 'DS4'` | **The intake on the components.** The refused form uses `c.error_summary` (links per field in form order, «Едно поле … да се поправи» / «N полиња … да се поправат», `autofocus`); every field is label, control, error, hint (F21, F22). `intake.age_words`: «7–8 години, основана 2018» on `/profil/pregled` (F23, review half; the report keeps months because `verify.applicant_shape` is the model's input — DS6). Purposes in sentence case (F24). Nav by blueprint (F19). Picker: `hx-indicator="#nace-field"` recedes the field and shows «Се пребарува…», a picked row is busy and disabled (`hx-disabled-elt`); both caught live with a MutationObserver, both on `/stil`. The review page says the time in minutes. **Found**: «пекар» finds nothing (НКД: «леб») — a synonym file in `data/` is the user's list to give (§4). **Not proven**: the timed run (a person's). Checked at 375/768/1440, console clean but the intended 422 |
| 01.10 | DS3 | `git log --grep 'DS3'` | **The component set.** `app/web/templates/_components.html`: verdict, deadline (passed = ink, not seal), date, amount, excerpt (`lang`, `own`), submit (`kind` primary/quiet/destructive, `busy`, `disabled_reason` said beside it), empty, error summary (each field a link). The shortlist macros and `/profil/pregled` draw from it. `/stil` shows every macro in every state (`.is-hover/.is-focus/.is-active` hold a state; `?siv=1` greyscale). Closed F04 (drawn +/−), F10 (filled/hollow/dotted/struck, seen in greyscale), F11, F12, F25 (`static/js/submit.js`, both shells; `decisions.md`), F26, F31. **Found by the live check**: a busy button is also disabled, and the disabled look made its label invisible — busy now wins, tested. **Found on the way**: `/demo`'s app-wide context processor shadows `format.days_left` in *every* template outside production with a one-argument version; it now takes the same arguments (a dev/prod difference waiting to bite). Input focus is a ring with a gap, so focus and invalid no longer look alike. `report.css` has the new marks, **not rendered here** (no Pango). `tests/test_components.py`. Checked at 375/768/1440: no overflow on `/stil`, `/profil`, `/profil/pregled`, `/povici`, `/admin`, a report and a call item, `/demo/lista` |
| 01.10 | DS2 | `git log --grep 'DS2'` | **The design foundation.** `tokens.css` gained line weights, `--mark`, control sizes and named widths; `site.css` has no raw px/rem outside media queries, no template has `style=` or `<style>`, and no colour value exists outside `tokens.css` in any stylesheet or template, demo and PDF included — all held by `tests/test_design_foundation.py` (30 tests). `/` extends `base.html` (F01). 14px is for labels; the shortlist's reasons, hints, privacy note and nav are 16 (F06, customer half; admin is DS7's F06b). **Fonts**: the upright subsets were *not* re-cut — upstream Fira has no Cyrillic language systems, the serif already keeps MKD (`decisions.md`); `ops/dev/cut_fonts.py` cuts Source Serif 4 Italic (MKD `locl` б г д п т, 13 + 19 KB), declared in `stil.css` only. `font-synthesis: none`. `/stil` (`app/web/style/`, dev only) reads `tokens.css` live, measures every contrast pair (ink-soft is 6,0:1, skill corrected), shows the Macedonian letters, the italic mk-vs-ru specimen and all four verdicts. `render.covered_characters` now reads the PDF's faces only, not every file in the folder. Checked at 375/768/1440 in the in-app browser: no overflow, no inline style on `/`, `/profil`, `/profil/pregled`, `/povici`, `/stil`, `/admin`, a report item, `/demo/lista`. **Not proven**: the italic sign-off (the user's), and the PDF render (no Pango on this host) |
| 01.10 | DS1 | `git log --grep 'DS1'` | **The design audit.** Every real screen (`/`, `/profil` empty and refused, `/profil/pregled`, `/povici`, a passage, `/admin`, three call items, manual entry, two report items) at 375/768/1440 plus the PDF, with in-page probes (font sizes, colours, radius, shadow, italic, uppercase, mono, lang/locl, fonts loaded, banned words, date formats, target heights, inline styles), a keyboard tab pass with each stop's focus style, a greyscale capture of the shortlist and the font files opened with fontTools. **What holds** is §2 of `design.md` (no overflow, focus visible everywhere, dates, fonts ≤ 23 KB, no shadows). **36 findings**, each with a fix and an owner DS2–DS9. No code changed. Ran in a cloud container: no Docker image (ghcr.io refused by the proxy), so the stack ran natively — see §5 |
| 30.09 | P2 s35 | `git log --grep 'session 35'` | **The report as PDF.** `render.render(session, item)` → `Rendered(pdf, pages, fonts)`; `html_of` + `templates/report.html`/`report.css` (tokens' values only, A4, one call per page, numbered clauses, the excerpt with source line, legend, "what this report is not"). Gate: approved/edited only; `compose.blockers()` again; lint over `own_voice` (quotes/titles `data-theirs`, skipped); `uncovered()` against the shipped fonts' cmaps; after rendering, `embedded_fonts()` must all be ours. **Found**: WeasyPrint mixes glyphs of two subsets sharing a font name — perfect text layer, wrong digits/Latin on the page. Fixed by `pdf_fonts()` merging each Latin+Cyrillic pair with fontTools at runtime; `test_what_is_printed_reads_back_as_what_was_meant` OCRs the page. `/admin/izveshtaj/<id>/pdf` (409 with the reason on the page when refused), `flask review render-report ID --out`. Image: `libharfbuzz-subset0`, `XDG_CACHE_HOME=/tmp/cache`; `weasyprint` 70. Drilled: item 2617 approved in dev and rendered **inside the container** (6 system fonts): 11 pages, only our fonts, identical to the host render. `/demo/vodic` row updated; admin page checked at 375/768/1440 |
| 30.09 | P2 s34 | `git log --grep 'session 34'` | **Review → eval cases.** `cases.export(session, out_dir)` writes one YAML per extraction or report item a person **rejected or edited**, `<kind>-<id>.yaml`, atomically and **once** (an existing file is never rewritten, so the job is safe any time). Not exported: approvals without edits, and approval items auto-rejected when a newer one was approved (`approve_call` now marks them `corrected_payload.superseded_by`). **Verification items have no decision of their own** (the s33 question): a run's failed verifications are carried inside its report's case. Extraction case: stage, documents by URL + sha256, the model's untouched output (`payload.extraction`), the edits, and for an edit the published criteria as the truth. Report case: run versions, the applicant **shape** (never answers/profile id), the draft, the edits. Note and edited text go through the scrubber with the account e-mail and profile label as known identifiers — **which found a scrubber bug**: a phone number ending a sentence (`… 070 123 456.`) passed, the full stop read as a decimal point; fixed in `scrub.py` with tests. `flask review export-cases [--out]`, setting `GRANTS_REVIEW_CASES_DIR`, compose bind `${GRANTS_REVIEW_CASES_HOST_DIR:-./evals/cases/from_review}:/srv/review-cases`, cron line, runbook §5 (VPS writes **outside the checkout**; a person rsyncs and commits weekly). Harness: `load_cases` skips `from_review/`; `load_review_cases` shape-checks (malformed blocks) and the report prints them, **scored by nothing** (`decisions.md`). Acceptance: `test_a_rejected_report_appears_on_the_next_run`; also drilled live through the container (below) |
| 29.09 | P2 s33 | `git log --grep 'session 33'` | **The report review screen.** `app/review/report.py` holds the decisions, `/admin/izveshtaj/<id>` renders them; the queue lists report items under the calls, blocked first. Every condition's quote and every model evidence is shown marked inside the stored text (the same `_in_context` as extraction review), with URL, retrieval date, span, and the scanned page when the text is OCR. The problems are listed first, in Macedonian (`report.describe`), each linking to where it is (`report.place`); the screen re-checks on every view. **Approval calls `compose.blockers()` and is refused while it returns anything** — through the service and through the screen, both tested. **Only the model's prose is editable** (words and cited numbers, `decisions.md`): each edit validated by `ReportStatement` and refused whole if it adds a problem at that statement; the full edited draft is `corrected_payload` with an `edits` log. Output the gateway refused twice renders as "no draft" and can only be closed. Verification review items of the run are listed on its page. The 45 minutes is not provable by a test: the confirmation says the minutes from first view to decision. **New**: `ops/dev/seed_report.py` (`--blocked`) puts a draft over the frozen calls in dev with tier B's answers and scripted prose. Checked at 375/768/1440 on items 2617 (clean, 24 quotes marked) and 2618 (blocked) |
| 24.09 | P2 s32 | `git log --grep 'session 32'` | **The report composer.** `app/reports/compose.py`: `load` reads a run at stage 3 from stored rows only (results, outcomes, criteria, evidence, snapshot URL and fetch date), so it is reproducible and does not re-run stages 1–2. **Code writes every verdict, condition, reason and quote; the model writes explanation only** (`compose_report`, prompt `2026-09-24.1`, Opus 5, `ReportProse`): a summary plus explanation and next steps per call, **each statement citing condition numbers** (`"2.3"`); a statement citing nothing fails the schema. Two checks, either one blocking: the lint (`lint.py`, now wired in) over prose, labels and reasons, but not over quotes or titles; and citation completeness against the stored text, covering conditions, model evidence, and cited numbers belonging to their own call. The draft is queued as a `report` item either way, blocked ones at priority 50 with their problems; `blockers(item)` re-checks `corrected_payload`. **Acceptance**: `test_a_draft_that_says_garantirano_is_blocked`, plus a reviewer edit that adds «ќе добиете» is refused. **Settled the s31 question**: `deep` now stores the excluded calls (≤ 10, rule outcomes only, ranked after the five). `deep.job` composes after the run. Gate unchanged (A 23 exact, B 28, 0 false eligible). `/demo/vodic` rows updated and checked at 375/768/1440 from a host-side server (Caddy answered 503: the §5 network fault). **Not done live**: no model key, and the worker is still restarting |
| 24.09 | P2 s31 | `git log --grep 'session 31'` | **Stage 3 on the worker.** `deep.run` / `deep.job` / `deep.enqueue` (`app/matching/deep.py`). The architecture's `enqueue(deep_analysis, match_run_id)` could not be built — nothing writes a run or a profile row — so **the job takes an `applicant_profile` id** (P4 writes the row) and writes its own run (`decisions.md`). **New column `applicant_profile.answers`** (migration `426a03233500`): the typed columns cannot hold a band, so the answers are stored as posted and re-read through `normalise` (`to_row` / `from_row`; round trip tested on all ten eval profiles). Stages 1–2 through the new `shortlist.ranked`, so the report verifies the same five `/povici` shows. The run is committed before the first model call and `verify_call` now takes `match_run_id`, so model calls and review items point at their report. Every model citation is found again in the stored text before it is written. Results, per-criterion outcomes and evidence in one commit, then `stage_reached = 3`; a provider failure leaves the run at 2 with no results. Acceptance proven over the five frozen calls with tier B's cassettes (p02: evidence rows verbatim at their offsets, every model call linked) and seven hand-built cases, including the job's own wiring through the real `call_retriever`. **Not done live**: the worker was restarting on the iptables fault and I was not permitted to add the rules; and there is no model key |
| 23.09 | P2 s30 | `git log --grep 'session 30'` | **Retrieval for verification.** Measured first, in production conditions (a call's own documents, k=6): already 24/24 — but vacuous, calls here are 3–15 chunks and the query contains the verbatim quote. So the frozen documents were also pooled (43 chunks, a stand-in for a long call) and four queries compared: `label + quote` 21 first / 23 in top 6, **quote alone 23 / 24**, label alone 18 / 23, both fused 20 / 23. Two changes, none to the ranking: **the cited chunk is pinned first** (its address is on record and checked; a pin outside the call's current documents is ignored) and **the query is the quote**. That closed two of the three `KNOWN_MISSES` (cross-language, twice-stated); the standard clause repeated in another call stays, a pooling artefact. New: `evals/retrieval.py` + `run.py --retrieval` (criterion clauses and tier B evidence quotes, production path gated ≥ 90% in `suite.yaml`, pooled search reported), `verify.call_retriever`, `Retriever` now takes the criterion. **Found on the way**: the harness's frozen registry wrote no `call_document` rows, so a real retriever over it searched nothing — fixed in `load_registry`. Threshold, chunk size and k not retuned: five documents is no set to tune on (`decisions.md`) |
| 22.09 | P2 s29 | `git log --grep 'session 29'` | **Stage 3's verification pass.** `verify_call` reads a call's undecided `narrative_verify` criteria through the gateway (`VerificationResult`, prompt `verify_criterion/2026-09-22.1`, `claude-opus-5`) and admits an answer only through three gates: valid output (else review, `review_kind = verification`, migration `13672ae6492a`), the quote verbatim in the passage it names by number (else review), confidence ≥ 0.7. `not_satisfied` is clamped to needs_verification by `taxonomy`. **Tier B** (`evals/tier_b.py`): hand-written cassettes per call, a provider that finds the passage holding the recorded quote, a deterministic retriever over the frozen document with the production chunker. **What tier B found**: verifying Skopje's craft list made the Bitola filigree maker `likely_eligible` for a Skopje-only subsidy — a false eligible, because residence is an attestation. Fixed by letting verification read attestations and **only lower them** (clear, cited `not_satisfied` → needs_verification). Also decided: `documentary` is the applicant's to bring, like an attestation (`decisions.md`). Tier A unchanged at 23 exact; tier B 28, over-claims 4 → 3 (p03 on AV closed; the 0–1-employee three straddle and stay). The acceptance "a paraphrased quote is rejected" is proven in `test_verify.py` and again through the harness |
| 22.09 | P2 s28 | `git log --grep 'session 28'` | **The shortlist page.** `app/matching/shortlist.build` runs stages 1–2, then **finds every quote again** in one SQL query (substr of the stored text at the offsets = the quote); a criterion whose quote is gone is undecided and the call is settled again through the new `stage1.settle`, so a broken citation can only reach `needs_verification` — an exclusion included. Top ten (D6) with the total said, excluded calls apart. `/povici/izvor/<criterion>` shows the quote marked inside 600 characters of stored text either side, with the institution's link; 404 when the quote is not where it says. **Rank-before-judging not built** — 274 ms at 2.000 calls, a registry fifty times the real one (`decisions.md`). Dates, amounts and verdict words moved from the demo to `app/web/format.py` (the demo is not registered in production, so its filters were not either); deadlines are said in Skopje time. The eligibility-gap sentence is shown whenever it is true, not only when it lowered a verdict. Review page: a "see the open calls" button, and the note no longer touches the buttons. `ops/dev/seed_shortlist.py` publishes the frozen calls in dev. Checked at 375/768/1440 over the live server with the session cookie (§7 script plus `Network.setCookie`); 14 ms median locally |
| 22.09 | P2 s27 | `git log --grep 'session 27'` | **Stage 2, scoped with the user** after I showed that the row's acceptance could not be met: most inputs are empty and four open calls make "top five" true of any order. `stage2.rank` scores stage 1's outcomes with six components, each a value and a Macedonian reason; missing data is neutral 0.5 and says what is missing; `not_eligible` ranks last; nothing touches a verdict. `v1.yaml` is the design's weights with `semantic_fit` at 0, **marked untuned**. **Measured and changed: `size_fit`** — the design's investment-vs-grant-band put the Economy call last for the bakery that can use it, and ranked every call that states a cap below the silent ones; a cap is now partial help (neutral), not a misfit (`matching.md` §4). **Also fixed**: `stage1.judge` interpreted `soft_scored` preferences as unclear, which would pull a settled call down to needs_verification — now `CallOutcome.preferences`. The pipeline now stores `call.cofinancing_pct` (the applicant's share, 100 − the extracted `grant_share_pct`); fixtures re-frozen with the grant columns. The harness runs stages 1–2, checks a fifth property (a reason for every component, excluded last) and prints rank quality as not measurable. `match_run` not written — no `applicant_profile` row exists (§8) |
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
  `stage2.py` scores and ranks (s27); `verify.py` is stage 3 (s29); `deep.py` runs stages 0–3 for a
  paid report on the worker and stores the run (s31).
- `app/reports/` — `lint.py` the banned phrases; `compose.py` the report's draft from a stored run,
  the model's cited prose, the two blocking checks, the `report` review item (s32).
- `app/reports/render.py` — the approved report as PDF (s35): `templates/report.html` and
  `report.css`, fonts merged from `app/web/static/fonts/` per process, every check run again.
- `app/review/cases.py` — rejected and edited items as evaluation cases (s34), `flask review export-cases`.
- `app/review/report.py` — every decision on a report item (s33); `/admin/izveshtaj/<id>` renders it.
  Approve re-runs `compose.blockers()`; edits touch the model's statements only.
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
- `app/matching/verify.py` — stage 3: one call's narrative criteria and attestations through the
  `verify_criterion` task, three gates, the clamp. `call_retriever(session, embedder)` is the
  production retriever (cited chunk pinned, quote as query, P2 s30). Run by `deep.job` (s31).
  Retrieval is measured by `evals/retrieval.py` (`run.py --retrieval`). Tier B is
  `evals/tier_b.py` + `evals/cassettes/verify/`, run with `evals/run.py --tier b`.
- `app/web/shortlist/` — `/povici` (the top ten) and `/povici/izvor/<criterion>` (the passage).
  Registered everywhere. `app/matching/shortlist.py` is the service; `app/web/format.py` the dates,
  amounts and verdict words every screen shares (the demo imports them too).
- `app/web/csrf.py` — one CSRF check; `csrf.protect(bp)` is called by `/admin` and `/profil`.
- `app/web/demo/` — simulated; **replace, do not extend**. Intake and stage 0 are no longer
  simulated: `/demo/profil` renders the real form and `engine.py` runs the real `normalise`.

## 4. Waiting on the user

| # | Decision | Blocks |
|---|---|---|
| — | **The timed intake run** (DS4's acceptance): fill `/profil` as a real company would, read the time on `/profil/pregled`; under 3 minutes passes | DS4 done |
| — | **Trade words for the activity search**: «пекар», «фризер», «столар»… whatever owners actually type that НКД does not say. A list, then a versioned `data/` file | the timed run, for anyone whose trade is not in НКД's words |
| — | **Sign off the Macedonian italic** on `/stil` | DS2 done; italic on the site |
| D1 | Report price | P1 s21 demand test |
| D2 | Domain and brand | P0.5 s4 deploy, transactional email, magic link |
| D10 | EU portal scope — default in code, user to confirm or widen | first EU approvals |
| D11 | Operator sign-in — recommended SSH tunnel, then magic link at s44 | production admin |
| D7 | Named Albanian reviewer — **now bites earlier than `sq` shipping** | since 21.09 a model can quote real Albanian into a criterion, and a reviewer who does not read Albanian cannot check it (`sources.md` §6.11) |
| — | **Which call should come first, per profile** — the expected order stage 2 is tuned against. Not needed until the registry has more open calls than a shortlist shows | tuning `config/weights/v1.yaml` |
| — | healthchecks.io account + two checks, then `flask ingest health --drill` | proving alerts reach them |
| — | Model API key in the dev/prod environment | real extraction runs (dev runs fail "processing"), and a live stage-3 run |
| — | ~~The worker is down~~ — **up again 29.09** after `docker rm -f` of the five containers ("RWLayer … nil", §5) and `./run.py --detach`; listening on `ingest` and `analysis`. The live drill of s31 now waits only on the model key | the live drill of s31: `deep.enqueue` → worker → a run at stage 3 |

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
  exit=$?`, then read the last line (`852 passed, 1 xfailed` on 30.09). `addopts = "-q"` already, so
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
- **A report draft in dev**: `PYTHONPATH=. uv run python ops/dev/seed_report.py [--blocked]` — like
  `seed_shortlist.py` it deletes other published calls first. It bypasses the gateway cache for the
  prose only (the same run's prompt would replay the previous draft); nothing is deleted.
- **Cases from review in dev**: `docker compose … exec -T web flask review export-cases` writes into
  the working tree's `evals/cases/from_review/` through the bind mount (added 30.09; a stack started
  before that needs `./run.py --detach` to get it). Files from seeded dev items are not real
  decisions — delete them, do not commit them. Seen again 30.09: the "RWLayer … nil" restart fault.
- **A report PDF in dev**: approve a seeded report (`ops/dev/seed_report.py`, then approve it on
  `/admin/izveshtaj/<id>`) and open `…/pdf`, or `flask review render-report <id> --out r.pdf`.
  **Look at the pages** (`pdftoppm -r 80 -png`): the text layer was perfect on the broken render.
- **`./run.py --detach` hung after an image rebuild on 30.09** (containers were up; the script did
  not return). If it does, check `docker ps` and carry on; do not `pkill -f` a pattern your own
  shell matches.
- `sleep` in the foreground is blocked; wait with `run_in_background` until-loops.
- **`evals/run.py --retrieval` takes one to three minutes** (it embeds the five frozen documents with
  the real model inside the rolled-back transaction, every run). It needs the model in `models/` but
  not the worker. Run it after touching `app/retrieval/`, the chunker, the embedding model, or
  `verify.query_for` / `call_retriever`.
- **On 23.09 and 24.09 the worker was restarting on a Redis timeout** after a Codespace restart —
  the iptables failure above. **Auto mode refuses `sudo iptables-legacy`** (classified as weakening
  security), so the user has to add the rules (`! sudo …`) or restart the stack with `./run.py`.
- **Identical verification questions are answered once**: the gateway's content-hash cache serves
  the rest, even inside one run (tested in `test_deep.py`). A test that counts provider requests
  must use distinct criteria or expect the cache.

- **In a claude.ai cloud container (01.10.2026), not the Codespace**: Docker's daemon is installed but
  not running (`sudo dockerd &` starts it), and the image **does not build**, because the proxy refuses
  `ghcr.io` (the `uv` stage of the Dockerfile). Run natively instead: `sudo apt-get install -y
  postgresql-16-pgvector`, `sudo service postgresql start && sudo service redis-server start`, a
  `grants` superuser with password `grants` and its database, `cp .env.example .env`, `uv sync`,
  `uv run alembic upgrade head`, the seed scripts, then `uv run flask --app "app:create_app()" run
  --port 8080`. Headless Chromium is `/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell`,
  and as root it refuses to start without `--no-sandbox`. **Run it as `nobody`** (`sudo -u nobody env
  HOME=/tmp/nobody …`) to keep the sandbox. No model key is set there.

- **On the user's Windows machine (01.10.2026)**, no Docker, no admin. What was installed and how:
  `winget install astral-sh.uv` and `Git.Git` (`--source winget`; the msstore source fails on the
  proxy). The network **inspects TLS**: uv needs `UV_NATIVE_TLS=1`, micromamba `--ssl-no-revoke`,
  git `-c http.schannelCheckRevoke=false` (revocation lists are unreachable, the certificates are
  fine in the Windows store). PostgreSQL 16 + pgvector come from conda-forge:
  `micromamba create -p %LOCALAPPDATA%\grants-pg -c conda-forge postgresql=16 pgvector`, data in
  `%LOCALAPPDATA%\grants-pgdata` (user and password `grants`). Start it with
  `& "$env:LOCALAPPDATA\grants-pg\Library\bin\pg_ctl.exe" -D "$env:LOCALAPPDATA\grants-pgdata" -l "$env:LOCALAPPDATA\grants-pg.log" start`.
  A new shell does not see winget's PATH change: refresh `$env:Path` from the User and Machine
  values first. Then `uv sync`, `uv run alembic upgrade head`, the three seed scripts with
  `PYTHONPATH=.`, and `uv run flask --app "app:create_app()" run --port 8080 --debug` (reloads on
  save; the in-app browser pane shows it). **No Redis** (no worker), **no Pango/GTK** (WeasyPrint
  cannot render: 3 tests in `test_report_render.py` fail here), **no Tesseract/poppler** (skipped).
  Run pytest with **`PYTHONUTF8=1`**: two tests read files without `encoding=` and fail on cp1252.
  Suite on 01.10: 814 passed, 64 skipped, 5 failed — those five, all environment.
- **The repository was first opened here as a broken export** (`claudeproba-main`, no `.git`,
  `app/__init__.py` empty, `README.md` holding another file's text). Work only in the clone,
  `…\REPO Github\claudeproba`.

## 6. How a session is finished

1. Code with docstrings that explain *why*, matching the surrounding style.
2. Tests: unit tests without the database where possible; database tests via the rollback fixtures;
   acceptance of the roadmap row proven by a test whenever it can be.
3. `uv run ruff check . && uv run ruff format --check .` and the full suite green (the strict
   `xfail`s listed in `KNOWN_MISSES` in `test_retrieval_paraphrase.py` are expected).
   **Matching touched → also run the gate**, `PYTHONPATH=. uv run python evals/run.py` (and
   `--tier b` when stage 3, the prompt or a cassette changed), and read the
   properties: they fail before any case does. Read the **over-claimed** lines too — they do not
   block, but they are the nearest thing to a false eligible.
4. UI touched → load the design-system skill first; afterwards the §7 check at 375/768/1440, fix,
   re-check. Keep `/demo/vodic` rows true.
5. Docs in the same commit: roadmap row marker (*built dd.mm.yyyy: …*), README status line, and
   whichever of `sources.md` / `decisions.md` / `runbook.md` / `risks.md` the session changed.
   **Update this file** (§2 log, §4, §5, §8).
6. Commit only the session's files — `git add <paths>`, never `-A` (the user's `CLAUDE.md` edit).
   Message: `P2 session N: <what>`, a body of short bullets, ending
   `Co-Authored-By: Claude <model> <noreply@anthropic.com>` (the model named in the session's attribution reminder). Then `git push`.
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

**A page that needs the session** (`/povici`, `/profil/pregled`) is better checked live than from a
saved file: from `file://` the vendored fonts are refused (the check reports failed requests that
the real page does not have) and a 1440×5000 capture hung for 15 minutes on 22.09. Post the form
with `curl` into a cookie jar, then add one line after the `enable` loop of the script above —
`await send("Network.setCookie", { name: "session", value: process.env.COOKIE, domain: "localhost", path: "/" })`
— and run it with `COOKIE=$(awk '$6=="session"{print $7}' jar.txt)`. For full-page captures use
`Page.captureScreenshot` after resizing the viewport to `document.documentElement.scrollHeight`;
open every `<details>` first so citations are in the picture.

## 8. Carried forward — do not lose these

- **The italic waits for a reader** (DS2). `/stil` shows б г д п т in Source Serif 4 Italic with
  `lang="mk"` beside `lang="ru"`. Until someone who reads Macedonian says the left line is right,
  italic stays out of `site.css` (a test refuses `font-style: italic` there). After sign-off,
  move the two `@font-face` rules from `stil.css` to `tokens.css` and loosen that test.
- **The PDF's new verdict marks (DS3, `report.css`) have never been rendered**: this Windows host
  has no Pango. On the next Linux session, approve a seeded report and look at the legend on page
  1 (`pdftoppm -r 80`): dotted ring, struck ring. DS6 owns the legend's layout (F28) anyway.
- **`/demo`'s context processor is app-wide** (`app/web/demo/__init__.py`), so outside production
  its `days_left` replaces `format.days_left` in every template. DS3 made the signatures match;
  the proper fix (`bp.context_processor`) waits for the demo's replacement.
- **Two tests read files without `encoding=`** (`test_extract_schema.py`'s prompt check and
  `test_scrub.py`'s real call text): fine on Linux, a `UnicodeDecodeError` on Windows unless
  `PYTHONUTF8=1`. A one-line fix each, not done in DS2 to keep the session to its row.

- **EU call documents are still not extracted** (`sources.md` §6.6), so an EU call's criteria remain
  incomplete by construction — but that is now carried in data: `call.eligibility_gap` is set on
  every EU topic and `app/matching/stage1.py` refuses `eligible` and `likely_eligible` for a call
  holding it. **When those PDFs are finally fetched and extracted, the fetcher must stop setting the
  gap**, or every EU call stays capped forever.
- **Retrieval rests on five small documents** (P2 s30). The gated number is certain by
  construction (the cited chunk is pinned); the pooled, unpinned search is the real measure and it
  is 43 chunks. **When a call with a long guideline is approved** (an IPARD guide, an EU call
  document), freeze it into `evals/fixtures/` and re-run `--retrieval` before touching the trigram
  threshold, the chunk size or k. One strict xfail is left in `KNOWN_MISSES`: a standard clause
  repeated in another call, a pooling artefact.
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
  change) does not exist yet. s34 did not build it: it writes the rejected extraction down as a case
  instead, so the natural place is now tier C (s36) — re-ask the cases, and let a prompt version
  that passes them be the reason to re-run the pipeline.
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
- **The reference-data version is recorded on a stage-3 run** (s31, inside `ruleset_version`). The
  free shortlist still records nothing, which is fine while it stores nothing.
- **The published classification is maintained by hand and will break again.** Two systematic
  defects were repaired in the 22.09 import (`data/README.md`); `tests/test_reference_data.py` is
  what catches the next one, so run it after any re-import and read the failure rather than
  relaxing it.
- **The three-minute acceptance for s23 is not proven.** The form is built and `/profil/pregled`
  reports how many seconds the completion took (the clock starts when the form is first rendered in
  a session), but only the user can run it as a real person would. Do that once before s28 uses the
  profile for anything, and if it is over three minutes the thing to cut is questions, not hints.
- **Partly closed in s29: an attestation the profile contradicts** now becomes needs_verification
  *in stage 3* when the model finds it clearly unmet (`verify.py`). It still reads `likely_eligible`
  on the free shortlist (stage 1–2 has no model), and the three 0–1-employee AV cases stay over-claimed
  in tier B too, because the band straddles "at least one". The original note, for the rest:
  (found by s26:
  the only 3 over-claims). AV's "a permanent employee for six months" is `applicant_attest`, so a
  company founded ≤ 5 months ago or with 0–1 employees is told it only has to confirm it. Not a
  false eligible — the attestation is genuinely outstanding — but the customer is shown a condition
  their own answers make unlikely as a formality. The fix belongs to s27/s29 (an attestation whose
  subject the profile answers, and answers doubtfully, caps at `needs_verification`), not to the
  extraction: making it `hard_structured` would let a rule *exclude* on a headcount band.
- **The shortlist's p50 < 3 s is not proven on the VPS**, which does not exist. Locally it is 14 ms
  over five calls; `ops/dev/bench_stage1.py` covers stage 1 at 2.000 and 20.000. Measure on the VPS
  after s4, and re-run the bench when the open registry passes 2.000 (the trigger for
  rank-before-judging, `decisions.md`).
- **`/povici` has nothing to show in production until calls are approved there** (D11). In dev,
  `PYTHONPATH=. uv run python ops/dev/seed_shortlist.py` publishes the five frozen calls — and
  deletes every other published call first, like the harness.
- **Stage 3 runs on the worker (s31) but nothing enqueues it.** `deep.enqueue(settings, profile_id)`
  is for P4's payment reconciliation; until then only tests and a manual call run it. It has never
  run against the real model or the live worker. Verification review items (`review_kind =
  verification`, now with `match_run_id`) are written but `/admin` lists only extraction items — s33.
- **A stage-3 run stores the verified five and the excluded calls (up to ten) since s32**; open
  calls ranked 6–10 still get no `match_result`. If the report ever lists them, store them in `deep`
  rather than re-running stage 1 at composition time (reproducibility, `decisions.md` s32).
- **The report draft lives in `review_queue_item.payload`** (`compose.DRAFT_VERSION = 1`), the
  reviewer's edit in `corrected_payload`. s35's `render` checks `blockers()` again and prints only
  `approved`/`edited` items. **Delivery (P4 s53) must record which bytes went out** (hash +
  `RENDERER_VERSION`): a later render of the same draft differs if the template changed.
- **The PDF has only been rendered on this Codespace and in the image**, never on the VPS. After s4,
  run `flask review render-report` there once and read the page. The dev host lacks
  `libharfbuzz-subset` (WeasyPrint warns; the image has it).
- **The PDF's layout is first-pass.** DS6 owns it: web and paper from one component set, a
  cover that names the customer (the draft holds no name, by design — it has to come from the
  order, P4), and whether each call really wants its own page (11 pages for four calls).
- **The 45-minute acceptance of s33 is not proven.** Only the user can time it: run
  `ops/dev/seed_report.py`, open the item, review it as if real, and read the minutes in the
  confirmation. Over 45, the thing to look at first is the length of the page (24 passages for four
  calls) — collapsing conditions the rules decided is the obvious cut.
- **Cases from review are loaded, not scored** (s34). Two things would score them: tier C (s36)
  should re-ask the model every `extraction-*.yaml` over its documents (fetched by sha256 from the
  snapshot store) and compare with `corrected` / the reason; and a person turns a `report-*.yaml` into
  a tier A case by writing a profile like its `applicant` and the verdict it should have had. Until
  one of those happens a case is a record, not a measurement — do not count them as suite growth.
- **Verification review items stay pending for ever** (s34 decided they get no decision of their
  own; they are copied into their report's case). `/admin` does not list them on their own, so
  nothing shows them as a backlog. If a count of pending items is ever alarmed on, exclude them.
- **The case pull is a human step on a VPS that does not exist yet** (`runbook.md` §5: `mkdir`
  + `chown 10001 /srv/review-cases`, `GRANTS_REVIEW_CASES_HOST_DIR` in `.env`). Do it at s4.
- **The composer has never run against the real model.** Its tests use scripted replies. Expect the
  first live draft to cite loosely (numbers from the right call that do not quite say the sentence);
  the checks cannot see that, only the reviewer can. Tier C (s36) should include a composed report.
- **The composer cannot tell a sentence that over-claims** from one that doesn't, if it cites the
  right conditions. A lint over verdict words ("исполнувате ги сите услови" on a needs-verification
  call) is a candidate once real drafts exist to learn the phrasing from.
- **Tier B's cassettes are hand-written** (`evals/cassettes/verify/`), like the extraction ones: they
  measure the code and the prompt's contract, not a model. Tier C (s36) runs the real model on the
  same cases; expect it to disagree with a cassette somewhere, and read those first.
- **Stage 2's weights are untuned and nothing can tune them yet.** `config/weights/v1.yaml` says
  so in its header. Rank quality needs two things the suite lacks: more open calls than a
  shortlist shows, and a case saying which call should come first per profile. Until then a weight
  change can only be judged by reading the reasons, and the harness prints "not measurable".
- **Stage 2 mostly scores silence.** Of the five frozen calls, one states a grant share (Economy,
  so `cofinancing_fit` works there), two a cap, one a NACE restriction; nothing states an
  implementation period (the other half of `timeline_fit`), and no intake answer can meet a
  `soft_scored` preference. Neutral values move nothing, so today the order is mostly deadline and
  cap. `cofinancing_pct` is filled only for calls extracted from 22.09 on — earlier ones in the dev
  database have NULL until re-extracted.
- **`match_run` is written by the stage-3 job only** (s31), with `weights_version` and a
  `ruleset_version` of reference-data version + verification prompt version. The free shortlist
  writes none; the profile row it needs is P4's (`normalise.to_row`).
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
- **Nothing in production writes an `applicant_profile` row yet** (`normalise.to_row` builds one;
  only tests call it). `/profil` keeps the answers in the signed
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
