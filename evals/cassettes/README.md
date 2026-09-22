Recorded model replies for tier B (P2 s29): the verification pass run against a fixed reply instead
of the provider, so the prompt, the schema, the verbatim-quote check and the verdict clamping are
tested on every commit without a token. Empty until s29. Hand-written extraction cassettes for the
ingestion path live in `tests/cassettes/extract_call/` and are a different thing.
