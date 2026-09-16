# Grant & Subsidy Matching Platform

A company or individual enters a short profile; the platform returns the funding programmes they can
realistically apply for, explains why with citations to the official text, and sells preparation of
the application documents. North Macedonia first, international programmes alongside.

- **What it is and why:** [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md)
- **How it is built:** [`docs/`](docs/README.md) — architecture, schema, sources, matching, roadmap,
  risks, open decisions
- **Rules that must not be broken:** [`CLAUDE.md`](CLAUDE.md)

Status: **P1 session 16** — container stack, schema, backups, source reconnaissance, LLM gateway,
snapshot store, fetcher base class, the normaliser (HTML, DOCX, PDF, OCR), call extraction with
citations located in code, the AV and EU Funding & Tenders fetchers end to end, chunking, local
embeddings and hybrid retrieval, source health alerts through healthchecks.io, and the admin review
queue where a human approves, edits or rejects every extracted call before it is published, with
manual entry of a call by URL (`/admin`, development only until operator sign-in is decided). See [`docs/roadmap.md`](docs/roadmap.md).

**Demo stage (16.09.2026):** the whole journey can be tried at `/demo` on invented calls, with no
database: profile, cited shortlist, report, order and proforma invoice, human review in an admin
queue, document package draft and monitoring alerts. The stage-1 rule interpreter
(`app/matching/hard_filter.py`), the verdict taxonomy and the banned-phrase lint are real code; the
rest is simulated. `/demo/vodic` lists, feature by feature, what is real and which session makes the
rest real. `/demo` is never registered in production.

```bash
uv run flask --app "app:create_app()" run   # then open http://127.0.0.1:5000/demo/vodic
```

## Running it locally

Requires [uv](https://docs.astral.sh/uv/). It installs Python 3.12 itself; no other setup.

```bash
uv sync                 # create .venv and install dependencies
uv run flask run        # http://127.0.0.1:5000
curl localhost:5000/healthz
```

```bash
uv run pytest           # tests (database-backed ones skip if no database is up)
uv run ruff check .     # lint
uv run ruff format .    # format
```

## Developing with live reload

```bash
./run.py              # start, open the browser, follow logs; Ctrl+C stops
./run.py --detach     # leave it running;  ./run.py stop  to stop
./run.py --build      # after changing dependencies or the Dockerfile
```

`run.py` is a thin wrapper around

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

This bind-mounts `app/` into the container and runs the Flask development server.
Editing Python restarts the server automatically. No rebuild, no restart command.

Open pages also refresh themselves: with `GRANTS_LIVE_RELOAD=true` (set by the overlay)
every HTML page polls `/__dev/reload` once a second and reloads when a template or
static file changes or the server restarts. See `app/web/devreload.py`. The setting
is refused in production.

In GitHub Codespaces, port 8080 is forwarded and can be shared:

```bash
gh codespace ports visibility 8080:public -c "$CODESPACE_NAME"
echo "https://$CODESPACE_NAME-8080.app.github.dev"
```

The overlay runs `flask run --reload --no-debugger`. The debugger is off deliberately:
it offers an interactive Python console to anyone who can reach the port, and a
Codespaces port can be made public.

Plain `docker compose up -d` (no overlay) runs gunicorn against code baked into the
image — that is what the VPS runs, and it needs a rebuild to pick up changes.

## Database

```bash
uv run alembic upgrade head                          # apply migrations
uv run alembic revision --autogenerate -m "message"  # after changing models
uv run alembic check                                 # models and database agree?
./ops/dump-schema.sh                                 # regenerate docs/schema.sql
```

The SQLAlchemy models in [`app/models/`](app/models/) and the migrations in
[`migrations/`](migrations/) are the source of truth. [`docs/schema.sql`](docs/schema.sql) is
generated and must not be hand-edited; the reasoning behind the model is in
[`docs/data-model.md`](docs/data-model.md).

Postgres is published on `127.0.0.1` only, so `psql` and `alembic` reach it from the machine itself
and nothing reaches it from the network.

## Running the full stack

```bash
cp .env.example .env      # then set GRANTS_SECRET_KEY and POSTGRES_PASSWORD
docker compose up -d
curl localhost:8080/healthz    # liveness: is this process up
curl localhost:8080/readyz     # readiness: can it reach Postgres and Redis
```

Five services: `caddy` (TLS and reverse proxy), `web` (gunicorn), `worker` (RQ), `postgres`
(pgvector), `redis`. Postgres extensions are created on first volume initialisation by
[`ops/initdb/01-extensions.sql`](ops/initdb/01-extensions.sql).

In production, set `CADDY_SITE_ADDRESS` to the real hostname and Caddy obtains a certificate
automatically; Cloudflare in front must then be **Full (Strict)**.

### If containers cannot reach each other (GitHub Codespaces and similar)

In some nested-Docker environments the kernel has both iptables backends active. Docker writes its
rules to the nft table, while the legacy table still carries `-P FORWARD DROP` with ACCEPT rules only
for the default `docker0` bridge — so traffic on this project's bridge is dropped: services time out
talking to each other, and the crawler cannot resolve any hostname (every source then fails closed as
"robots.txt unreachable"). `./run.py` adds these rules for you; by hand:

```bash
sudo iptables-legacy -I FORWARD 1 -i grants-br -o grants-br -j ACCEPT
sudo iptables-legacy -I FORWARD 1 -i grants-br ! -o grants-br -j ACCEPT
sudo iptables-legacy -I FORWARD 1 -o grants-br -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
```

This is a quirk of such sandboxes, not a requirement of the stack. A normal Docker install on the
VPS needs nothing. The bridge is named `grants-br` in `docker-compose.yml` precisely so rules like
this — and the firewall rules on the VPS — can reference it by a stable name.

## Ingestion

```bash
flask ingest sync-sources                 # config/sources.yaml → source_feed
flask ingest due                          # what cron runs: every active source not run in 20 h
flask ingest run <slug>                   # crawl one source; new calls → unpublished + review queue
flask ingest snapshot <slug> <url>        # fetch one URL and store it, for checks
flask ingest normalise                    # stored snapshots → text for citations (OCR if needed)
flask ingest extract --snapshot-id N      # one call's documents → CallExtraction (needs ANTHROPIC_API_KEY)
flask ingest fetch-model                  # once per machine: the embedding model, ~2.2 GB, into GRANTS_MODEL_DIR
flask ingest index                        # chunk new documents and embed chunks (also runs after run/due)
```

In the dev stack, prefix with `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web`.
Every request carries `grantbot/0.1 (+contact URL)`, obeys robots.txt and waits 5 s per host.

`run` and `due` fetch, normalise, extract and write each call the fetcher found. A call is written
unpublished, with cited unapproved criteria and one review item; anything the pipeline cannot vouch
for (unreadable document, invalid model output, a quote not found verbatim) becomes a review item
instead of a call. Extraction needs `ANTHROPIC_API_KEY`; without it, changed calls are reported as
errors and retried on the next run.

After the sources, `run` and `due` chunk every newly normalised document and embed the chunks with a
local model (`app/retrieval/`). Without `flask ingest fetch-model` first, that step fails loudly and
the command exits non-zero; chunks are kept and embedded on the next run. The retrieval acceptance
test (`tests/test_retrieval_paraphrase.py`) skips until the model is present.

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
  cli.py         operator commands (flask ingest ...)
  ai/            LLM gateway and identity scrubber -- the only path to a model
  ingestion/     polite HTTP, robots.txt, snapshot store, fetcher base class
  retrieval/     chunking, local embeddings, hybrid vector + trigram search
  models/        SQLAlchemy models (the schema's source of truth)
  web/           blueprints
config/          models.yaml (task routing, embedding model), sources.yaml (ingestion sources)
prompts/         versioned prompt files
tests/
docs/            design documents (see docs/README.md)
```

The full intended structure, and the three boundaries that matter, are in
[`docs/repo-skeleton.md`](docs/repo-skeleton.md).
