# Open decisions — yours to make

Everything else in `/docs` I decided and justified. These eleven I cannot decide for you, because they
depend on your market judgement, your risk appetite, or facts about your business I do not have.

Each has a **recommendation**, the **reasoning**, and the **consequence of each option** so you can
disagree with the recommendation for a stated reason rather than a feeling.

Rate used throughout: **1 EUR ≈ 61.5 MKD** (the denar is pegged, so this is stable).

---

## D1 — Pricing (you left this open; here is the model)

### The input that actually matters

The marginal cost of a deep report is roughly **€1 of model tokens and 45–60 minutes of your review
time**. Tokens are noise. **Your evenings are the binding constraint**, so price per review-hour is
the only number worth optimising.

If you allocate ~4 h/week to review once the build settles, that is ~17 review-hours per month.

| | **A — 2.900 ден** | **B — 8.900 ден** ⭐ | **C — 19.900 ден** |
|---|---|---|---|
| Ex-VAT price | ~€47 | ~€145 | ~€324 |
| With 18% ДДВ | 3.422 ден | 10.502 ден | 23.482 ден |
| Review time it funds | ~30 min | ~60 min | ~120 min |
| **Revenue per review-hour** | **~€92** | **~€144** | **~€162** |
| Reports/month at 17 review-h | ~34 | ~17 | ~8 |
| **Monthly revenue at capacity** | **~€1.560** | **~€2.450** | **~€2.590** |
| Customers needed for brief §14 (3 sales) | 3 → €141 | 3 → €435 | 3 → €972 |
| Sales motion | Self-serve impulse | Self-serve considered | Requires a conversation |

### Recommendation: **B — 8.900 ден ex-VAT (10.502 ден with ДДВ)**

Similar revenue at capacity to option C, but reachable through a self-serve checkout rather than a
sales call — which is the entire point of the funnel you are building. It funds a full hour of honest
review per report, which is what the human gate actually needs.

**Consequences:**
- **Choosing A** — you need 34 sales a month for the same income, and 30 minutes of review is not
  enough time to properly check a report with 50 cited criteria. Volume pressure will erode the
  review gate, which is the one thing protecting you from R2. Only viable once review is largely
  automated, which is not year one.
- **Choosing B** — 17 sales/month is a real but achievable target in a market this size. Priced high
  enough to signal seriousness, low enough to buy without a procurement process.
- **Choosing C** — best hourly rate, but it is consulting with a website attached. If that is the
  business you want, the platform becomes lead generation and P3's self-serve work is largely wasted.
  A legitimate strategy, but decide it now, not after building the checkout.

**Also decide:**
1. **Founding-customer price.** I recommend the first 10 customers at **4.900 ден**, explicitly
   time-limited and labelled as such. It creates a reason to buy now and gives you real price
   elasticity data. Consequence of not doing it: session 21's demand test is a harder sell and a
   noisier signal.
2. **VAT presentation.** Display **both**: `8.900 ден. без ДДВ (10.502 ден. со ДДВ)`. Your B2B buyers
   think ex-VAT; farmers and individuals are not VAT-registered and pay the gross. Showing one number
   confuses half your market.
3. **Document packages (P5).** FITR-type package **25.000–45.000 ден**; IPARD-type **60.000 ден+**
   (local consultants often charge 2–5% of the grant, so this is not aggressive).
4. **Monitoring subscription.** **1.200 ден/month or 12.000 ден/year.** At 50 subscribers that is
   ~€975/month recurring at near-zero marginal cost — and it is the line that fixes the seasonality
   problem in `risks.md` R4. It is probably the most important price on this page, not the least.

**One thing I recommend against: success fees.** Charging a percentage of the awarded grant is the
local convention and it would raise revenue. It also delays cash by 6–18 months and — more seriously
— creates a direct incentive to tell customers they are eligible. The entire product is built on
telling them honestly when they are not. Flat fees in v1; revisit only once the review gate has a
track record.

---

## D2 — Brand and domain

**Recommendation: a descriptive Macedonian `.mk` domain, not a brandable abstract name.**

The public archive strategy (P3) depends on organic search in a small market. A descriptive name
carries keyword weight, is instantly comprehensible to a 55-year-old business owner in Bitola, and
needs no marketing budget to explain itself. Register the matching `.com.mk` at the same time.
`.mk` registration requires a local entity — you have one.

**Consequences:** a brandable name is more memorable and more defensible long-term, but it needs
advertising spend you do not have in year one. Descriptive names are harder to sell or rename later.
Given a solo operation with no marketing budget, the SEO advantage wins.

**Also needed before P1 session 14:** an `@yourdomain` contact address and a public `/crawler` page,
both referenced in the crawler's User-Agent. Crawling ministries anonymously is how you get blocked.

---

## D3 — Which two programmes get document templates first (P5)

**Recommendation: 1) FITR, 2) Employment Agency measures. Explicitly *not* IPARD first.**

FITR has the most structured forms and clearest criteria, and its applicants are the most comfortable
with a digital product — so the first template validates the machinery with the shortest feedback
loop. Employment measures are the highest volume with the simplest documents, so the second template
is fast and immediately sellable.

**Consequence of choosing IPARD first** — which is tempting, since the packages are worth several
times more: it has the heaviest document set, the strongest incumbent consultants, and the longest
validation loop. You cannot properly test an IPARD template until an IPARD call is open, which may be
months away. You would risk spending 12 sessions on a template you cannot validate, at the point in
the project where momentum matters most. Do it third, once the templating machinery is proven.

---

## D4 — Contracting entity

**Recommendation: bill everything through your existing VAT-registered DOO. No new entity in v1.**

**You need to confirm two things with your accountant** (30 minutes, before P4 session 49):
1. Your registered activity codes cover software services and consulting as you intend to invoice them.
2. Your invoice numbering scheme and required fields are compliant — the generator in session 49 must
   match what your accountant already files.

**Consequence of a separate entity:** cleaner separation if you ever sell the platform, at the cost of
registration, a second set of books, and roughly two sessions of admin — for no v1 benefit.

---

## D5 — Data retention periods

**Recommendation:**

| Data | Retention | Reasoning |
|---|---|---|
| Applicant profiles | 24 months after last activity, then anonymised | Long enough for a returning seasonal customer, short enough to limit exposure |
| Accounts | Anonymised on request immediately | GDPR erasure, with invoice rows preserved |
| Invoices | **Per tax law — confirm the exact period with your accountant** | Legal obligation overrides erasure requests |
| Raw snapshots | Indefinite | Contain no personal data; they are the audit trail the accuracy contract depends on |
| `model_call_payload` | 12 months, then pruned | Audit value decays; storage and exposure do not |

**Consequences:** longer profile retention improves matching quality over time and makes returning
customers effortless, at the cost of more personal data held. Shorter retention means you cannot show
a customer what you told them a year ago — which matters in a dispute. 24 months is the point where
those two curves cross for this product.

---

## D6 — How much the free shortlist shows

You have chosen email-gated results. The remaining question is depth.

**Recommendation: show the full top 10 — verdict badge, the reasons behind each score, the deadline,
`last_verified_at`, and a link to the cited source.** Gate only the clause-level verification, the
document checklist and the written report.

This is your own quality bar from brief §12: the free tier should be genuinely useful on its own, with
no dark patterns in the upgrade path. Showing three results and blurring the rest is exactly the
pattern you said you would not use, and in a market this small, reputation compounds faster than
conversion tricks.

**Consequence of showing less:** marginally higher conversion to the paid report, at the cost of the
positioning that makes people trust a report they cannot verify themselves.

---

## D7 — Who reviews Albanian, and when it ships

You chose Macedonian-only at launch, which I think is right. But Albanian is roughly a quarter of the
market and its absence will be noticed.

**Recommendation: do not ship Albanian until you have a named human reviewer and a per-report budget
for them.** Ship the UI strings when convenient; hold back *generated Albanian prose* until reviewed.

**Consequence of shipping unreviewed AI Albanian:** exactly the failure brief §3.1 forbids for
Macedonian, in the language where a visible quality gap is read as something other than a technical
shortcoming. The cost of waiting is some lost market; the cost of shipping badly is worse and harder
to undo.

**What I need from you:** whether you already know someone who could do this, and roughly what they
would charge per report. That answer determines whether Albanian is a P6 item or a year-two item.

---

## D8 — Model spend ceiling

You said "cheapest", which I have implemented as: cheapest adequate tier per task, one primary
provider to keep the subprocessor list short, all behind a swappable interface.

**What I still need from you: a monthly spend ceiling that triggers an alarm.** I recommend **€30/month**
during P1–P4. The `model_call` table makes spend visible per feature, so the alarm is one query.

**Consequences:** too low a ceiling and you will throttle the composition step, which is the one place
a stronger model genuinely improves the customer-facing artefact. Too high and a caching bug or a
retry loop costs you a month's infrastructure budget before you notice. €30 with an alert is the
setting where both failures are cheap.

---

## D9 — OCR for call documents without a text layer

> **Decided 13.09.2026: A — Tesseract, with both rules below.** Implemented in the normaliser (P1 s9).
>
> **As built (P1 s9), two findings changed the details:**
> - **Macedonian model only (`-l mkd`), not `mkd+eng`.** English turned Cyrillic "б" into "6" and put
>   a Latin "A" into Cyrillic text on an IPARD call — invisible look-alikes that break quote matching.
> - **Rule 2 needs two signals, because a page mean hides misread words.** A clean 300 dpi Skopje scan
>   averaged 94 while still containing garbage words at confidence 0. A page goes to review when its
>   mean is below 85 **or** more than 10% of its words score below 60 (degraded 75 dpi: mean 78, 18%).
>   Isolated misreads on a good page are exactly why rule 1 — every OCR citation reviewed — stays.
> - `raw_snapshot.text_source` and `ocr_mean_confidence` record which text is OCR, and
>   `normaliser_version` names the Tesseract version that read it.

> **Open again in part (16.09.2026, P1 s18):** bilingual Macedonian–Albanian PDFs (every Economy
> call) score a page mean of 67–75 because the `mkd` model turns the Albanian half into garbage at
> confidence 0, while the Macedonian half reads well (median 92). Rule 2 as written flags every such
> page. Options: measure confidence over the Macedonian text only; or OCR with `mkd+sqi`, which must
> first be tested against the Cyrillic corruption that `mkd+eng` caused. `sources.md` §6.7.
>
> **Closed 21.09.2026 — read the Albanian, do not move the yardstick**
> (`normalise/pdf.py:restore_foreign_blocks`). Neither option above was taken. Measuring confidence
> over the Macedonian only would have *hidden* the unread half rather than read it, and leaves
> extraction looking at Cyrillic nonsense; `mkd+sqi` as one pass risks exactly the corruption
> `mkd+eng` caused. The third way is that **Tesseract already segments the two languages into
> separate blocks**, so the page can be read twice and merged by region:
>
> - a page with a block below `LOW_WORD_CONFIDENCE` is read again with `sqi`;
> - a **whole block** — never a word, never part of a line — is swapped to the second pass where its
>   mean is at least 80 **and** at least 25 points above what `mkd` scored on the block it covers;
> - blocks are matched by bounding box, not by Tesseract's block numbering, which is an internal
>   counter of a separate run;
> - a swapped block keeps the base block's number, so the page still reads in `mkd`'s order.
>
> Because a Latin-script model is only ever applied to blocks the Macedonian model demonstrably
> failed on, it cannot corrupt Cyrillic it never touches — which is what ruled `mkd+sqi` out as a
> single pass.
>
> **Measured over all 20 pages of both bilingual Economy calls:** the two passes produced *identical
> block sets on every page*, and the languages never disagreed by less than the 25-point margin — an
> Albanian block gained 30–90 points under `sqi`, a Macedonian block lost 20–60. Page means went
> 67–75 → 83–95. End to end on the 12-page call 1: document mean **90.31**, and **review reasons fell
> from every page to two** (pages 11 and 12, which are genuinely poor — page 12 has no Albanian on it
> at all and reads at 73). The degraded 75 dpi Skopje scan is *not* rescued: a bad scan is bad in
> every language, so no block is swapped and its review reason stands.
>
> **The Albanian is now correct Albanian**, with diacritics — "Republika e Maqedonisë së Veriut",
> "THIRRJE PUBLIKE" — where `mkd` gave "ЌКеририка е Мадедопј56" and "ТИКВЕЈЕ РОВЦКЕ". Two
> consequences worth stating: extraction and retrieval stop indexing nonsense, and **a model can now
> quote Albanian into a criterion**, which a reviewer who does not read Albanian cannot check. That is
> a second, independent reason for D7's named Albanian reviewer, and it applies before `sq` ships.
>
> **Cost and dependency:** `tesseract-ocr-sqi` and `tesseract-ocr-eng` join the image (D9's "two apt
> packages" becomes four). A page pays for a second pass only when it shows the symptom, and a model
> that is not installed is skipped rather than fatal, so an older image degrades to the Macedonian
> pass instead of failing. Measured on the same host over the 12-page call, both passes on:
> **155 s → 263 s, 1.7×.** Of that, the `%` pass cost 61 s and changed nothing on this document —
> it has no rates. That is the premium for catching one, and it is deliberately not tuned away: a
> tighter gate would also suppress the review reason a `%` nobody can place is supposed to raise.

> **And a second gap (18.09.2026, P1 s20):** the `mkd` model's character set has no `%`. "60%"
> is read as "609", "75%" as "755" or "7595", at confidences that raise no flag. The verbatim check
> passes, because the quote matches the OCR text; the number in it is wrong. `mkd+eng` reads `%`
> but turned "ЕУ" into Latin "EY" in the same test. `sources.md` §6.9.
>
> **Closed 21.09.2026 — the two-pass `%` restoration** (`normalise/pdf.py:restore_percents`,
> `NORMALISER_VERSION` `2026-09-21.1`). A page whose `mkd` text contains a digit is read a second
> time with `mkd+eng`, and the two word tables are matched **by bounding box**, not by text. Only the
> `%` character crosses over, and only into a token where all of the following hold:
>
> - the second-pass token holds exactly one `%` and **no letter at all**, so the Latin look-alikes
>   that disqualified `mkd+eng` as the primary model cannot enter the Cyrillic text;
> - the second pass was confident (≥80) and **`mkd` was not** (<80), so a number `mkd` read well is
>   never overruled — "6%" over a confident "60" is as likely to be the second pass misreading a zero;
> - the boxes overlap (≥0.5 of the second-pass box);
> - and the `mkd` token is that token with the `%` replaced by at most two non-letter characters,
>   i.e. the two passes agree on everything except the glyph one of them cannot write.
>
> A `%` seen by the second pass that fails any of this is **counted and becomes a review reason** —
> the text keeps what `mkd` wrote, wrong number and all, because a snapshot is faithful to what the
> engine read, and an unreadable rate is a human's (invariant 3).
>
> Measured on the IPARD 01/2025 short version, the only fixture with rates: **6 of 6 restored**, every
> box overlapping 1.00, second pass 92–97 where `mkd` scored 45–75 on the same six tokens. Diffed
> against the single pass over the whole three-page document, the *only* changes were those six
> tokens — the second pass contributed nothing else. Both word tables are recorded
> (`tests/fixtures/ipardpa/call-32.words.json`) because both differ between Tesseract versions.
>
> **Cost:** an OCR'd page with a digit is read twice, so roughly double the OCR time (a 26-page IPARD
> long version goes from ~10 to ~20 minutes on a first run; unchanged documents are still never
> re-read). `percent_pass=None` restores the single-pass behaviour.
>
> **Still open under D9:** bilingual MK/AL confidence (the paragraph above). Untouched by this.

Reconnaissance (`sources.md` §6.2) found that the call documents of **Economy, Skopje and IPARD**
mostly have no extractable text: scanned paper (Skopje) or Word exports with every glyph as an image
(Economy, IPARD). `pypdf` returns nothing. AV and the EU portal are unaffected.

A test on 13.09.2026 with Tesseract 5.3.4 and its `mkd` model, first page at 300 dpi:

- **Word-export PDFs** (Economy, IPARD): body text essentially exact. ~5–6 s per page.
- **Scanned PDF** (Skopje): body text good but not exact — "постапката за субвенционирање" came out as
  "поечатката- за еубвенционирање". Letterheads and stamps become noise. ~8 s per page.

| | **A — Tesseract in the worker image** ⭐ | **B — No OCR; route to review** | **C — Vision model via the gateway** |
|---|---|---|---|
| What happens | `pdftoppm` → `tesseract -l mkd` when a PDF has no text layer | Snapshot stored, item lands in the review queue as "unreadable"; you transcribe or summarise by hand | Page images sent to a model provider for transcription |
| New moving parts | Two apt packages (~40 MB), one normaliser branch | None | None in the image; a new task type and a per-page cost |
| Leaves the EU | No | No | Yes, unless the provider is EU-hosted |
| Citation quality | Verbatim against OCR text, which can differ from the paper | Whatever you type | Verbatim against model output, which can silently "correct" or paraphrase |
| Your time | Review of OCR-derived citations only | Every such document, ~50/year across the three sources | Review of every transcription |

### Recommendation: **A**, with two rules

1. **An OCR-derived snapshot is marked as such** (proposed: a `text_source` column on `raw_snapshot`), and every citation into it
   is shown to you with the page image beside the quote before it can reach a customer. The
   verbatim check still runs — against the OCR text — but it no longer proves the paper says it.
   **Built in full on 22.09.2026**: the mark and the document link came with P1 s15, and the page
   itself is now rendered beside each OCR'd quote on the review item — `pdftoppm` at 110 dpi, in
   colour, from the content-addressed bytes in the snapshot store, on demand and never stored
   (`app/ingestion/normalise/pdf.py render_page`, `/admin/dokument/<snapshot>/strana/<page>`).
   Text that came with its own character layer gets no image: a photograph of a document that
   already told us its characters proves nothing, and showing one would make the mark meaningless.
2. **OCR never runs silently.** Low Tesseract confidence on a page routes the document to review,
   in line with invariant 3.

**Consequences:** A keeps the pipeline local, cheap and boring, and turns ~50 manual transcriptions a
year into ~50 quick reviews. B is honest and simplest, but the three affected sources are half the
domestic coverage, and your evenings are the constraint. C is the most accurate on messy scans, and
the worst fit for "no citation, no claim": a model transcript is the one place a paraphrase could
enter the evidence chain unnoticed.

---

## D10 — Which EU portal topics to ingest

> **Default in place since 16.09.2026 (P1 s13); yours to confirm or widen.** It is `SCOPE` in
> `app/ingestion/sources/eu_portal.py`, a one-line edit either way.

The portal listed 1.341 open or forthcoming items on 16.09.2026: 1.142 grant topics, 176 cascade-funding
calls and 23 other calls for proposals. **966 were Horizon Europe**, most of them research topics for
consortia. Every new call waits for your approval before it is published (P1 s15), so the scope is
really a question about your evenings.

**Default: grant topics from five programme areas North Macedonia takes part in** — Digital Europe,
the Single Market Programme, Creative Europe, Erasmus+, and the EIC part of Horizon Europe
(Accelerator, Pathfinder, STEP, prizes). That was 39 topics with a deadline still ahead, about one
evening of first approvals and a trickle after. Participation was checked on 16.09.2026 by web
search: Commission and EEAS announcements for Horizon Europe, Digital Europe and Creative Europe, the
Erasmus+ country page, and reports that North Macedonia signed up to SMP. The portal's
per-programme "list of participating countries" was not read and is the authority; read the SMP one
before approving the first SMP call.

**Left out, with reasons:**
- **The rest of Horizon Europe** (~930 topics). Real opportunities for Macedonian partners, but a
  company rarely leads them and the volume would bury the queue. Revisit when a paying customer asks
  for research consortia.
- **LIFE, CERV, EU4Health and others.** North Macedonia's participation was not confirmed in the
  session. Add each once its participating-countries list names North Macedonia.
- **Cascade funding (type 8, 176 calls).** Often the most SME-relevant money on the portal — open
  calls run by EU projects — but it has no topic JSON; the text lives in the search result and the
  project's own site. It needs its own document shape, so it is a session of its own.

**Consequences:** wider scope means more calls in the shortlist and more first approvals, and more
model spend on extraction. It also means English call text in front of a customer whose report is
in Macedonian (`CLAUDE.md`: human review of any AI Macedonian). Narrower scope is cheaper and
reviewable, at the cost of missing Horizon partner opportunities a competitor may list.

---

## D11 — How the operator signs in to the admin

> **Needed before the first production deploy that ingests real calls.** Until then the admin is
> simply not registered in production (`app/__init__.py`), like `/demo`.

The review queue (P1 s15) publishes calls: the most consequential action in the system. The roadmap
puts sign-in at P3 s44 (magic link, "no password anywhere in the system"), 29 sessions after the
admin exists.

**Options:**

- **A. Magic link to the operator's email**, built with s44: an `account` flagged as operator, a
  one-time link, a session cookie. No password anywhere. Needs transactional email, which needs the
  domain (D2).
- **B. SSH tunnel.** Production serves `/admin` only on a port bound to the VPS's localhost, and Caddy
  refuses `/admin` from outside. You reach it with `ssh -L 8001:localhost:8001 <vps>` and open
  `http://localhost:8001/admin/`. Authentication is your SSH key; no auth code is written. Laptop
  only, in practice.
- **C. Caddy `basic_auth` on `/admin`** over HTTPS. Works from a phone the day it is set up, but it is
  a password (no lockout, no second factor) and contradicts s44's acceptance.

**Recommendation: B at the first deploy, A when s44 lands.** B costs one Caddyfile rule and a compose
port, and its failure mode is "you cannot reach the admin", never "someone else can". Reviewing is an
evening task at a computer anyway: approving a call means reading its quotes in context.

Whichever you choose, the forms already carry CSRF tokens and the session cookie is `SameSite=Lax`,
so the admin is ready for a cookie-based login. `review_queue_item.reviewer_id` stays empty until
there is an account to point at.

---

## Decided in code, not by you

Conservative defaults taken during a session, recorded here so they can be overruled deliberately
rather than discovered later.

### An intake profile lives in the session cookie, not in a row (22.09.2026, P2 s23)

`applicant_profile` needs an `account_id`, and there are no accounts until the magic link at P3 s44
(D11). Rather than invent an anonymous account row, `/profil` keeps the answers in the signed session
cookie, exactly as `/demo` does. It is also the more honest default: nothing is stored about a
visitor who never orders anything, which is what §3.3 of the brief asks for.

**Consequence:** a profile does not survive clearing the browser, and cannot be reached from another
device. The first screen that must persist one is the order (P4), and that is the session that
should create the account and write the row — with `applicant_profile.version`, so a profile edited
after a purchase does not change what the delivered report was computed from.

### The intake form carries a CSRF token, `/demo` still does not (22.09.2026, P2 s23)

`app/web/csrf.py` is now shared between `/admin` and `/profil`, and both check every unsafe request.
The eleven forms on `/demo` do not, because they were written without one and write nothing but the
visitor's own session cookie. Harmless while `/demo` is registered outside production only — but the
day any demo form touches the database, protect the blueprint first.

### The evaluation gate is a command, not a hosted CI service (22.09.2026, P2 s25)

`docs/matching.md` §8 says tier A runs "every commit, in CI", and the roadmap row asks for a harness
that runs in CI. There is no CI in this repository and s25 did not add one. The gate is
`PYTHONPATH=. uv run python evals/run.py`: exit 0 or 1, run before a deploy and after any change to
matching.

Three reasons, in order of weight. **Nothing deploys automatically yet** — P0.5 s4 has not happened,
there is no VPS and no deploy script, so there is no pipeline for a gate to sit in front of.
**The suite is not cheap to host**: PostgreSQL 16 with pgvector, Tesseract with three language
packs, and a 2,2 GB embedding model, rebuilt on a runner for a project maintained on weeknights.
And **a check that is red on every push is a check that gets ignored** — tier A is deliberately red
until s26 fills in the cases, which is exactly the period in which a hosted red badge would train
its only reader to stop looking.

**Revisit when a deploy script exists** (P3): that script calls `evals/run.py` and refuses to
deploy on a non-zero exit, which is what "blocks deploy" in §8 has meant all along. A GitHub
Actions workflow running tier A alone is twenty lines the day the user wants one; the fixtures,
the thresholds and the exit code are already in place for it.

### Old normalised text warns the reviewer; it does not block, and nothing rewrites it (22.09.2026)

Snapshots read before 21.09.2026 keep the missing percent signs and the garbled Albanian for ever:
normalised text is written once (evidence cites it by offset) and an unchanged document is never
fetched again (content hash). The citation check cannot see the problem — the quote *is* verbatim
against our text, which is itself wrong.

**What was built:** the review item now says which of its documents were read by an older version
and what to distrust in them, and `flask ingest stale-text` lists every such snapshot with the
criteria and published calls that cite it.

**What was deliberately not built.** Blocking approval: most quotes out of an old document are
correct, and a block the reviewer cannot clear — there is no re-normalisation path and a re-fetch of
unchanged bytes finds the same row — would only teach them to stop reading notices. And
re-normalisation in place: it moves every offset that cites the text, so every criterion on the call
would silently stop matching. The remedy is to delete the snapshot and let it be fetched and read
again, which is a deliberate job with its own session.

**Before launch:** run `flask ingest stale-text` and clear it. In the development database today it
is three snapshots — the s20 IPARD run and one Skopje document — with nothing published on them.
**P2 s29 must not write verdicts from a snapshot this command still lists.**

### Stage 3: documents are the applicant's, attestations can only go down, Opus reads (22.09.2026, P2 s29)

**A `documentary` criterion is outstanding, like an attestation.** Stage 1 used to call it
undecided, which kept every call listing a required document at `needs_verification` forever. A
document is something the applicant brings; it caps a call at `likely_eligible` and never allows
`eligible`. The user's own s26 verdicts read the calls this way ("what remains is the craft permit
and the declaration").

**Verification reads attestations and may only lower them.** Tier B found that verifying a Skopje
call's craft list made a Bitola craftsman `likely_eligible` for a Skopje-only subsidy — a false
eligible — because residence is an attestation. Making location `hard_structured` needs a new
extraction prompt and lets a rule exclude on it; letting the model contradict an attestation (and
never confirm one) needs neither, and also closes the AV "employee for six months" over-claim for a
company too young to have one. It costs one more model call per attestation of the top five calls.

**`verify_criterion` runs on `claude-opus-5`**, extraction stays on Sonnet 5. The skill reference
this was checked against defaults to Opus and says a downgrade for cost is the owner's call; the
answer is the one a customer reads beside a quote, and report volume is small. Change it in
`config/models.yaml` with an evaluation run behind it. **Not enabled:** the API's server-side
refusal fallbacks. A refusal today is an empty reply, fails validation twice and lands in the review
queue — safe, and no second model to reason about; revisit if tier C shows refusals.

### The shortlist judges every candidate, and shows a window of the source, not the source (22.09.2026, P2 s28)

**Rank-before-judging is not built**, although the roadmap row names it. Stage 1 over 2.000 open
calls takes 274 ms (`matching.md` §3); North Macedonia publishes a few dozen open calls at a time,
the EU portal adds 39 topics in scope (D10). Judging only the best-ranked calls would need batching
to keep ten open calls on the page, and would hide excluded calls further down the order — a moving
part for a registry fifty times the real one. `ops/dev/bench_stage1.py` is the trigger: re-run it
when the open registry passes 2.000.

**Every quote is found again when the page is built**, in one query, not trusted from approval.
A criterion whose quote is not at its offsets any more is undecided, and the call is settled again
from that — so a broken citation can turn `eligible` or `not_eligible` into `needs_verification`
and nothing else. Its passage page answers 404.

**The passage page shows 600 characters either side of the quote**, with the institution's own
link beside it, not the whole stored document. Whether a whole official publication may be
reproduced is P3 s43's question; a short excerpt with a link is the conservative answer until then.

### A registered craftsman is an entity type, and extraction does not know it yet (22.09.2026)

s26 found two of the five evaluation calls turning on a legal form the intake could not express: a
*занаетчија* registered under the Закон за занаетчиство is neither a trading company nor a sole
trader. `EntityType.CRAFTSMAN` (migration `1b093080ae25`), the form «Занаетчија» on `/profil`, and a
boundary profile p11 that differs from p07 in nothing else.

**Sized, like a sole trader.** A craftsman also gets a size band. The EU SME definition counts
"self-employed persons and family businesses engaged in craft" as enterprises whatever their form
(Recommendation 2003/361/EC, Annex Art. 1), and the Economy ministry's call is written on that
footing. The other way would let a call's `in [micro, small, medium]` exclude a craftsman by rule.

**The extraction prompt is not changed.** `prompts/extract_call/2026-09-13.1.md` still lists the
entity values without `craftsman`, so no model can write a criterion on it. That is deliberate:
Skopje's call is for craftsmen *and* holders of a craft permit, who may be companies or sole
traders; an extracted `entity_type in [craftsman]` would exclude those by rule, a false exclusion
invariant 1 would let through because it is a rule. Adding it needs a new prompt version, a
permit question on the intake, and the tier B run of P2 s29 behind it. A reviewer can already
write such a criterion by hand in `/admin`, and should not for that reason.

**Not asked**: whether a company or sole trader holds a craft permit (*вршител на занаетчиска
дејност*). It is what p07/p08's verdicts turn on, but every question costs the three-minute
intake; it waits until a rule or a verification step reads the answer.

### Stage 3 is shown the cited chunk first and searches with the quote alone (23.09.2026, P2 s30)

`matching.md` §5 sketched the verification query as `label_mk + ' ' + source_quote`. Measured over
the frozen calls with every document pooled, the label only made the search worse (it pulled an
English quote under a Macedonian label below the trigram threshold), so the query is now the quote.
And the chunk the criterion cites is placed first without being searched for, because its address
is on record and checked. **What this gives up:** the gated number (24/24 in the top 6) is close to
certain by construction and is not evidence that the ranking is good; the pooled, unpinned number is,
and it rests on five documents. **Not changed:** the trigram threshold, the chunk size and k. The
day a call with a long guideline is approved, add it to the frozen set and re-run
`evals/run.py --retrieval` before touching any of the three.

### A paid report is one job per stored profile, and the profile row keeps its answers (24.09.2026, P2 s31)

`architecture.md` §6 sketched `enqueue(deep_analysis, match_run_id)`, a run the free shortlist had
already written. Nothing writes one: `/profil` keeps the answers in the session cookie (above). So the
job takes an **`applicant_profile` id** — the row P4's order flow will write when someone pays — and
writes its own `match_run`, committed before any model is asked so every model call and review item
points at it (s36 sums cost per run from those). It is marked `stage_reached = 3` only when results,
per-criterion outcomes and evidence are written, in one commit; a run left at 2 is a job that failed,
and running it again makes a new run, with the gateway's cache answering what was already paid for.

**`applicant_profile.answers`** (migration `426a03233500`) holds the intake answers exactly as
posted, and the run reads them back through the same `normalise()` the form ran. The typed columns
could not carry a profile: the form asks for *bands* (2–9 employees, 1–3 million МКД), and an integer
headcount would have to be a guessed number. They are filled where an answer is exact
(`normalise.to_row`) and left empty otherwise. **Only the five verified calls get result rows**;
`candidates_considered` records how many were ranked. **What P4 has to do:** create the account and
the row (`normalise.to_row`), put its id on the order, and call `deep.enqueue` when the payment is
reconciled.

### The report's model writes explanation only, and every sentence cites (24.09.2026, P2 s32)

The design said "prose via strong-tier model". Taken literally, the model would write the report and
the checks would have to find the eligibility claims inside free text, which code cannot do. So the
work is split: **code writes every verdict, condition, reason and quote from the stored run**; the
model writes a summary and, per call, an explanation and next steps, as statements that each name the
conditions they rest on by the number the prompt gave them. A statement without a condition is invalid
output (retried once, then reviewed), and one citing a condition of another call blocks the draft.
What remains unchecked by code — a sentence stronger than its conditions — is the reviewer's, and
every draft is reviewed anyway.

**A blocked draft is queued, not dropped**, marked and ahead of clean ones, because the review queue is
where uncertainty goes. **The lint skips quotes and call titles**: they are the institution's words, a
reviewer cannot edit them, and an English EU title may well contain "approved". **The calls the rules
exclude are now stored by `deep`**, up to ten, with their rule outcomes: this settles the s31 open
question. Reading stage 1 again at composition time would describe that day's registry, not the run's,
and a report must be reproducible. Open calls ranked below the five are still not stored. Opus 5 writes
the prose, for the same reason it verifies. The draft is stored in the review item's `payload`
(`DRAFT_VERSION = 1`); no report table until s35 renders one.

### A report reviewer edits the model's prose, not the verdicts (29.09.2026, P2 s33)

The review screen lets the reviewer rewrite any statement of the model's prose and the condition
numbers it cites, remove one (never a call's last explanation), approve or close. **It does not let
them change a verdict, a condition, a reason or a quote.** Those were written by code from the stored
run; a wrong one is a wrong criterion or a wrong verification, and fixing it in one report would leave
the next report wrong in the same way. The reviewer closes the report with the reason instead, and the
reason becomes an evaluation case (s34). If real drafts show this is too strict — a verification reason
in poor Macedonian, say — the next step is an edit path for reasons with the same lint, not for verdicts.

**An edit is refused whole** if it would fail the schema the model had to meet or add a problem at that
statement, rather than saved and shown as blocking: a reviewer should never be able to store a draft
worse than the one they were given. The approval check runs regardless. **The edited draft is kept
complete in `corrected_payload`** (that is what `blockers()` reads), with an `edits` log of each before
and after; `payload` stays what the model wrote. **The time a review took** is measured from the first
view of the item in the operator's session to the decision, and said back in the confirmation and the
log; nothing stores it, since there is one reviewer and the number is for them.

### A reviewer's decision becomes a case file that is pulled and committed by hand (30.09.2026, P2 s34)

**What is a case**: every extraction or report item a person **rejected or edited**. An approval
without an edit is agreement and holds nothing a case could test; an approval item closed because a
newer one for the same call was approved is bookkeeping (now marked `superseded_by`) and writes
nothing. **Verification items get no decision of their own** — s33 left that to s34 — because nobody
reads them except on their report's page: a run's failed verifications are written inside that
report's case, and the items stay pending. If they ever need closing, close them with the report.

**What a case is not, yet: a scored verdict.** A rejected report says a verdict or a sentence was
wrong, not what the right one was, and its applicant is a shape, not a profile the harness can run.
So the harness loads and shape-checks every case from review (a malformed file blocks, like any bad
case file) and scores none. An extraction case is the model's output, the documents by URL and hash,
and the reviewer's correction — tier C (s36) is what can re-ask the model. Turning a report case into
a tier A case is a person writing a verdict and a profile, which is the s26 convention and stays one.

**Nothing identifying in a file**, because the files leave the server for a laptop and GitHub: the
applicant only as `verify.applicant_shape` wrote it into the draft (never answers, municipality,
profile id or account), documents by URL and hash (public anyway), and everything a person typed —
the note and every edited statement — through the scrubber with the account's e-mail and the
profile's label as known identifiers. The scrubber is the second line; the runbook tells the
reviewer not to write a company name into a note.

**Written on the VPS, committed on a laptop.** Cron writes into `/srv/review-cases`, **outside the
checkout** (a bind mount, `GRANTS_REVIEW_CASES_HOST_DIR`): files written inside it would make the next
deploy's `git pull` refuse. Pulling them with `rsync --ignore-existing` and committing is a weekly
human step — a case enters the suite when a person has read it, which is the point of the loop. The
alternative, a job that commits and pushes from the VPS, would put a deploy key with write access on
the box for the sake of saving one command a week. Each file is written once (atomically, a
temporary file then a rename) and never rewritten, so the job is safe to run at any time.

### The report PDF is set in fonts we ship, merged per weight, and checked by its pixels (30.09.2026, P2 s35)

**Fonts.** "Fonts actually installed on the VPS" is read as: the PDF must not depend on what any
machine has installed. The image has six system fonts, this Codespace fifty-eight, so a render
that looks right here proves nothing there. The PDF uses only the woff2 files the site already
serves, and `render` refuses (a) any character outside their character maps, before rendering,
and (b) any embedded font that is not ours, after. Identifiers are set in Fira Sans with tabular
figures, because the site's monospace is a system font.

**Merged at runtime, not committed.** WeasyPrint 70 embeds the Latin and Cyrillic subsets of one
face under one name and mixes their glyphs (the first render: right Cyrillic, wrong digits and
Latin, and a perfect text layer). Each pair is merged with fontTools once per process from the
shipped files. Committing merged files would work too, but DS2 will re-cut the subsets and a
second copy would drift silently; merging costs about a second per worker start.

**Checks again before printing.** Only `approved` or `edited` items, `compose.blockers()` once
more (the stored text can move after approval), and the lint over the whole printed text,
including the template's own words; the institution's words (quotes, titles) are marked
`data-theirs` and printed but not linted, as in compose.

**On paper a deadline is a date only.** The design system says days in words under 14 on screen;
a PDF is read days later, and "уште три дена" printed on the 30th is wrong on the 2nd. The date
keeps `--seal`. **Not stored**: rendered on demand, reproducible from the stored draft and
`RENDERER_VERSION`; which bytes were delivered is P4 s53's to record.

---

## Summary — what to decide, and by when

| # | Decision | Needed by | My recommendation |
|---|---|---|---|
| D1 | Report price | **P1 s21** (demand test) | 8.900 ден ex-VAT; 4.900 for first 10 |
| D2 | Domain and brand | **P0.5 s4** (deploy) | Descriptive `.mk` + `.com.mk` |
| D3 | First two templates | P5 s58 | FITR, then Employment Agency. Not IPARD first |
| D4 | Contracting entity | P4 s49 | Existing DOO; confirm codes with accountant |
| D5 | Retention periods | P3 s45 | 24 months profiles; invoices per tax law |
| D6 | Free tier depth | P2 s28 | Full top 10 with reasons and citations |
| D7 | Albanian reviewer | Before any SQ content | Defer until a named reviewer is funded |
| D8 | Model spend ceiling | P1 s7 | €30/month with an alarm |
| D9 | OCR for image-only PDFs | ~~P1 s9~~ **decided 13.09.2026**; both reopened gaps closed 21.09.2026 | Tesseract `mkd` locally; OCR citations always reviewed; two narrow second passes, matched by box, supply the `%` and the Albanian blocks |
| D10 | EU portal scope | Before the first EU approvals (P1 s15) | Five programme areas, 39 topics; the default in code |
| D11 | Operator sign-in | Before production ingests real calls | SSH tunnel first, magic link with P3 s44 |

**Two are urgent.** D2 blocks the P0.5 deploy in the first week. D1 blocks the demand test that
decides whether P2 gets built as specified. The rest can wait until their phase.
