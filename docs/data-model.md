# Data model

The source of truth is the SQLAlchemy models in [`app/models/`](../app/models/) and the Alembic
migrations in [`migrations/`](../migrations/). [`schema.sql`](schema.sql) is generated from the live
database and is never hand-edited — regenerate it with `ops/dump-schema.sh`.

This document holds the reasoning that a generated file cannot: why the model is shaped this way.

## Answering the challenge in brief §4

### `Programme` and `Call` stay separate

**For.** Criteria, document templates and institutional knowledge are stable at programme level and
change slowly, so re-extracting them per call burns tokens and invites drift. The SEO archive wants
durable programme pages that accumulate authority while individual calls close. The monitoring
subscription is naturally "tell me when this programme reopens". Document templates map to
programmes, not to calls.

**Against.** Some sources publish genuine one-offs, and forcing a parent row creates junk.

**Resolution.** Every `call` has a `programme_id` (not null), and a one-off gets an auto-created
programme with `is_singleton = true`. Criteria live on the **call** — authoritative and cited — but
may be seeded from the programme as defaults that extraction confirms or overrides.

### Criteria that are genuinely unstructurable

`eligibility_criterion.kind` decides who evaluates a criterion and whether it may exclude an
applicant. **Only `hard_structured` can produce `not_eligible`.**

| kind | evaluated by | can exclude? |
|---|---|---|
| `hard_structured` | deterministic predicate over profile fields | **yes — the only kind that can** |
| `soft_scored` | deterministic weight, affects rank only | no |
| `narrative_verify` | model against a retrieved passage, with a citation | no — caps at `needs_verification` |
| `applicant_attest` | becomes an intake question or a report checklist item | no |
| `documentary` | a required document, becomes a checklist row | no |

The honest answer to "unstructurable" is `applicant_attest`: turn it into a question for the human
rather than a guess by the machine. "The applicant must not be in financial difficulty" is not a
field we can ever populate reliably, and pretending otherwise is how a false `eligible` reaches a
paying customer.

### `Applicant` is split into `account` and `applicant_profile`

`account` is who they are — identity, email, language, consent. `applicant_profile` is what they told
us, versioned, with `superseded_at`. A profile edited after a report was purchased must not
retroactively change the inputs that report was computed from. Without this split, reproducibility is
impossible and any dispute with a customer is unresolvable.

### Evidence cites a snapshot, never a live URL

`evidence` records `(snapshot_id, char_start, char_end)`. Source websites change; a citation that
points at a live page stops being verifiable the moment it does. Citation offsets index into
`raw_snapshot.normalised_text`, which is why that column is stored in the database while the raw
bytes live in object storage.

### Reproducibility

`match_run` records `ruleset_version` and `weights_version`. A report delivered in March must be
regenerable byte-for-byte in November, from stored inputs, after the source site has been redesigned
twice.

## Other decisions worth knowing

**Native PostgreSQL enums**, not check constraints or lookup tables. The value set is small, stable
and readable in `psql`, and the database rejects a typo at write time. `app/models/base.py` provides
`pg_enum()`, which stores member *values* (`micro`) rather than Python member names (`MICRO`) —
without it, every hand-written query in `docs/` would break.

**Raw bytes are not in the database.** `raw_snapshot` holds a hash, a URL, a status and a storage
key. Nightly `pg_dump` stays small and restores stay fast.

**Empty array means "no restriction".** `call.allowed_entity_types`, `allowed_nace_prefixes` and
`allowed_regions` use `'{}'` for national or unrestricted calls, which keeps the stage-1 filter a
single `&&` overlap test rather than a nullable special case.

**`call.eligibility_gap` is a fetcher's confession** (added 22.09.2026, P2 s24). Nullable text: when
set, it says in Macedonian that the documents fetched for this call are knowingly not all of its
conditions — an EU topic whose eligibility lives in a call document on another host
(`sources.md` §6.6). It is not a flag because the sentence is shown to the reviewer and to the
customer; a boolean would have to be translated back into a reason somewhere. `app/matching/stage1.py`
treats a call carrying it as never `eligible` and never `likely_eligible`, which is invariant 3
expressed as data rather than as a rule someone has to remember.

**Two check constraints carry the accuracy contract**, so it is enforced by the database rather than
by discipline:

- `ck_eligibility_criterion_has_citation` — an approved criterion must have a `snapshot_id` and a
  `source_quote`. No citation, no claim.
- `ck_eligibility_criterion_structured_has_predicate` — a `hard_structured` criterion must have a
  `field` and an `operator`, because otherwise it could never be evaluated.

Both are covered by tests in `tests/test_models_integration.py`.
