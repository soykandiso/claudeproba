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

> **And a second gap (18.09.2026, P1 s20):** the `mkd` model's character set has no `%`. "60%"
> is read as "609", "75%" as "755" or "7595", at confidences that raise no flag. The verbatim check
> passes, because the quote matches the OCR text; the number in it is wrong. `mkd+eng` reads `%`
> but turned "ЕУ" into Latin "EY" in the same test. Options: a second, `eng`-only pass over number
> tokens followed by a `%` substitution when the second pass is confident; or a fine-tuned `mkd`
> model with `%` added. Either is a normaliser version bump with a test set of real rates. Until then,
> every OCR-derived number next to a rate is a reviewer's check. `sources.md` §6.9.

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
| D9 | OCR for image-only PDFs | ~~P1 s9~~ **decided 13.09.2026** | Tesseract `mkd` locally; OCR citations always reviewed |
| D10 | EU portal scope | Before the first EU approvals (P1 s15) | Five programme areas, 39 topics; the default in code |
| D11 | Operator sign-in | Before production ingests real calls | SSH tunnel first, magic link with P3 s44 |

**Two are urgent.** D2 blocks the P0.5 deploy in the first week. D1 blocks the demand test that
decides whether P2 gets built as specified. The rest can wait until their phase.
