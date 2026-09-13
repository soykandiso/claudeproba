# Grant & Subsidy Matching Platform

A company or individual enters a short profile; the platform returns the funding programmes they can
realistically apply for, explains why with citations to the official text, and sells preparation of
the application documents. North Macedonia first, international programmes alongside.

- **What it is and why:** [`PROJECT_BRIEF.md`](PROJECT_BRIEF.md)
- **How it is built:** [`docs/`](docs/README.md) — architecture, schema, sources, matching, roadmap,
  risks, open decisions
- **Rules that must not be broken:** [`CLAUDE.md`](CLAUDE.md)

Status: **P1 session 8** — container stack, schema, backups, source reconnaissance, LLM gateway, and
the snapshot store and fetcher base class. No source fetchers, matching or UI yet. See
[`docs/roadmap.md`](docs/roadmap.md).

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
flask ingest run <slug>                   # crawl a source with its fetcher
flask ingest snapshot <slug> <url>        # fetch one URL and store it, for checks
```

In the dev stack, prefix with `docker compose -f docker-compose.yml -f docker-compose.dev.yml exec web`.
Every request carries `grantbot/0.1 (+contact URL)`, obeys robots.txt and waits 5 s per host.

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
  models/        SQLAlchemy models (the schema's source of truth)
  web/           blueprints
config/          models.yaml (task routing), sources.yaml (ingestion sources)
prompts/         versioned prompt files
tests/
docs/            design documents (see docs/README.md)
```

The full intended structure, and the three boundaries that matter, are in
[`docs/repo-skeleton.md`](docs/repo-skeleton.md).
