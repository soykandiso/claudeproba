# Matching engine

> The governing rule of this document, from brief §3.4: **deterministic rules decide eligibility;
> the model never does.** Everything below is an elaboration of that one sentence.

---

## 1. Stage overview

| Stage | What it does | Where it runs | Budget |
|---|---|---|---|
| 0 | Normalise the profile | web request | < 50 ms |
| 1 | Hard filter — remove what the applicant cannot legally apply for | web request | < 1 s |
| 2 | Score and rank the survivors | web request | < 3 s |
| 3 | Verification pass — retrieval + model, top 5 only | RQ worker | minutes |
| 4 | Human review gate | admin UI | your evening |

Stages 0–2 are the free shortlist and must feel instant. Stages 3–4 are the paid report and are
asynchronous with email notification — **and the customer-facing promise is "within one business
day", not three minutes** (architecture §9.2).

---

## 2. Stage 0 — normalise

Raw intake answers become the canonical attributes the rules operate on. Deterministic, cached,
unit-tested against a fixture table.

```
normalise(intake) -> profile:
    profile.nace_code        = resolve_nace(intake.sector_text or intake.nace_input)
    profile.nace_prefixes    = ['62.01', '62', 'J']      # hierarchy, for proximity scoring
    profile.municipality     = resolve_municipality(intake.municipality)
    profile.region_code      = REGION_OF[profile.municipality]   # and: is it in Град Скопје?
    profile.age_months       = months_between(intake.founded_year, today)
    profile.size_band        = eu_sme_band(intake.headcount, intake.turnover_band)
                               # micro <10, small <50, medium <250, else large
    profile.investment_band  = band(intake.investment_size_mkd)
    return profile
```

Reference tables (NACE, municipalities, regions) are **versioned data files in the repository**, not
rows someone edits in production. A changed classification must show up in a diff.

**Built 22.09.2026** as `app/matching/normalise.py` over `data/` (`app/matching/reference.py`), with
the thirty-odd intakes in `tests/fixtures/intake/profiles.yaml` as the acceptance. Four things the
implementation settled, all of them consequential later:

- **Everything is a `Range`.** Intake asks for a band of employees and a founding year, so a company
  founded in 2022 is 44–56 months old and a criterion needing 48 gets *unclear*, not a rounded yes.
  That is the same conservatism §3 already applies, moved one stage earlier.
- **A Macedonian section letter is not the Latin one** — manufacturing is section `C`, written `В`.
  `resolve_nace` accepts either alphabet; nothing else may guess (`data/README.md`).
- **The size band is the EU SME definition**, headcount *and* turnover: turnover can only push a
  band up, never pull it down. Only one intake answer can do it — over 150 million МКД is past the
  micro ceiling of €2 million however few people a company employs.
- **A legal form does not imply a size band.** A company and a trader get one; an association and a
  farm do not, because a call writing `not_in [micro]` is not talking about them, and reading it as
  though it were would exclude them silently.

Geography is still **not** in the rule vocabulary (`app/matching/operators.py`). The data it was
waiting for now exists, but adding `region_code` there lets a criterion exclude on location, which
needs a new extraction prompt version and an evaluation run — so it belongs to s24, with the harness
of s25–26 behind it, not to the session that produced the files.

### The questions themselves

**Built 22.09.2026** as `app/matching/intake.py`: the eleven questions, their Macedonian wording,
what a refused answer is told, and the labels that say a profile back to the applicant. The form at
`/profil` renders it (`app/web/intake/`), and so does `/demo/profil` — one questionnaire, one
validation, one stage 0.

Two decisions in it that the rest of matching depends on:

- **Only four answers are required** — legal form, municipality, founding year and headcount. Every
  other question may be skipped, because an answer that is not given is `None`, and `None` is
  *unclear*, which asks rather than excludes (§3). Requiring more would buy nothing in correctness
  and cost the three minutes the roadmap's acceptance is measured in.
- **An unresolvable activity is an error, not a silence.** It is the one exception: everything else
  degrades quietly, but a person who typed their НКД code and got no match would otherwise never
  learn that the field they cared most about had been discarded. The picker searches the 1000-row
  classification by name over HTMX so that the code does not have to be known at all.

---

## 3. Stage 1 — hard filter

Two steps, deliberately.

**1a. SQL on indexed columns only.** Five predicates, all backed by indexes from `schema.sql`:
published-and-open, deadline in the future, entity type overlap, NACE prefix overlap, region overlap.
This cuts the registry to at most a couple of hundred rows in a few milliseconds.

```sql
SELECT c.* FROM call c
WHERE c.is_published
  AND c.status = 'open'
  AND (c.deadline_at IS NULL OR c.deadline_at > now())
  AND (c.allowed_entity_types = '{}' OR c.allowed_entity_types && ARRAY[:entity_type]::entity_type[])
  AND (c.allowed_nace_prefixes = '{}' OR c.allowed_nace_prefixes && :nace_prefixes)
  AND (c.allowed_regions       = '{}' OR c.allowed_regions       && ARRAY[:region_code, :municipality])
```

An empty array means "no restriction" — national calls open to everyone. That convention keeps the
filter a single `&&` test instead of a nullable special case.

**1b. A rule interpreter in Python over the survivors.** Every remaining `hard_structured` criterion
is evaluated in application code, not in generated SQL.

```
evaluate_hard(profile, call) -> (passed: bool, outcomes: list):
    outcomes = []
    for crit in call.criteria where crit.kind == 'hard_structured':
        actual = getattr(profile, crit.field)          # whitelisted field names only
        if actual is None:
            outcomes.append(Outcome(crit, NEEDS_VERIFICATION, 'rule',
                                    reason='profile does not answer this'))
            continue                                    # missing data NEVER excludes
        ok = OPERATORS[crit.operator](actual, crit.value_json)
        outcomes.append(Outcome(crit, ELIGIBLE if ok else NOT_ELIGIBLE, 'rule',
                                reason=explain(crit, actual)))
    passed = not any(o.verdict == NOT_ELIGIBLE for o in outcomes)
    return passed, outcomes
```

**Why an interpreter and not dynamic SQL.** Generating a SQL predicate per stored criterion is the
clever-not-boring trap: it is hard to debug, hard to unit-test, and one malformed extracted criterion
becomes a query error instead of a handled case. Over ≤200 candidate rows with ~10 criteria each,
2,000 interpreted comparisons cost under a millisecond. `OPERATORS` is a fixed dictionary of nine
functions and `crit.field` is checked against a whitelist, so a bad extraction can never reach
`getattr` with something arbitrary.

**Missing data never excludes.** If the profile does not answer a criterion, the outcome is
`needs_verification`, not `not_eligible`. Wrongly excluding a company is a silent failure the user
never sees and never disputes — which makes it worse, not better, than a false positive you catch in
review.

---

## 4. Stage 2 — score and rank

Every component returns a value in `[0,1]` **and a human-readable reason string**. The reason strings
are not decoration: they are what the free shortlist prints under each result, and what makes a
disputed ranking explainable a year later.

| Component | Weight | Definition |
|---|---:|---|
| `sector_fit` | 0.30 | NACE hierarchy distance: exact code 1.0, same class 0.85, same group 0.7, same division 0.5, same section 0.3, otherwise 0.0 |
| `size_fit` | 0.20 | Applicant's investment size against the call's `grant_min`/`grant_max` band. Inside band 1.0; degrades linearly to 0 at 2× outside |
| `timeline_fit` | 0.15 | Days to deadline vs stated project timeline. Under 14 days heavily penalised — an undeliverable deadline is not a match |
| `cofinancing_fit` | 0.15 | Applicant's stated co-financing capacity vs the call's required share. Below requirement → 0.2, not 0 (it is fixable, not disqualifying) |
| `soft_criteria` | 0.10 | Sum of matched `soft_scored` criteria (regional priority, woman-owned, youth, export) normalised by their total weight |
| `semantic_fit` | 0.10 | Cosine similarity between the project description embedding and the call summary embedding |

```
score(profile, call) -> (value, breakdown):
    parts = {}
    for name, fn in COMPONENTS:
        v, reason = fn(profile, call)
        parts[name] = {'value': v, 'weight': WEIGHTS[name], 'reason': reason}
    value = sum(p['value'] * p['weight'] for p in parts.values())
    return value, parts
```

**Weights live in `config/weights/<version>.yaml`, never in code**, and the version used is recorded
on every `match_run`. Changing weights is therefore a reviewable diff whose effect the evaluation
harness measures before it ships.

**Where the embedding comes from (open for P2 s27).** The embedding model runs locally and needs
~1.9 GB while loaded (`app/retrieval/embedder.py`), so it cannot live in the gunicorn workers that
serve stages 0–2. Call summary embeddings can be computed at ingestion; the project description
needs either a small second model in the web process, or the embedding moved to the worker with
`semantic_fit` filled in asynchronously. Decide when building stage 2, with the < 5 s budget measured.

**`semantic_fit` is capped at 0.10 deliberately.** It is the only component that is not fully
explainable, and it must never be able to move a call from rank 8 to rank 1 on its own. Embedding
similarity is a tiebreaker here, not a decision procedure.

**Deferred:** past-awardee similarity. The brief lists it, but no awardee data exists yet. Add it
only once a source actually publishes award lists — a scoring component with no data is a weight of
zero with extra code.

---

## 5. Stage 3 — verification pass

Top 5 results only. For each call, for each criterion the rules could not settle:

```
verify(profile, call, criterion) -> outcome:
    query  = criterion.label_mk + ' ' + criterion.source_quote
    chunks = hybrid_retrieve(call, query, k=6)      # app/retrieval/search.py
             # pgvector cosine on chunk.embedding  UNION  pg_trgm on chunk.text
             # reciprocal-rank-fused; trigram exists because Postgres has no
             # Macedonian FTS dictionary and codes/dates need exact matching.
             # Trigram votes only at word_similarity >= 0.6: below that it is
             # noise that outvotes the vectors on paraphrased questions (P1 s12).
             # An incomplete retrieval (unembedded or unindexed documents)
             # is a failed retrieval: needs_verification.

    payload = {
        'criterion':  criterion.label_mk,
        'passages':   [{'id': c.id, 'text': c.text} for c in chunks],
        'applicant':  pseudonymise(profile),   # size band, NACE, region, age band,
                                               # investment band. NO name, EMBS/EDB,
                                               # address, phone or email. Ever.
    }
    result = llm_gateway.call(task='verify', schema=VerificationResult, payload=payload)

    if result is INVALID after one retry:
        return queue_for_review(criterion, reason='schema validation failed')
    if result.quote not found verbatim in the cited chunk:
        return queue_for_review(criterion, reason='citation not verifiable')
    if result.confidence < 0.7:
        return Outcome(criterion, NEEDS_VERIFICATION, 'model', evidence=result.evidence)
    return Outcome(criterion, clamp(result.verdict), 'model', evidence=result.evidence)
```

`VerificationResult` (Pydantic, strict):

```
criterion_id : uuid
verdict      : 'satisfied' | 'not_satisfied' | 'unclear'   # NOT the user-facing verdict enum
confidence   : float 0..1
quote        : str          # must appear verbatim in the cited chunk
chunk_id     : int
reasoning_mk : str
```

Three defences worth naming explicitly:

1. **The model's vocabulary is not the user's.** It returns `satisfied` / `not_satisfied` /
   `unclear`. `clamp()` maps those into the user-facing taxonomy, and `not_satisfied` from a
   `narrative_verify` criterion maps to **`needs_verification`, never `not_eligible`**. The model is
   structurally incapable of excluding an applicant.
2. **The quote must be found verbatim in the chunk it cites.** A plain string search, run in code.
   This catches paraphrase-as-quotation, which is the failure mode that would otherwise put an
   invented citation in front of a paying customer.
3. **The applicant is pseudonymised at the gateway boundary**, enforced by a unit test that asserts
   no PII pattern appears in an outgoing payload (`risks.md` R5).

---

## 6. Stage 4 — the review gate, and the flywheel

Every paid report is approved by a human before delivery (brief §6.4). The admin screen shows, per
criterion: the model's verdict and confidence, the quoted passage **highlighted in place inside the
stored snapshot**, and Approve / Edit / Reject.

The part that matters more than the quality control: **every rejection or edit is written back as an
evaluation case automatically.** `review_queue_item.corrected_payload` holds the diff, and a nightly
job turns resolved items into fixtures under `evals/cases/from_review/`. The review gate is therefore
not a cost you are trying to eliminate — it is the mechanism that builds the test suite you have no
other way to obtain. That reframing is what makes months of manual review worth doing.

Before delivery, two automatic checks run on the composed prose:

- **Banned-phrase lint**: `гарантирано` / "guaranteed", "approved", "you will receive" and their
  Macedonian and Albanian equivalents. A hit blocks delivery (brief §3.4).
- **Citation completeness**: every eligibility statement carries a resolvable
  `(snapshot_id, char_start, char_end)`. No citation, no claim — enforced in code, not in review.

---

## 7. Confidence taxonomy

| Verdict | Condition | Who can produce it |
|---|---|---|
| **`not_eligible`** | At least one `hard_structured` criterion evaluated false on real data | **Rules only.** Never the model |
| **`eligible`** | All hard criteria passed, all narrative criteria verified with a valid citation, no attestations outstanding | Rules + verified model output |
| **`likely_eligible`** | All hard criteria passed, narrative criteria verified, but ≥1 `applicant_attest` outstanding | Rules + model |
| **`needs_verification`** | Anything else: a criterion unresolved, confidence below threshold, citation unverifiable, or profile data missing | Default |

**The governing rule: absence of evidence downgrades, never upgrades.** Every uncertainty path in
the code above terminates in `needs_verification`. There is no path from missing data to `eligible`
and no path from a model output to `not_eligible`.

In practice `eligible` will be rare before the applicant attests, and that is correct. A product that
frequently says "you are eligible" is a product that is about to be wrong in public.

---

## 8. Evaluation harness

### Layout

```
evals/
  profiles/       p001_skopje_it_micro.yaml       applicant fixtures
  fixtures/       fitr_2026_03/snapshot.txt       frozen snapshots + extracted criteria
  cases/          expected verdicts per (profile × call), with a human reason
  cases/from_review/                              auto-generated from reviewer corrections
  cassettes/      recorded model responses for stage 3
```

### Three tiers

| Tier | Covers | Runs | Speed |
|---|---|---|---|
| **A — deterministic** | Stages 0–2 against frozen fixtures. No network, no model | Every commit, in CI | Seconds |
| **B — recorded** | Stage 3 against cassettes. Tests prompt, schema, citation verification, clamping | Every commit | Seconds |
| **C — live** | Stage 3 against the real model, same cases | Weekly, and before any prompt or model change | Minutes, costs money |

Tier C exists because the model provider can change behaviour under you without warning. Tier A is
the one that runs constantly, which is why it is built to need neither network nor tokens.

### Metrics and the deploy gate

| Metric | Threshold |
|---|---|
| **False `eligible`** — expected `not_eligible`, produced `eligible` or `likely_eligible` | **Zero. Blocks deploy, no exceptions** |
| **False `not_eligible`** — expected eligible, excluded | ≤ 2% and never a regression |
| Citation validity — every quote found verbatim | 100%, blocks deploy |
| Rank quality — is the correct call in the top 5 | ≥ 90%, warns |
| Median stage 1–2 latency | < 3 s, warns at 3 s, blocks at 5 s |

The asymmetry is deliberate. A false `eligible` costs a customer real money on an application they
could never win, and it is the reputational failure this business does not survive. A false
`not_eligible` costs one missed opportunity. They are not equally bad and the gate should not treat
them as if they were.

### Seeding the suite, given no past cases

You answered that you have no archive of past client cases but can judge one quickly. So:

1. Pick 4 real calls with different shapes — FITR, an employment measure, an EU call, an IPARD
   measure.
2. I generate 10 applicant profiles engineered to sit on the boundaries: one clearly eligible, one
   clearly not, and several deliberately ambiguous per call.
3. **You spend one session marking the expected verdict and a one-line reason for each.** That
   session produces roughly 40 cases and is the single highest-value evening in P2.
4. The suite then grows on its own from reviewer corrections (§6). Real cases displace synthetic ones
   as they arrive.

The harness is written **before** stage 2 scoring, not after. Weights tuned without a measurement
harness are tuned by vibes, and you will not be able to tell whether your third adjustment helped.
