# Ingestion sources

> **Every access-method, cadence and difficulty claim in this document is `UNVERIFIED`.**
> They are informed expectations, not observations. Session 1 of P1 is reconnaissance (§4) and
> replaces each `UNVERIFIED` marker with a checked fact. Building a scraper against an unverified
> assumption is how you lose an evening; building six of them is how you lose a month.

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

| # | Source | Segment | Access (expected) | Legal check | Cadence (expected) | Parsing difficulty | Priority |
|---|--------|---------|-------------------|-------------|--------------------|--------------------|----------|
| 1 | **ФИТР** — Фонд за иновации и технолошки развој (`fitr.mk`) | Startups / tech | HTML listing → per-call page + PDF guidelines `UNVERIFIED` | robots + ToS `UNVERIFIED` | Bursty: several calls/year, clustered `UNVERIFIED` | **Medium** — structured call pages, guidelines in PDF | **1** |
| 2 | **EU Funding & Tenders Portal** (Horizon Europe, SMP, IPA III) | All / international | Believed to expose a JSON search API (SEDIA); fall back to HTML `UNVERIFIED` | Portal ToS permit reuse `UNVERIFIED` | Continuous, high volume | **Low if API / High if not** | **2** |
| 3 | **Агенција за вработување на РСМ** (`av.gov.mk`) | SME employment | HTML "Огласи / Јавни повици" + annual Оперативен план PDF `UNVERIFIED` | gov robots `UNVERIFIED` | Annual plan ~Q1, individual measures rolling `UNVERIFIED` | **Medium** — the annual plan PDF is the real payload | 3 |
| 4 | **Министерство за економија** (`economy.gov.mk`) | SME / trade | HTML; calls mixed into news `UNVERIFIED` | gov robots `UNVERIFIED` | Irregular, a handful per year `UNVERIFIED` | **Medium-high** — call vs news disambiguation is the hard part | 4 |
| 5 | **Град Скопје** (`skopje.gov.mk`) | NGO / municipal | HTML "Јавни повици и конкурси" `UNVERIFIED` | gov robots `UNVERIFIED` | Several per year, seasonal `UNVERIFIED` | **Low** — small, simple pages | 5 |
| 6 | **АФПЗРР / IPARD** — Агенција за финансиска поддршка во земјоделството и руралниот развој | Agriculture / rural | HTML index → large PDF call packages `UNVERIFIED` | gov robots `UNVERIFIED` | IPARD a few/year; national measures annual `UNVERIFIED` | **High** — long PDFs, tabular eligibility, annexes | 6 |

### Why this six, and why in this order

- **FITR and the EU portal are built first, together.** They are the two extremes: one hard HTML
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
