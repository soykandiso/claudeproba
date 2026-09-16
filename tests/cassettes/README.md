# Cassettes

Model replies replayed by tests instead of calling a provider.

## `extract_call/`

**Hand-written, not recorded.** Each file is the reply a correct extraction should give for one
fixture, written by a person reading the normalised text of that fixture. They test the schema and
the in-code citation check against real documents; they say nothing about how well a model extracts.

| File | Fixture |
|---|---|
| `economy-call-3.json` | `tests/fixtures/economy/call-3-javen-povik.docx` |
| `av-measure-819.json` | `tests/fixtures/av/measure-819-business-mk.json` (the `d` field) |
| `ipard-notice-03-2025.json` | `tests/fixtures/ipardpa/call-34-najava-03-2025.pdf` |
| `eu-digital-2026-skills-10-edtech.json` | `tests/fixtures/eu_portal/topic-digital-2026-skills-10-edtech.json`, as rendered by `EuPortalFetcher.unwrap` |

The roadmap asked for three FITR fixtures; FITR did not respond during reconnaissance
(`docs/sources.md` §6.1), so these three cover the shapes that exist instead: a DOCX call, an HTML
announcement, and a wrapped-line PDF advance notice with a Latin look-alike letter.

Recorded replies from a live run (`flask ingest extract`) belong next to these once an API key is
available, and should replace them as the regression baseline.
