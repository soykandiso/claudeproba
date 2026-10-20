#!/usr/bin/env bash
# One command in a GitHub Codespace: make room on the disk, bring the code up to date, start
# the app, migrate the database. For the owner, who runs it from a Codespace some nights.
#
#   bash ops/dev/codespace_tonight.sh          # safe clean-up, then pull, build, start, migrate
#   bash ops/dev/codespace_tonight.sh --deep   # also remove every Docker image not in use
#
# What it removes, and what it never touches:
#   removes  Docker build cache, dangling images, stopped containers, uv/pip/npm caches,
#            apt's package cache, old journal logs, your own files in /tmp older than a day;
#            with --deep, every Docker image no running container uses (rebuilt, just slower)
#   NEVER    Docker volumes (the PostgreSQL data, Redis, the snapshots), the repository,
#            .env, the embedding model in models/
set -euo pipefail
cd "$(dirname "$0")/../.."

DEEP=0
[[ "${1:-}" == "--deep" ]] && DEEP=1
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.dev.yml)

free_gb() { df -BG --output=avail . | tail -1 | tr -dc '0-9'; }
show() { df -h / . 2>/dev/null | awk '!seen[$0]++'; }

echo "== Disk before"
show

echo "== Making room (Docker volumes are never touched)"
docker container prune -f >/dev/null || true
docker image prune -f >/dev/null || true
docker builder prune -af >/dev/null || true
if [[ $DEEP == 1 ]]; then
  echo "   --deep: removing Docker images no running container uses"
  "${COMPOSE[@]}" stop >/dev/null 2>&1 || true
  docker image prune -af >/dev/null || true
fi
command -v uv >/dev/null && uv cache prune >/dev/null 2>&1 || true
command -v pip >/dev/null && pip cache purge >/dev/null 2>&1 || true
command -v npm >/dev/null && npm cache clean --force >/dev/null 2>&1 || true
sudo -n apt-get clean >/dev/null 2>&1 || true
sudo -n journalctl --vacuum-size=50M >/dev/null 2>&1 || true
find /tmp -mindepth 1 -maxdepth 1 -user "$(id -u)" -mtime +1 -exec rm -rf {} + 2>/dev/null || true

echo "== Disk after"
show
echo "== Largest folders here and in your home (for a look, nothing is removed)"
du -xsh ./* ~/.cache ~/.local 2>/dev/null | sort -h | tail -8 || true

if [[ "$(free_gb)" -lt 4 ]]; then
  echo
  echo "!! Under 4 GB free. Try:  bash ops/dev/codespace_tonight.sh --deep"
  echo "!! If that is not enough: github.com > Codespaces > this codespace > ... > Change machine type"
  echo "!! (a larger machine has a larger disk; the code and the database volume are kept)."
  exit 1
fi

echo "== Bringing the code up to date"
git pull --rebase

echo "== Building and starting the stack (dependencies changed since last time)"
./run.py --build --detach

echo "== Migrating the database and syncing the sources"
"${COMPOSE[@]}" exec -T web alembic upgrade head
"${COMPOSE[@]}" exec -T web flask ingest sync-sources

echo
echo "Done. The app is running; ./run.py shows its address, ./run.py stop stops it."
