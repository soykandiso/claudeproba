#!/usr/bin/env bash
# Restore a backup, and verify it actually restored.
#
#   ./ops/restore.sh                      # newest backup -> scratch db, then verify
#   ./ops/restore.sh path/to/file.dump.age
#   ./ops/restore.sh --into grants --i-mean-it   # overwrite the live database
#
# The default target is a scratch database, never the live one. This script is
# read at 2am by someone who has just lost data; the dangerous option is the one
# that has to be typed out in full.
set -euo pipefail

cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

: "${POSTGRES_USER:=grants}"
: "${POSTGRES_DB:=grants}"
: "${BACKUP_DIR:=./backups}"
: "${BACKUP_AGE_IDENTITY:?set BACKUP_AGE_IDENTITY to the age private key file}"

target_db="restore_drill"
force_production=false
backup_file=""

while [ $# -gt 0 ]; do
  case "$1" in
    --into) target_db="$2"; shift 2 ;;
    --i-mean-it) force_production=true; shift ;;
    *) backup_file="$1"; shift ;;
  esac
done

if [ "$target_db" = "$POSTGRES_DB" ] && [ "$force_production" != true ]; then
  echo "Refusing to overwrite the live database '$POSTGRES_DB'." >&2
  echo "If that is genuinely what you want, add --i-mean-it." >&2
  exit 1
fi

if [ -z "$backup_file" ]; then
  backup_file=$(find "$BACKUP_DIR/daily" -maxdepth 1 -name '*.dump.age' | sort | tail -1)
  [ -n "$backup_file" ] || { echo "No backups found in $BACKUP_DIR/daily" >&2; exit 1; }
fi

echo "restoring : $backup_file"
echo "into      : $target_db"
[ ! -f "$BACKUP_AGE_IDENTITY" ] && { echo "Missing key file: $BACKUP_AGE_IDENTITY" >&2; exit 1; }

docker compose exec -T postgres psql -U "$POSTGRES_USER" -d postgres -q \
  -c "DROP DATABASE IF EXISTS \"$target_db\";" -c "CREATE DATABASE \"$target_db\";"

# Decrypt on the way in; the plaintext dump never lands on disk.
age --decrypt --identity "$BACKUP_AGE_IDENTITY" "$backup_file" \
  | docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" -d "$target_db" --no-owner --no-privileges

echo
echo "--- verification ---"
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$target_db" -Atc "
  select 'tables:     '||count(*) from pg_tables where schemaname='public'
  union all select 'indexes:    '||count(*) from pg_indexes where schemaname='public' and indexname like 'ix_%'
  union all select 'extensions: '||count(*) from pg_extension where extname in ('vector','pg_trgm','citext','pgcrypto')
  union all select 'migration:  '||coalesce(max(version_num),'NONE') from alembic_version;"

# The check that matters: does the restored schema match the live one? A restore
# that runs without error but produces a different schema is the failure mode
# that stays hidden until you need it.
live=$(mktemp); restored=$(mktemp)
trap 'rm -f "$live" "$restored"' EXIT
docker compose exec -T postgres pg_dump --schema-only --no-owner --no-privileges --no-comments \
  -U "$POSTGRES_USER" "$POSTGRES_DB" | grep -vE '^\\(un)?restrict ' > "$live"
docker compose exec -T postgres pg_dump --schema-only --no-owner --no-privileges --no-comments \
  -U "$POSTGRES_USER" "$target_db" | grep -vE '^\\(un)?restrict ' > "$restored"

if diff -q "$live" "$restored" >/dev/null; then
  echo "schema:     identical to $POSTGRES_DB"
else
  echo "schema:     DIFFERS from $POSTGRES_DB"
  diff "$live" "$restored" | head -20
  exit 1
fi
echo
echo "Restore drill passed. Drop the scratch database when finished:"
echo "  docker compose exec -T postgres psql -U $POSTGRES_USER -d postgres -c 'DROP DATABASE \"$target_db\";'"
