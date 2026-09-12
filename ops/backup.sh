#!/usr/bin/env bash
# Nightly database backup: dump, encrypt, store off-site, prune, report.
#
# Encryption is asymmetric on purpose. The server holds only the age PUBLIC key,
# so it can write backups it cannot read. Someone who compromises the VPS gets
# the live database -- which they already had -- but not the backup history.
# The private key lives somewhere else entirely; see docs/runbook.md.
#
# Run from cron:
#   15 3 * * *  cd /srv/grants && ./ops/backup.sh >> /var/log/grants-backup.log 2>&1
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

: "${POSTGRES_USER:=grants}"
: "${POSTGRES_DB:=grants}"
: "${BACKUP_DIR:=./backups}"
: "${BACKUP_KEEP_DAILY:=30}"
: "${BACKUP_KEEP_MONTHLY:=6}"
: "${BACKUP_AGE_RECIPIENT:?set BACKUP_AGE_RECIPIENT in .env (the age public key)}"
: "${BACKUP_REMOTE:=}"      # optional rclone target, e.g. hetzner:grants-backups
: "${HEARTBEAT_URL:=}"      # optional healthchecks.io ping

# A dump smaller than this is a silent failure, not a small database. Even an
# empty schema is tens of kilobytes.
MIN_DUMP_BYTES=10000

stamp=$(date -u +%Y-%m-%dT%H%M%SZ)
name="grants-${stamp}.dump.age"
mkdir -p "$BACKUP_DIR/daily" "$BACKUP_DIR/monthly"
target="$BACKUP_DIR/daily/$name"

echo "[$(date -u +%FT%TZ)] backup starting"

# Dump and encrypt in one pass: the plaintext never touches disk.
docker compose exec -T postgres pg_dump -Fc -U "$POSTGRES_USER" "$POSTGRES_DB" \
  | age --encrypt --recipient "$BACKUP_AGE_RECIPIENT" --output "$target"

size=$(stat -c%s "$target")
if [ "$size" -lt "$MIN_DUMP_BYTES" ]; then
  rm -f "$target"
  echo "FAILED: dump was only ${size} bytes, which means the dump did not work" >&2
  exit 1
fi
echo "  wrote $target (${size} bytes)"

# Keep the first backup of each month as well, so a problem noticed in August is
# still recoverable from June.
if [ "$(date -u +%d)" = "01" ]; then
  cp "$target" "$BACKUP_DIR/monthly/$name"
  echo "  kept a monthly copy"
fi

if [ -n "$BACKUP_REMOTE" ]; then
  rclone copy "$BACKUP_DIR/daily/$name" "$BACKUP_REMOTE/daily/" --quiet
  [ -f "$BACKUP_DIR/monthly/$name" ] && rclone copy "$BACKUP_DIR/monthly/$name" "$BACKUP_REMOTE/monthly/" --quiet
  echo "  uploaded to $BACKUP_REMOTE"
else
  echo "  WARNING: BACKUP_REMOTE is unset, so this backup exists only on this machine."
  echo "           A backup on the same box as the database is not a backup."
fi

prune() {
  local dir=$1 keep=$2
  # ls -1 sorts by name, and the name is an ISO-8601 UTC timestamp, so name order
  # is time order.
  local count
  count=$(find "$dir" -maxdepth 1 -name '*.dump.age' | wc -l)
  if [ "$count" -gt "$keep" ]; then
    find "$dir" -maxdepth 1 -name '*.dump.age' | sort | head -n "$((count - keep))" \
      | while read -r old; do rm -f "$old"; echo "  pruned $(basename "$old")"; done
  fi
}
prune "$BACKUP_DIR/daily" "$BACKUP_KEEP_DAILY"
prune "$BACKUP_DIR/monthly" "$BACKUP_KEEP_MONTHLY"

# Only on success: a heartbeat that fires regardless tells you nothing.
if [ -n "$HEARTBEAT_URL" ]; then
  curl -fsS -m 10 --retry 3 "$HEARTBEAT_URL" >/dev/null && echo "  heartbeat sent"
fi

echo "[$(date -u +%FT%TZ)] backup complete"
