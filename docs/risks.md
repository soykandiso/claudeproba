# Risk register

The eight risks from brief §11, each with likelihood, impact, mitigation, and — the column that
actually matters — **the earliest cheap test that would reveal it**. A risk without a cheap early
test is a risk you will discover expensively.

Scale: Low / Medium / High. Impact is measured against the business surviving, not against
inconvenience.

---

## R1 — A source changes layout or blocks the crawler, and matches go stale silently

| | |
|---|---|
| **Likelihood** | **High.** Not "if" — government sites are redesigned, move to new domains, and add bot protection without notice. Assume at least two breakages per year per source |
| **Impact** | **High.** This is the failure mode that kills the business quietly: the site keeps working, results keep rendering, and they are wrong. A customer pays for a report about a call that closed six weeks ago |
| **Mitigation** | Per-source `staleness_sla` with alerting that leaves the system (email plus an external heartbeat service, so a dead box is noticed by something that is not the box). `last_verified_at` displayed on every call in the UI (brief §12), so staleness is visible to users, not just to you. Parser fixtures per source in CI — a layout change breaks a test before it breaks production. Raw snapshots stored even on parse failure, so recovery does not require re-crawling |
| **Earliest cheap test** | **P1 session 14.** Deliberately point one source at a dead URL in staging and confirm the alert reaches you outside the app within its SLA window. Fifteen minutes of work, and it is the single most valuable alarm in the system |

---

## R2 — The model reports a company as eligible when it is not, and a customer wastes real money

| | |
|---|---|
| **Likelihood** | **Medium** with the architecture as designed; **High** without it. LLMs are confidently wrong about grant criteria, and their training data on Macedonian programmes is stale by construction |
| **Impact** | **Critical.** An SME spends weeks and consultant fees preparing an application it could never win. In a market the size of Skopje, that story reaches everyone who would have been your next ten customers |
| **Mitigation** | Structural, not procedural. (a) Only `hard_structured` rules can produce `not_eligible`, and the model's output vocabulary cannot express a user-facing verdict at all — it returns `satisfied`/`not_satisfied`/`unclear` and code does the mapping. (b) Every quote must be found **verbatim** in the chunk it cites, checked in code. (c) Missing data downgrades to `needs_verification`, never upgrades. (d) Human review gate on every paid report. (e) Evaluation harness treats a false `eligible` as a **zero-tolerance, deploy-blocking** failure. (f) Banned-phrase lint on all customer-facing prose |
| **Earliest cheap test** | **P2 session 26**, your verdict-marking session. Take one call you know intimately, run 10 engineered boundary profiles through it, and count false `eligible` results. If it is not zero, stage 2 does not ship |

---

## R3 — Willingness to pay is lower than assumed in the Macedonian SME market

| | |
|---|---|
| **Likelihood** | **Medium-High.** Macedonian SMEs are price-sensitive and accustomed to consultants who charge on success, not up front. "Pay 8.900 MKD to find out whether you qualify" is a harder sell than it looks from inside the build |
| **Impact** | **High.** Not fatal to the code, fatal to the business model. The platform would become a lead generator for your existing consulting practice — which is a viable outcome, but a different one, and better discovered early |
| **Mitigation** | Test before building. Free shortlist genuinely useful on its own (brief §12) so the funnel exists regardless. Three revenue lines rather than one — report, document package, subscription — with the package priced where the real value is (an IPARD package is worth 20× a report). Pricing options and break-even maths in `decisions.md` D1 |
| **Earliest cheap test** | **P1 session 21**, ~30 sessions earlier than the brief's sequencing would find out. Landing page, real price, report fulfilled **by hand** from registry data. If five prospects say no at the real price, the product changes before P2 is built (architecture §9.9) |

---

## R4 — Calls are seasonal, so demand is spiky and revenue is lumpy

| | |
|---|---|
| **Likelihood** | **High.** Close to certain. Employment measures cluster after the annual operational plan; IPARD opens in defined windows; EU deadlines cluster around cut-off dates |
| **Impact** | **Medium.** Cash-flow pain rather than existential, but it distorts every early signal you read — a quiet October looks like product failure when it is just the calendar |
| **Mitigation** | The monitoring subscription exists precisely to convert spiky transactions into recurring revenue. Document packages extend each spike (a call that opens in March generates package work through May). The public archive draws traffic in dead months. Digest emails in busy seasons so bursts do not become spam |
| **Earliest cheap test** | **P1 session 6**, free as part of reconnaissance. Walk each source's archive back 2–3 years and plot actual publication dates. One evening produces the seasonal shape of your entire market — and tells you whether session 21's demand test is landing in a dead period (`roadmap.md` §8) |
| **Observed (13.09.2026)** | AV announcements peak May–June and September, thinnest December–January; Economy deadlines cluster in August and November; IPARD 1–3 calls/year. Detail in `sources.md` §6.4 |

---

## R5 — Personal data exposure through model API calls

| | |
|---|---|
| **Likelihood** | **Low** if enforced in code, **Medium** if left to discipline. The realistic leak is not a designed one; it is a debug log, an error report, or a prompt someone adds in a hurry at 23:00 |
| **Impact** | **High.** GDPR-aligned Macedonian law, a B2B customer base that cares, and a trust product. Also a disclosure obligation |
| **Mitigation** | The LLM gateway is the **only** code path permitted to reach a provider, and it scrubs at the boundary: names, EMBS, EDB, addresses, phones, emails removed or pseudonymised. The model receives the *shape* of an applicant — size band, NACE, region code, age band, investment band. Buyer identity fields live on `order` and never enter a matching payload at all. `model_call_payload.request_json` stores exactly what left the building, so the claim is auditable rather than asserted. Turnover is stored banded, not exact, by design |
| **Earliest cheap test** | **P1 session 7.** A unit test that builds a payload from a fixture profile stuffed with a name, EMBS, EDB, address, phone and email, and asserts none of them appear in the outgoing JSON. It runs on every commit forever and costs nothing after the first hour |

---

## R6 — Liability framing: this is information and drafting assistance, not legal, tax or financial advice

| | |
|---|---|
| **Likelihood** | **Medium** that a customer eventually treats a report as a guarantee and complains. **Low** that it becomes a formal claim |
| **Impact** | **High** for reputation in a small market, **Medium** legally if the framing is correct and consistent |
| **Mitigation** | Plain-language ToS in Macedonian stating what the service is and is not. Graded verdicts throughout, never binary. Banned-phrase lint enforcing that "guaranteed", "approved" and "you will receive" cannot appear in any generated text. Every claim citation-backed, so a dispute is resolved by reading the source rather than by argument. Generated documents labelled AI-assisted and human-reviewed, with financial and legal fields left explicitly unfilled (brief §8). No submission to any authority on the user's behalf in v1 |
| **Earliest cheap test** | **P3 session 45**, and cheaper still: one hour with a lawyer reviewing the ToS and one report sample. Do this before the first paid delivery, not after. The banned-phrase lint (P2 session 32) is the automated half and costs an hour |

---

## R7 — Single-operator bus factor: what happens if you are unavailable for two weeks

| | |
|---|---|
| **Likelihood** | **Medium.** Illness, travel, a demanding fortnight at work. Over a multi-year horizon, near-certain at least once |
| **Impact** | **High** if it happens with unreviewed paid orders in the queue: customers who have paid and are waiting, with no one able to deliver. Low if the system degrades gracefully |
| **Mitigation** | A documented **graceful degradation mode**: a single flag that stops accepting new paid orders, shows an honest banner with a return date, and keeps the free shortlist and archive running. Automated ingestion continues unattended — it needs no human. `docs/runbook.md` covers deploy, restore, common failures, and how to refund an order, written so that a competent developer who is not you could follow it. Deliver-before-holiday discipline: never leave a paid order unreviewed overnight before a planned absence |
| **Earliest cheap test** | **After P4, one deliberate 10-day hands-off period.** Touch nothing, then read what broke: which alerts fired, what silently stopped, what a waiting customer would have seen. Costs nothing but attention, and it is the only way to learn this before it is forced on you |

---

## R8 — Competition from the ministries themselves publishing a better portal

| | |
|---|---|
| **Likelihood** | **Low-Medium** for a genuinely good aggregated portal. Public bodies publish their own calls well and other institutions' calls badly, and a cross-institutional portal requires coordination that rarely survives contact with institutional boundaries |
| **Impact** | **Medium**, and narrower than it first appears. A government portal would compete with the free shortlist — which is the part you give away — not with clause-level eligibility verification against a specific company profile, and certainly not with document drafting |
| **Mitigation** | Do not compete on listing. The defensible assets are: cross-source aggregation including international programmes no ministry will ever list; per-applicant eligibility verification with citations; document packages; and the archive of extracted, structured criteria accumulated over years, which nobody can rebuild retroactively. If a ministry does publish a good API, that is **good news** — a cheaper source with a better cadence. Design `source_feed` so a new official API is configuration, not a rewrite |
| **Earliest cheap test** | **Free, continuous.** Track the digital-agenda and e-government roadmaps, and watch whether any institution starts publishing structured open data for calls. A ministry announcing a portal gives 12–18 months of warning; the mitigation is to have already moved up the value chain into drafting by then |

---

## Summary: what to watch

| Risk | Watch for | Earliest test |
|---|---|---|
| R1 dead scraper | No new items past SLA | P1 s14 — break one on purpose |
| R2 false eligible | Any non-zero count in the eval suite | P2 s26 — one call, 10 profiles |
| R3 willingness to pay | Five explicit nos at the real price | P1 s21 — sell a hand-made report |
| R4 seasonality | Publication dates over 3 years | P1 s6 — free during reconnaissance |
| R5 PII leakage | Any identity field in an outgoing payload | P1 s7 — one unit test, forever |
| R6 liability | "Guaranteed" surviving into any output | P2 s32 lint + P3 s45 legal hour |
| R7 bus factor | Paid orders ageing in the queue | Post-P4 — a real 10-day absence |
| R8 competition | Structured open data for calls appearing | Continuous, free |

**The three worth acting on first are R1, R2 and R3.** R1 and R2 are architectural and are already
built into the design; R3 is commercial, is the one the architecture cannot solve, and is the reason
session 21 exists.
