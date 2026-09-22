# Tier B cassettes: recorded answers for the verification pass (P2 s29)

One file per frozen call. For each criterion stage 3 reads (`narrative_verify`, and
`applicant_attest`, which it may only lower), a `default` answer and, where the
applicant's shape settles it, one answer per profile. `evals/run.py --tier b` replays
them through the real `app/matching/verify.py`: the gateway validates them, the quote is
searched for in the passages the tier B retriever returned, and the verdict is clamped.

They are **hand-written**, like `tests/cassettes/extract_call/`: what a careful model
should answer given only the shape and the passages. What tier B measures is the code
and the prompt's contract, not a model — that is tier C (P2 s36). A cassette whose
quote is not in any passage it was shown is reported by the harness, not silently
accepted: fix the cassette, or the retriever.

`passage` is not recorded. The cassette provider finds the passage holding the quote in
the request it was sent, so a change in passage order does not break every file.
