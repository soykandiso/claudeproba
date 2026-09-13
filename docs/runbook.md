# Runbook

Operational procedures, written to be followed by someone who is tired, or by
someone who is not the author. If a step here is wrong, fix it the same day —
this file is only useful if it is trusted.

> **Status:** the deploy section awaits the VPS (P0.5 session 4). Backups and
> restore are complete and have been rehearsed.

---

## 1. Backups

### What happens nightly

`ops/backup.sh`, at 03:15 UTC via `/etc/cron.d/grants`:

1. `pg_dump -Fc` piped straight into `age` — **the plaintext dump never touches disk**
2. Written to `backups/daily/grants-<ISO timestamp>.dump.age`
3. Rejected if smaller than 10 KB, because a tiny dump is a silent failure rather than a small database
4. Copied to `backups/monthly/` on the first of the month
5. Uploaded off-site with `rclone` if `BACKUP_REMOTE` is set
6. The snapshot volume (raw fetched documents) copied to `$BACKUP_REMOTE/snapshots/` — not
   encrypted, since they are public documents with no personal data, and never pruned, since every
   citation points back into them. Needs root to read the volume.
7. Pruned to 30 daily and 6 monthly
8. Heartbeat pinged **only on success**

### Encryption keys

Encryption is asymmetric, and this matters more than it looks.

- **`BACKUP_AGE_RECIPIENT`** — the public key. Lives on the server. It can encrypt
  and cannot decrypt.
- **`BACKUP_AGE_IDENTITY`** — the private key. **Never on the production server.**
  Keep it in a password manager and on a piece of paper somewhere physical.

So someone who compromises the VPS gets the live database — which they already
had by being on the box — but not the backup history. It also means that **losing
the private key means losing every backup**, permanently. Store it before you need it.

```bash
age-keygen -o backup-key.txt     # public key is printed and in the file header
```

### Restoring

```bash
./ops/restore.sh                          # newest backup into a scratch database, verified
./ops/restore.sh backups/daily/FILE.age   # a specific backup
./ops/restore.sh --into grants --i-mean-it   # overwrite the live database
```

The default target is a scratch database, never the live one. Overwriting
production needs `--i-mean-it` spelled out, because this script gets read by
someone who has just lost data and should not be able to make it worse with a
typo.

After restoring, the script checks that the restored schema is **identical** to
the live one and fails if it is not. A restore that runs without error but
produces a different schema is the failure mode that stays hidden until it matters.

### Restoring snapshots

The database rows (`raw_snapshot`) say which files should exist; the files come back from the
remote. Each file is named by its SHA-256, so a corrupted one is detected on read.

```bash
sudo rclone copy "$BACKUP_REMOTE/snapshots/" \
  "$(docker volume inspect --format '{{ .Mountpoint }}' grants_snapshots)/"
```

### The monthly drill — first Saturday, 15 minutes

An untested backup is not a backup. Put this in your calendar.

```bash
./ops/restore.sh                 # expect: schema identical, migration version present
docker compose exec -T postgres psql -U grants -d postgres -c 'DROP DATABASE "restore_drill";'
```

If it fails, that is the most important thing you will do that month.

---

## 2. Deploy

*(Awaiting the VPS — P0.5 session 4.)*

```bash
ssh <server>
cd /srv/grants
git pull
docker compose build
docker compose run --rm web alembic upgrade head    # migrations before the new code serves
docker compose up -d
curl -fsS https://<domain>/readyz                   # both dependencies must report ok
```

Migrations run before the new containers take traffic. If a migration fails, the
old containers are still serving and nothing is broken yet — fix forward, do not
restart into a half-migrated state.

---

## 3. When something is wrong

| Symptom | First thing to check |
|---|---|
| Site down | `docker compose ps` — which service is not running or not healthy |
| 502 from Caddy | `docker compose logs web` — usually a failed start after a bad deploy |
| `/readyz` says not ready | It names the failing dependency. `docker compose logs postgres` or `redis` |
| Jobs not processing | `docker compose logs worker`; is Redis healthy; is the queue name right |
| No new calls for days | `flask ingest health` — the source is probably blocking or has changed layout |
| Backup heartbeat silent | `/var/log/grants-backup.log`. The heartbeat only fires on success, so silence means failure |
| Disk filling | `docker system prune` for old images; check `backups/` pruning is working |

Containers cannot reach each other on a nested-Docker host: see the troubleshooting
note in [`README.md`](../README.md). Not a concern on the VPS.

---

## 4. If you are unavailable for a while

The bus-factor plan (`docs/risks.md` R7). Ingestion needs no human and continues
on its own. What must not happen is a customer paying and then waiting with no
explanation.

**Before a planned absence:** clear the review queue, and deliver every paid order.
Never leave a paid order unreviewed overnight before travelling.

**To pause commerce** *(arrives with P4)*: a single flag stops new paid orders and
shows an honest banner with a return date. The free shortlist and the public
archive keep running.

**If something breaks while you are away:** the site can be down for days without
losing data, as long as backups are running. Restoring is `./ops/restore.sh`.
Nothing in this system requires a human on a given day except the review queue.
