# Grant & Subsidy Matching Platform

A company or individual enters a short profile; the platform returns the funding programmes they can
realistically apply for, explains why with citations to the official text, and sells preparation of
the application documents. North Macedonia first, international programmes alongside.

- **What it is and why:** [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md)
- **How it is built:** [`docs/`](docs/README.md) — architecture, schema, sources, matching, roadmap,
  risks, open decisions
- **Rules that must not be broken:** [`CLAUDE.md`](CLAUDE.md)

Status: **P0.5 session 1** — application skeleton. No ingestion, no matching, no UI yet.
See [`docs/roadmap.md`](docs/roadmap.md).

## Running it locally

Requires [uv](https://docs.astral.sh/uv/). It installs Python 3.12 itself; no other setup.

```bash
uv sync                 # create .venv and install dependencies
uv run flask run        # http://127.0.0.1:5000
curl localhost:5000/healthz
```

```bash
uv run pytest           # tests
uv run ruff check .     # lint
uv run ruff format .    # format
```

## Configuration

Every setting is read from the environment with the `GRANTS_` prefix, or from a local `.env` file.
Copy [`.env.example`](.env.example) to `.env` to start. Settings are validated at boot, so a typo
stops the process immediately instead of surfacing as a confusing failure later.

`.env` is gitignored and must never be committed. There are no secrets in code.

## Layout

```
app/
  __init__.py    application factory
  config.py      env-driven settings, validated at boot
  web/           blueprints
tests/
docs/            design documents (see docs/README.md)
```

The full intended structure, and the three boundaries that matter, are in
[`docs/repo-skeleton.md`](docs/repo-skeleton.md).
