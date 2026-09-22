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
| 2 | **EU Funding & Tenders Portal** (Horizon Europe, SMP, IPA III) | All / international | **JSON search API** (`api.tech.ec.europa.eu/search-api`, public key `SEDIA`) + per-topic JSON (`…/data/topicDetails/<id>.json`). No HTML scraping needed | robots: portal paths allowed. Reuse terms not yet read — P3 s43 | Continuous: 1.405 open/forthcoming topics on 13.09.2026 | **Low** for metadata. Eligible countries live in the linked call-document PDF, not the JSON | **2** — built in P1 s13 for the scope in `decisions.md` D10 (§6.6) |
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

**Built in P1 s16 (16.09.2026)** as `app/ingestion/sources/manual.py`: paste up to five URLs (the
call first, then attachments) at `/admin/rachen-vnes`, or run `flask ingest manual <url>...`. The
`manual` row in `config/sources.yaml` is inactive on purpose, so it is never scheduled and never
judged by the health check; instead every entry answers in the review queue, including a failed
fetch or an already-known call. One change was needed outside `sources/`: the pipeline now takes a
call's programme institution from the listing when it names one (`pipeline._singleton_programme`),
because a pasted call comes from whoever published it, not from "manual entry".

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
  only in an admin page you might not open for a week. *(Built in P1 s14: `flask ingest health`, `docs/runbook.md` §4.)*
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

**16.09.2026, P1 s17:** checked again from the Codespace host before building its slot. DNS still
resolves (104.247.81.99); HTTPS and HTTP both time out after 20 s without a TCP connection, three
attempts five seconds apart. Nothing to build against. Until a connection that reaches it exists,
a FITR call can enter through manual entry (§3) only if the operator can download it, since the
crawler cannot. The slot is deferred and P1 continues with s18.

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

### 6.6 EU portal, as built — 16.09.2026 (P1 s13)

`app/ingestion/sources/eu_portal.py`. It needed no change outside `app/ingestion/sources/` and
`config/sources.yaml`: `unwrap`, `significant` and `listing_is_complete` from the AV fetcher were
enough for a paginated API with a JSON document per call. That is the abstraction check this session
existed for.

- **The portal's status field is stale.** 23 of 31 EIC topics listed as "Open" or "Forthcoming" had
  their last deadline in 2023. The fetcher keeps a topic only while a deadline is today or later, so
  a call whose deadlines have all passed drops out of the listing and is closed.
- **Paging is checked, not trusted.** Results are sorted by `identifier` (the API honours it), every
  page is read, and a scope whose results do not add up to `totalResults`, or that returns none,
  fails the run. A failed run closes nothing.
- **Deadline times in the JSON are unreliable:** 00:00 UTC for 2026 topics, 17:00 UTC for 2023 ones.
  Only the date is rendered, and the pipeline reads a date as the end of that day in Skopje.
- **Eligibility is mostly in another document.** Most topics say "Eligible countries: described in
  section 6 of the call document"; the topic JSON gives title, dates, description and where to look,
  and cannot say whether a Macedonian company may apply. Of the 39 topics crawled live, 14 had no
  "call document" link: EIC topics point to the EIC Work Programme (and state much of their
  eligibility inline, which is extracted), Chips JU topics to `chips-ju.europa.eu`, a separate host
  with its own robots.txt. Every link in the conditions goes into the review item's
  `listing.condition_links`. Fetching and extracting that PDF (one document is often shared by
  several topics) is still to do. **Until it is, an EU call's criteria are incomplete by construction.**
  A call with no criteria already comes out `needs_verification` (`taxonomy.call_verdict`), but a
  call with a few satisfied criteria could add up to `eligible` while the country rule sits unread in
  the PDF. **Closed 22.09.2026 (P2 s24):** the fetcher writes `ELIGIBILITY_GAP` on every topic it
  finds, the pipeline stores it in `call.eligibility_gap`, and `app/matching/stage1.py` refuses to
  show such a call as `eligible` or `likely_eligible` however well its criteria come out. It is set
  unconditionally, not only where a condition link was found: a topic states some conditions inline
  and leaves the rest to the call document, and the absence of a link is not evidence of
  completeness. The reviewer sees the same sentence on `/admin` before approving. Fetching and
  extracting those PDFs is still to do; when it is done, the fetcher stops setting the gap.
- **The text is English.** Titles are stored as the document states them. A Macedonian label over an
  English quote retrieves poorly across documents (roadmap P2 s30).
- **Change detection ignores call news.** A topic's `latestInfos` changes whenever anything happens
  in its call; `significant` compares the rendered document instead, so news costs no tokens.
- **Live check, 16.09.2026:** 41 requests (2 search pages, 39 topics), all 39 topics normalised
  without review; rendered text 2.039 to 19.428 characters, median 6.702. Under 4 minutes at one
  request per 5 s.

### 6.7 Economy ministry, as built — 16.09.2026 (P1 s18)

`app/ingestion/sources/economy.py`. No change outside `app/ingestion/sources/` and
`config/sources.yaml`.

- **The listing is calls only, and can be empty.** On 16.09.2026 it read "Во моментот нема активни
  јавни огласи": both calls captured on 13.09 had closed on 15.09 and moved to "Завршени". No rows
  with that message is a quiet source; no rows without it fails the run. A row is a link to a page
  under `/javni-objavi/javni-oglasi/`, which leaves the menu out. The closed listing also carries
  national awards ("Национална награда…") and an EU call advertised on the ministry's behalf
  (EISMEA): extraction decides what is a funding call, and the institution comes from the page.
- **The document is the "Јавен повик" attachment only.** Forms ("Барање", "Образец…") are templates
  and often legacy `.doc`, which the normaliser refuses; they go into the review item's listing.
- **Livewire regenerates a CSRF token and component snapshots on every request.** Two fetches five
  seconds apart differed only there; `significant` strips them.
- **Link labels split digits across spans** ("202<span>6</span>"), as on AV (§6.3).
- **The call PDFs are bilingual, Macedonian and Albanian, with no text layer** — **fixed 21.09.2026,
  §6.11.** A live 12-page call took 99 s to OCR in the worker. Tesseract's `mkd` model read the
  Macedonian cleanly (median word confidence 92) and turned the Albanian into Cyrillic nonsense at
  confidence 0 ("ЕКопотте" for Ekonomisë), so every page's mean landed at 67–75, under the D9
  threshold of 85, and **every Economy call raised an OCR-doubt review item** while extraction saw
  the garbled Albanian too. The normaliser now reads those blocks with `sqi`; the same call raises
  two page-level reasons instead of twelve, and the Albanian is real Albanian.

### 6.8 Skopje and municipal listings, as built — 16.09.2026 (P1 s19)

`app/ingestion/sources/municipal.py`, one fetcher class registered per `sources.yaml` entry with
`access_method: pdf_index` and an `options` block of `kind: municipal_listing` (listing URL, CSS
selectors for the item, its title link, deadline and attachments, which attachment labels are call
documents, which title words mean procurement). A second municipality whose page has that shape is
a copy of the entry with its own selectors; a test builds one with entirely different markup.

**The one change outside `sources/`** is `SourceEntry.options` in `app/ingestion/source_config.py`:
a free-form block, validated by the fetcher that reads it and never written to the database. It is
the smallest thing that lets configuration carry what differs between municipalities, and it is the
abstraction change this session was expected to reveal.

- **The listing is an archive of a year** (38 entries on 16.09.2026, deadlines 31.10.2025 to
  30.11.2026, identical bytes on two fetches). Scope is "Отворен до" today or later in Skopje, so
  a call leaves scope when its date passes and is closed.
- **Only one funding call was open on 16.09.2026**: craft subsidies until 30.11.2026. Live OCR
  read it at mean confidence 92.75 with no review flag (a Macedonian-only scan, unlike §6.7).
- **Titles containing "набавка" are not fetched**: the two open tenders (RAR/ZIP dossiers) and a
  closed call for an expert to evaluate procurements. Everything else goes to the model, which will
  meet taxi licences, urban furniture locations and board nominations and should call them "not a
  funding call"; a reviewer then closes them. Add words to `exclude_titles` only for the unmistakable.
- **"Критериуми" attachments are documents of the call** (festival and project calls keep their
  scoring criteria there); forms and the general rulebook ("Правилник") are listed for the reviewer.
- The call document is linked from the listing itself, so its URL is also the public URL cited.

### 6.9 IPARD, as built — 18.09.2026 (P1 s20)

`app/ingestion/sources/ipard.py`. Outside `sources/`, only `snapshots.without_aspnet_state` learned
one more token name (below); no interface change.

- **The call page is the call.** The programme page (IPARD 2021-2027, `/mk/Home/Ipard/5`) lists all
  six calls with no dates. Each call page (`/mk/Home/IpardPovici/<id>`) gains files in stages on the
  same URL: advance notice, then short and long versions with forms and guides, then a ranking. The
  page is the primary document, so publishing the call **updates** the announced call instead of
  adding a second one. Only the content section (`section.section.mb-3`) is normalised.
- **Scope is "no ranking yet".** A page listing "РАНГ ЛИСТА" is decided: not fetched, and closed if
  it was ingested earlier. Live on 18.09.2026 that left three calls: 03/2025 and 02/2025 (advance
  notice only, text layer, extracted as `advance_notice` → ANNOUNCED) and **02/2024**, published,
  deadline 20.12.2024, never given a ranking on the site. Its extracted deadline closes it in the
  pipeline; it stays in the queue until a reviewer rejects it. Notice-only calls stay announced
  until a reviewer rejects them: the site gives no date to judge them by.
- **Tables go to a human explicitly.** Eligibility, eligible costs and scoring sit in tables in the
  long version, a PDF with no text layer. OCR reads tables row by row, so every IPARD review item
  carries a note (`listing.note`) to check each criterion against the table in the PDF. The long
  version of 02/2024 (26 pages) took most of a 10.5-minute first run to OCR; unchanged, it is never
  read again (content hash). One page raised an OCR-doubt item.
- **OCR could not read `%`** — **fixed 21.09.2026, §6.10.** The `mkd` model's character set (86
  characters) has no percent sign: "75% ЕУ учество" arrived as "755 ЕУ учество", "до 60%" as
  "до 60“", "10%" as "105". Confidence stayed high, so no flag was raised, and a quote containing the
  wrong number still matched verbatim. This affected every OCR-derived document from every source;
  IPARD is where rates decide eligibility. The IPARD reviewer note no longer mentions it and still
  routes the tables themselves to a human.
- **ASP.NET MVC adds a fresh `__RequestVerificationToken`** to every page; it joins `__VIEWSTATE`
  in `without_aspnet_state`.
- Forms, guides and annexes are listed for the reviewer (`listing.other_files`), not extracted.

### 6.10 The `%` restored — 21.09.2026 (out of roadmap order, D9)

`app/ingestion/normalise/pdf.py`; `NORMALISER_VERSION` `2026-09-13.1` → `2026-09-21.1`. Nothing
outside the normaliser changed, and no fetcher was touched except to drop the now-stale half of the
IPARD reviewer note.

Not a fetcher problem and not fixable in one: **an OCR'd page with a digit is now read twice.** The
`mkd` pass is still the text — it is the only pass that reads Macedonian without substituting Latin
look-alikes — and a second `mkd+eng` pass over the *same rendered image* supplies nothing but the
`%` character. The two word tables are matched **by bounding box**, so no text alignment heuristic is
involved: on the IPARD 01/2025 rates every box overlapped 1.00.

A `%` is carried across only where the second-pass token has exactly one `%` and **no letter at all**,
the second pass was confident and `mkd` was not, the boxes overlap, and the `mkd` token is that token
with the `%` replaced by at most two non-letter characters. The full rule, with its numbers and why
each clause is there, is in `decisions.md` D9.

- **Result on the only fixture with rates** (IPARD 01/2025 short version, 3 pages): 6 of 6 rates
  restored — `755`→`75%`, `254`→`25%`, `605`→`60%`, `655`→`65%`, `704`→`70%`, `7556.`→`75%.` — and
  diffed against the single pass, those six tokens were the *only* changes in the document.
- **A `%` that cannot be placed is a review reason**, not a repair. The text keeps what `mkd` wrote,
  because a snapshot is faithful to what the engine read, and an unreadable rate is a human's.
- **Cost:** the OCR time on pages with digits, again. Measured at §6.11: 155 s → 216 s on a 12-page
  call, so ~1.4× for this pass alone. Unchanged documents are still never re-read (content hash).
- **Only new snapshots get this.** Normalised text is written once and never recomputed (property 3
  in `normalise/__init__.py`), so anything ingested before the bump still holds the wrong numbers.
  There is still no re-normalisation path, and an unchanged document is never fetched again — so
  since 22.09 the versions carry their repair history (`REPAIRS` in `normalise/__init__.py`): the
  review item warns, per document, that its text predates this fix, and `flask ingest stale-text`
  lists every snapshot in that state with what cites it. The remedy stays delete-and-re-fetch
  (`decisions.md`, "Decided in code"; `runbook.md` §5).

### 6.11 The Albanian half, read — 21.09.2026 (out of roadmap order, D9)

`app/ingestion/normalise/pdf.py`; `NORMALISER_VERSION` `2026-09-21.1` → `2026-09-21.2`, plus two apt
packages in the `Dockerfile`. Again nothing outside the normaliser; no fetcher changed. The two
21.09 fixes are separate versions on purpose: `.1` restored `%` only, and one version must never
mean two behaviours (property 2 in `normalise/__init__.py`). Nothing was ingested under `.1`.

Every Economy call is a bilingual Macedonian–Albanian PDF, and `mkd` cannot read the Albanian at all.
The fix is **not** to stop counting the Albanian against the page — that hides the unread half and
leaves extraction indexing nonsense — but to read it. Tesseract already puts the two languages in
**separate blocks**, so a page with a block below `LOW_WORD_CONFIDENCE` is read again with `sqi`, and
a whole block is swapped where the second pass is unambiguously better. The full rule is in
`decisions.md` D9; the safety argument is the same one as §6.10's: a Latin-script model is only ever
applied where the Macedonian one demonstrably failed, so it cannot corrupt Cyrillic it never touches.

- **Measured over all 20 pages of both bilingual calls**: identical block sets in both passes on
  every page, and no block where the two languages were within the 25-point margin. Page means
  67–75 → 83–95.
- **End to end on call 1 (12 pages)**: document mean 67–75 per page → **90.31**, review reasons
  **12 → 2**. The two that remain are genuinely poor pages, and page 12 has no Albanian on it at all.
- **The Albanian reads correctly**, with diacritics: "Republika e Maqedonisë së Veriut", "Ministria e
  Ekonomisë dhe Punës", "THIRRJE PUBLIKE". Under `mkd` those were "ЌКеририка е Мадедопј56",
  "Миц5Ена е ЕКопотј!56 аПе Рипе5", "ТИКВЕЈЕ РОВЦКЕ".
- **A degraded scan is not rescued.** The 75 dpi Skopje calibration page reads no better in Albanian
  than in Macedonian, so nothing is swapped and its review reason stands. Only a page unreadable
  because of its *language* comes back.
- **New:** a model can now quote Albanian into a criterion, which a reviewer who does not read
  Albanian cannot check. This is a second reason for D7's named Albanian reviewer, and it bites
  before `sq` ships.
- **Cost:** on the same host and document, 155 s single-pass → 263 s with both passes, **1.7×**
  (§6.10 guessed "roughly double" from a cold run; this is the controlled number). 61 s of that is
  the `%` pass, which found nothing here — this call has no rates.
- The source PDFs are too large to commit, so the test set is the recorded **word tables**
  (`tests/fixtures/economy/call-1.words.json`, pages 1 and 12).
