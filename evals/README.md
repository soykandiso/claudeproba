# The evaluation harness

The measurement the matching engine is changed against. `docs/matching.md` §8 is the design;
this file is how it is run and how it grows.

```
PYTHONPATH=. uv run python evals/run.py              # the gate: exit 0 passed, 1 failed
PYTHONPATH=. uv run python evals/run.py --worksheet  # write the blank case files
```

**It exits 1 today and that is the intended state.** There are no expected verdicts yet, and an
empty suite proves nothing. Roadmap P2 s26 — one evening with `evals/cases/` open — is what turns
it green, and P2 s27 must not tune a single scoring weight before then: weights tuned without a
measurement are tuned by vibes, and the third adjustment cannot be told from the first.

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

## The three tiers

| Tier | Covers | State |
|---|---|---|
| **A — deterministic** | stages 0–2 over the frozen calls. No network, no model, no tokens | built (P2 s25) |
| **B — recorded** | stage 3 against cassettes: prompt, schema, citation check, clamping | P2 s29 |
| **C — live** | the same cases against the real model, weekly and before any prompt change | P2 s36 |

## What tier A checks without a single expected verdict

Four properties hold for every profile and every call, and they run on every commit from today:

1. **Every quote is verbatim** at the offsets it cites — no citation, no claim, checked in code.
2. **Stage 1a is a superset filter**: a call the SQL threw away is one the interpreter would have
   called `not_eligible` anyway. This is the error the product cannot show you — a call that never
   appears has no reason beside it.
3. **Only a rule excluded anyone** — no `not_eligible` from a model or an attestation.
4. **A call whose documents are knowingly incomplete never rose above `needs_verification`**,
   however well its extracted criteria went.

## Filling in a case (P2 s26)

`run.py --worksheet` writes one file per call with a blank row per profile, the call's conditions
and the applicant's answers in the comments, and **deliberately not** what the system says — a
number already on the page is the fastest way to stop reading the call. Write one of
`eligible`, `likely_eligible`, `needs_verification`, `not_eligible`, `not_shown` and one sentence
of why:

```yaml
  - profile: p02_bitola_bakery_small
    expect: likely_eligible
    reason: Преработувачка дејност, постара од 12 месеци, мала — остануваат само изјавите.
```

`not_shown` means the call should not be in the shortlist at all. Half a file is fine: a blank
`expect` is counted, not an error, and the gate reports how many are still open.

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
