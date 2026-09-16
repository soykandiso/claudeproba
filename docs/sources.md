# Ingestion sources

> **Reconnaissance ran on 13.09.2026** (§6). Five of the six rows below are now observations, not
> expectations. **FITR is still unverified**: its server did not answer from the reconnaissance
> machine, so its row keeps `UNVERIFIED` until it is checked from a connection that reaches it.

You answered that **all four applicant segments** are in scope. That decision is honoured below —
each of the first six sources serves a different segment — but it comes with a trade-off worth
stating plainly: six sources spread across four segments means roughly one source per segment, so
coverage is **broad and thin** rather than narrow and deep. A competitor focused only on IPARD will
have better agricultural coverage than you on day one. The mitigation is in §5: after P1, expansion
order is driven by where paying demand actually appears, not by keeping the four segments balanced.

---

## 1. The matrix — first six

Priority 1–2 are built in P1a (pipeline proof). Priorities 3–6 are built in P1b as repetitions of
the proven pattern.

| # | Source | Segment | Access (observed) | Legal check | Cadence (observed) | Parsing difficulty | Priority |
|---|--------|---------|-------------------|-------------|--------------------|--------------------|----------|
| 1 | **ФИТР** — Фонд за иновации и технолошки развој (`fitr.mk`) | Startups / tech | HTML listing → per-call page + PDF guidelines `UNVERIFIED` — **host did not respond** (§6.1) | robots + ToS `UNVERIFIED` | Bursty: several calls/year, clustered `UNVERIFIED` | **Medium** `UNVERIFIED` | ~~1~~ **3** (§6.1) |
| 2 | **EU Funding & Tenders Portal** (Horizon Europe, SMP, IPA III) | All / international | **JSON search API** (`api.tech.ec.europa.eu/search-api`, public key `SEDIA`) + per-topic JSON (`…/data/topicDetails/<id>.json`). No HTML scraping needed | robots: portal paths allowed. Reuse terms not yet read — P3 s43 | Continuous: 1.405 open/forthcoming topics on 13.09.2026 | **Low** for metadata. Eligible countries live in the linked call-document PDF, not the JSON | **2** |
| 3 | **Агенција за вработување на РСМ** (`av.gov.mk`) | SME employment | **JSON endpoint** behind the listing: `POST /services/ServiceJobAnnouncements.asmx/GetActiveEmploymentMeasures` (full archive since 2016) and `…DescriptionForBusinessMk` with `{detailId}` (full call text as HTML). The HTML listing itself is empty without JavaScript | robots allows `/services/`; **disallows `*.pdf`**, which the JSON makes unnecessary. No ToS published | 20–44 announcements/year (2016–2025); 10 so far in 2026. Peaks May–June and September | **Low-medium** — clean JSON; description HTML splits numbers across spans (§6.3) | ~~3~~ **1** — built in P1 s11 (§6.1) |
| 4 | **Министерство за економија и труд** (`www.economy.gov.mk`, attachments on `portal.mdt.gov.mk`) | SME / trade | Server-rendered HTML: "Јавни огласи" and "Завршени јавни огласи" are separate listings, so call-vs-news is **not** a problem. Call page = title, deadline, attachment links. Call text is in PDF or DOCX attachments | robots: only `/login` disallowed on both hosts. No ToS published | ~14 closed calls with deadlines in 2024–2026 (3 / 8 / 3); archive starts 2024. Deadlines cluster Aug and Nov | **High** — both open calls' PDFs have **no text layer** (glyphs exported as images); one call is DOCX only (§6.2) | 4 |
| 5 | **Град Скопје** (`skopje.gov.mk`) | NGO / municipal | Server-rendered HTML "Јавни повици", each entry a direct link to a PDF. Only a deadline ("Отворен до") is shown, no publication date. Procurement tenders are mixed in | No robots.txt (404). No ToS published | ~40 entries over the listed year (deadlines 31.10.2025–30.11.2026) | **High** — all three sampled PDFs are **scanner output with no text** (§6.2). Tenders must be filtered out | 5 |
| 6 | **АФПЗРР / IPARD** (`www.ipardpa.gov.mk` — bare domain returns 404 on every path) | Agriculture / rural | Server-rendered HTML. "Програма 2021-2027" lists calls; each call page links a ПРЕТХОДНА НАЈАВА, then the call (short and long version) and annexes | No robots.txt (404). "© All rights reserved" footer, no ToS | IPARD 2021–2027: 1 call in 2023, 2 in 2024, 3 in 2025, none yet in 2026. National-programmes tab empty on 13.09.2026 | **High** — advance notices have text; both call versions of 01/2025 have **no text layer** (§6.2) | 6 |

### Why this six, and why in this order

- **FITR and the EU portal are built first, together.** *(Superseded 16.09.2026: FITR is unreachable
  from a datacenter, so AV — also a domestic source, and JSON rather than HTML — took its slot. See
  §6.1.)* They are the two extremes: one hard HTML
  scrape of a domestic site, one structured international feed. Getting the fetcher, normaliser and
  extractor interfaces to serve both is what proves the abstraction. If they only ever served FITR,
  source #2 would break them.
- **IPARD is last, despite being the highest-value segment.** It is the hardest parse in the set —
  long PDFs with tabular eligibility and annexes — and doing it first would mean debugging PDF table
  extraction before the pipeline around it works at all. Its value does not change; its position in
  the queue does. (See `decisions.md` D3 for the related question of which programmes to *template*
  first, where the answer is also not IPARD.)
- **Skopje is cheap and proves a pattern.** Once the municipal fetcher works, other municipalities
  are configuration rather than code — the fastest coverage expansion available after P1.

---

## 2. Deferred sources, with reasons

| Source | Why not in the first six | Revisit when |
|---|---|---|
| **Развојна банка на Северна Македонија** | Publishes **credit lines and guarantees**, not grants. Different product logic: interest rates, collateral, repayment. Mixing it into a grant registry would distort both the schema and the matching scores. | P6+, as a separate `instrument_type`, if customers keep asking |
| **data.gov.mk** | Open-data metadata, not call-shaped documents. Useful later as a *reference* dataset (municipality codes, NACE registries, company registry extracts) rather than as a call source. CKAN API likely available `UNVERIFIED` | P2, for reference data used in profile normalisation |
| **Erasmus+ / Creative Europe own portals** | Substantially covered through the EU portal already; their own portals are heavy and duplicate that coverage | After measuring how much the EU portal actually misses |
| **EBRD / EIB / WB EDIF** | Instruments delivered through partner banks, not open calls with deadlines. Rarely publish an applicable "call" an SME can apply to directly | P6+, as advisory content rather than registry entries |
| **UNDP / GIZ / Swiss / Nordic bilateral** | Ad-hoc publication, low and irregular cadence, no common format. High manual cost per item captured | P3+, possibly as a manual-entry source (see §3) |
| **Other municipalities** | Each is a small variation of the Skopje pattern | Immediately after Skopje works — configuration, ~1 evening for several |

---

## 3. `manual` is a first-class access method

Some genuinely valuable sources (bilateral donors, one-off ministry announcements you hear about
before they are posted) will never justify a scraper. `source_feed.access_method = 'manual'` plus an
admin form that accepts a URL, stores a snapshot and runs the same extraction pipeline gives those
sources the same citation quality as automated ones, at the cost of two minutes of your time. Build
it in P1b — it is cheap, and it stops you from writing a bad scraper for a source that publishes four
times a year.

---

## 4. Reconnaissance protocol (P1, session 1)

Before any fetcher is written, do this once per source and record the result in this file. It is one
evening for all six, and it is the highest-leverage evening in P1.

1. Fetch `/robots.txt`. Record the date and whether the call listing paths are permitted.
2. Find and read the terms of use. Record the URL and a one-line note on reuse of published content.
3. Locate the call listing page. Check for RSS, Atom, a JSON endpoint, or a sitemap — check the
   page source and the network tab, not just the visible UI. **Prefer API or RSS over HTML always.**
4. Save three representative call pages to `tests/fixtures/<source>/`. These become the parser
   fixtures and the frozen snapshots the evaluation harness runs against.
5. Walk the archive back two to three years and record actual publication dates. This produces a
   real `expected_cadence` and `staleness_sla` instead of a guess, and it doubles as the seasonality
   data needed for `risks.md` R4.
6. Note whether the page renders server-side. **A source that requires JavaScript to list its calls
   is disqualified from the first six** (architecture §9.4) — substitute the next deferred source.
7. Fill in the row above, delete its `UNVERIFIED` markers, and commit.

---

## 5. Standing ingestion rules

These apply to every source, present and future, and are restated in `CLAUDE.md`.

- **Identify honestly.** `User-Agent: grantbot/1.0 (+https://<domain>/crawler; <contact email>)`, and
  that URL must resolve to a page explaining what the crawler does and how to ask it to stop.
- **Respect `robots.txt`, terms of use, and a conservative rate limit** — default 0.2 requests per
  second per host, one concurrent connection. There is no scenario where crawling a ministry faster
  is worth the phone call.
- **Content-hash every fetch.** Unchanged bytes cost zero tokens. This is the primary cost control
  in the entire system.
- **Store the raw snapshot, always**, even when parsing fails — especially when parsing fails.
- **Every source has a staleness SLA and alerts on breach.** A silently dead scraper is the primary
  failure mode of this business (`risks.md` R1). The alert must reach you outside the system, not
  only in an admin page you might not open for a week.
- **Surface `last_verified_at` in the UI on every call**, per brief §12.
- **Expansion after P1 follows demand, not symmetry.** When a segment produces paying customers, add
  its adjacent sources next. Do not add sources to keep the four segments evenly covered.

---

## 6. Reconnaissance findings — 13.09.2026

Run from a GitHub Codespace (US Azure datacenter), `User-Agent: grantbot/0.1 (reconnaissance;
+https://github.com/soykandiso/claudeproba)`, at most one request per 5 seconds per host. Captured
files and their hashes are listed in `tests/fixtures/README.md`.

### 6.1 FITR did not respond

`fitr.mk` and `www.fitr.mk` resolve (104.247.81.99) but every connection timed out, on HTTPS and
HTTP. The likeliest explanation is that the host drops traffic from datacenter or non-Macedonian IP
ranges. That matters beyond reconnaissance: **the production crawler also runs from a datacenter**.
Before building the FITR fetcher (P1 s11), check from a Macedonian home connection and from the EU
VPS. If the VPS is blocked too, FITR becomes a `manual` source (§3) or needs to be asked to allow
the crawler — and the priority-1 slot should go to AV, which has the cleanest access of the six.

**16.09.2026:** still timing out from the Codespace, and there is no EU VPS yet to test from (P0.5 s4
not done). AV took the priority-1 slot and is the fetcher built end to end in P1 s11
(`app/ingestion/sources/av.py`). FITR stays in `config/sources.yaml` at priority 3, inactive, until it
has been checked from a Macedonian connection and from the VPS.

### 6.2 Most domestic call documents have no text layer

This is the most consequential finding. Of the PDFs sampled:

| Source | Document | Pages | Extractable text |
|---|---|---|---|
| Economy | two open calls (2026) | 12, 8 | none — Word 2019 export, ~90 images per page |
| Skopje | three calls (2026) | 2 each | none — "Adobe PSL for Canon", i.e. scanned paper |
| IPARD | call 01/2025, short and long | 3, 26 | none — Word 2019 export |
| IPARD | advance notice 03/2025 | 2 | yes |
| Economy | one call published as DOCX | — | yes |

The architecture's normaliser (`pypdf`, `pdfplumber`) returns nothing for these. The AV and EU
sources are unaffected (JSON). Three consequences:

1. **An OCR step is needed for three of six sources**, or those calls go to manual review. That is
   an open decision: `decisions.md` D9.
2. **DOCX needs a normaliser path** alongside HTML and PDF.
3. **Citations over OCR text are weaker.** "Verbatim in the chunk" then means verbatim in the OCR
   output, which can differ from the paper. Any OCR-derived citation should be marked as such and
   pass human review before a customer sees it.

### 6.3 Details that will bite a fetcher

- **AV descriptions split numbers across styled `<span>`s** — naive tag stripping yields `202 3` and
  `21 .09 .2023`. The normaliser must join inline elements without inserting whitespace, or quotes
  will not match the source.
- **The ministry is now Министерство за економија и труд.** Attachments are served from a second
  host, `portal.mdt.gov.mk`; the rate limit and robots check apply per host.
- **Economy dates are `dd/mm/yyyy`**, AV `dd.mm.yyyy` plus `/Date(ms)/`, Skopje `dd.mm.yyyy`, EU
  ISO 8601. Parse per source; display always `dd.mm.yyyy`.
- **IPARD publishes in two stages** (advance notice, then call). Calls 02/2025 and 03/2025 only ever
  carried the advance notice on the site. Map advance notices to `CallStatus.ANNOUNCED`, never
  to `open`.
- **Skopje mixes procurement tenders** ("Јавен повик за набавка…") into the calls listing. Filter them
  out; they are not funding.
- **Official documents mix Latin look-alike letters into Cyrillic words.** The Economy call DOCX has
  "Mинистерството", "зa", "машинa"; the IPARD notice "Aлтернативно". 7 such words across 2 of 5
  documents. The normaliser keeps them (faithful), and `find_quote(..., fold=True)` matches them
  against an all-Cyrillic quote without moving offsets. Whether verification uses folding is P2 s29.
- **ASP.NET pages regenerate `__VIEWSTATE` on every request.** av.gov.mk returned the same listing
  twice, seven seconds apart, differing only in that field. Such a source's fetcher overrides
  `Fetcher.significant` with `snapshots.without_aspnet_state`, or every run looks like a change.
- **av.gov.mk's robots.txt starts with a byte-order mark and uses a wildcard (`*.pdf`).** Python's
  `urllib.robotparser` honours neither, and would have allowed the PDFs. `app/ingestion/robots.py`
  implements RFC 9309 matching instead.
- **Containers in a Codespace cannot reach the internet** without the iptables rules in `README.md`;
  every source then fails closed as "robots.txt unreachable", which is the correct failure.
- **The EU search returns the same topic identifier several times** (per deadline/type). Deduplicate
  on `identifier`. `frameworkProgramme` is a numeric code that needs a lookup.

### 6.4 Seasonality (`risks.md` R4)

AV announcements peak in **May–June** and again in **September**, and are thinnest in December and
January. Economy deadlines cluster in **August and November**. IPARD calls have come one to three per
year. The demand test in P1 s21 should avoid December–January, when almost nothing is open.

### 6.5 Still open after this session

- FITR, entirely (§6.1).
- EU portal reuse terms: the legal notice page is rendered client-side and was not read. P3 s43.
- No domestic source publishes terms of use; reuse of official publications is the P3 s43 question.
- Economy call PDFs (2.0–2.5 MB) and the IPARD long call (5.2 MB) were not committed as fixtures;
  their URLs and SHA-256 are in `tests/fixtures/README.md`.

