# The evaluation harness

The measurement the matching engine is changed against. `docs/matching.md` §8 is the design;
this file is how it is run and how it grows.

```
PYTHONPATH=. uv run python evals/run.py              # the gate: exit 0 passed, 1 failed
PYTHONPATH=. uv run python evals/run.py --worksheet  # write the blank case files
PYTHONPATH=. uv run python evals/run.py --retrieval  # stage 3's retrieval, real embedder (~1 min)
```

**It passes since P2 s26 (22.09.2026)**, when the 41 expected verdicts were marked: 0 false
eligible, 0 false exclusion, 3 over-claimed (named in the report), 14 under-decided. A profile added
later (p11, the same evening) gets its rows from `--worksheet`, appended to each marked file. Before that it
exited 1 on purpose — an empty suite proves nothing — and P2 s27 still must not tune a weight
without reading this report first: weights tuned without a measurement are tuned by vibes, and the
third adjustment cannot be told from the first.

## What is in here

| Path | What it holds | Who writes it |
|---|---|---|
| `profiles/` | ten applicants, as intake answers, each sitting on a boundary | a session, by hand |
| `fixtures/` | five real calls, frozen: the document, the columns, the approved criteria | `ops/dev/freeze_eval_fixtures.py` |
| `cases/` | the expected verdict and a one-line reason per (profile × call) | **the user** |
| `cases/from_review/` | cases generated from reviewer corrections (P2 s34) | a nightly job |
| `cassettes/` | recorded model replies for tier B (P2 s29) | a session |
| `suite.yaml` | the clock and the deploy gate's thresholds | a session |
| `harness.py`, `run.py` | the machinery | a session |
| `tier_b.py`, `retrieval.py` | tier B's stand-ins; the retrieval measurement (P2 s30) | a session |

## The three tiers

| Tier | Covers | State |
|---|---|---|
| **A — deterministic** | stages 0–2 over the frozen calls. No network, no model, no tokens | built (P2 s25) |
| **B — recorded** | stage 3 against cassettes: prompt, schema, citation check, clamping. `run.py --tier b` | built (P2 s29) |
| **C — live** | the same cases against the real model, weekly and before any prompt change | P2 s36 |
| **Retrieval** | whether stage 3 is shown the right passages: each criterion's clause and each cassette's evidence, production path (gated, ≥ 90% in the top 6) and the unpinned search over all five documents pooled (reported). `run.py --retrieval` | built (P2 s30) |

## What tier A checks without a single expected verdict

Five properties hold for every profile and every call, and they run on every commit:

1. **Every quote is verbatim** at the offsets it cites — no citation, no claim, checked in code.
2. **Stage 1a is a superset filter**: a call the SQL threw away is one the interpreter would have
   called `not_eligible` anyway. This is the error the product cannot show you — a call that never
   appears has no reason beside it.
3. **Only a rule excluded anyone** — no `not_eligible` from a model or an attestation.
4. **A call whose documents are knowingly incomplete never rose above `needs_verification`**,
   however well its extracted criteria went.
5. **Stage 2 gave every ranked call a score in [0, 1] and a reason for every component**, and
   no call the rules exclude ranks above one the company may apply for (P2 s27).

**Tier B adds two**: every recorded answer passed stage 3's gates (a cassette whose quote is not
in the passage it was shown is reported, not believed), and every model quote is verbatim at its
offsets in the stored text. The cassettes are `cassettes/verify/`, hand-written, one per call; their
README says how.

Rank quality — "is the right call in the top five" — is printed as **not measurable**: with four
open calls every ordering passes it, and the cases record verdicts, not an expected order.

## Filling in a case (P2 s26)

`run.py --worksheet` writes one file per call with a blank row per profile, and everything needed to
decide in the comments: the call's conditions **in the call's own words**, quoted from the frozen
document, and each applicant's answers. What it deliberately leaves out is what the system says — a
number already on the page is the fastest way to stop reading the call. Nothing has to be opened;
the whole document is there if you want it. Write one of
`eligible`, `likely_eligible`, `needs_verification`, `not_eligible`, `not_shown` and one sentence
of why:

```yaml
  - profile: p02_bitola_bakery_small
    expect: likely_eligible
    reason: Преработувачка дејност, постара од 12 месеци, мала — остануваат само изјавите.
```

`not_shown` means the call should not be in the shortlist at all. Half a file is fine: a blank
`expect` is counted, not an error, and the gate reports how many are still open.

Two conventions the first 41 rows were written under (s26), so the next row means the same thing:

1. **The truth is what a careful expert would say from the applicant's answers and the call's
   text** — not what the system can produce today. An IT company is `not_eligible` for a
   manufacturing-only call even though only a model can read that condition; the harness reports
   the gap as under-decided and it blocks nothing.
2. **`not_shown` is for location only.** Every other exclusion is `not_eligible`, a call listed
   with its reason. For the gate the two are the same exclusion.

No row is `eligible`: every frozen call but the IPARD notice has an `applicant_attest` condition,
and an unconfirmed attestation caps a verdict at `likely_eligible`.

The suite grows from real review corrections after that (P2 s34). Synthetic cases are the seed,
not the crop.

## Changing a fixture

Fixtures are rebuilt, never hand-edited:

```
PYTHONPATH=. uv run python ops/dev/freeze_eval_fixtures.py
```

It reads the captured documents in `tests/fixtures/` and the extractions in
`tests/cassettes/extract_call/`, locates every quote with the same code the pipeline uses, and
writes `call.yaml` and `document.txt`. **Read the diff**: a moved offset or a changed quote is
exactly the drift the harness exists to notice, and a case whose call text changed underneath it
may no longer mean what its reason says.

## Why the gate is asymmetric

A false `eligible` costs a customer real money on an application they could never win: zero
tolerated, no exceptions. A false `not_eligible` costs one missed opportunity: ≤ 2%. And "the
system is less certain than the truth" is not a failure at all — it is the distance stage 2
scoring (s27) and the verification pass (s29) have to close, so it is reported as a number.
