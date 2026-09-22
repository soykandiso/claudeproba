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

**First deploy, and after changing `embedding.model` in `config/models.yaml`:**

```bash
docker compose run --rm web flask ingest fetch-model   # ~2.2 GB into the models volume
docker compose exec -T web flask ingest index          # embeds whatever is waiting
```

The `models` volume is not backed up: it is a public download and can be fetched again.

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
| Alert email from the health check | §4, "A source alert" |
| Alert email from the ingest check (no ping) | §4, "The ingest heartbeat went silent" |
| No new calls for days | `flask ingest health` — the source is probably blocking or has changed layout |
| `index FAILED: ModelNotDownloaded` in the ingest log | The `models` volume is empty or was recreated: `docker compose run --rm web flask ingest fetch-model` |
| Ingest run killed, `Killed` or exit 137 | Out of memory while embedding (~1.9 GB peak). `free -m`; stop what else is large, run `flask ingest index` again — it resumes |
| Backup heartbeat silent | `/var/log/grants-backup.log`. The heartbeat only fires on success, so silence means failure |
| Disk filling | `docker system prune` for old images; check `backups/` pruning is working |

Containers cannot reach each other on a nested-Docker host: see the troubleshooting
note in [`README.md`](../README.md). Not a concern on the VPS.

---

## 4. Source alerts

A silently dead scraper is the failure that kills this business quietly (`docs/risks.md` R1).
Alerts leave the box through **healthchecks.io** (EU: Hetzner, Germany), which emails. Nothing in
the ping says anything about a customer: source slugs, dates, error messages.

### Setup — once, on the VPS

1. On healthchecks.io create two checks, and set email (and, if you like, a phone app) as their
   integration:
   - **grants-ingest**: period **4 hours**, grace **3 hours**. Pinged at the end of every
     `flask ingest due`, whatever happened to the sources. Silence means cron, Docker or the box
     is dead.
   - **grants-health**: period **1 day**, grace **2 hours**. Told once a day by
     `flask ingest health` whether every active source is fine.
2. Put their ping URLs in `.env` as `GRANTS_HEARTBEAT_INGEST_URL` and
   `GRANTS_HEARTBEAT_HEALTH_URL`, then `docker compose up -d` so the containers see them.
   In production `flask ingest health` refuses to run without the health URL.
3. Install the cron file (it runs `health` at 06:30 UTC).
4. **Drill — not done until it has actually arrived:**
   `docker compose exec web flask ingest health --drill` sends a failure marked DRILL. Confirm the
   email (or phone notification) arrives, then `docker compose exec web flask ingest health` to
   clear it. Repeat the drill after changing email address or phone.

### What the health check judges

`flask ingest health` prints the same report the email carries. Each active source is:

| State | Meaning | Threshold |
|---|---|---|
| `FAILING` | Its runs fail — fetch (blocked, moved, changed shape) or processing (model key, provider) — and none has succeeded | 30 hours, about six retries |
| `NOT_RUNNING` | No run started — cron is not reaching it, or it is active in `config/sources.yaml` without a fetcher | 30 hours |
| `QUIET` | Runs succeed but no new call has appeared | the source's `staleness_sla_days` |
| `ok` | Possibly with "last run failed … alerts at …": one bad night is a note, not an alert | |

healthchecks.io emails when the check changes state. If a second source breaks while the check is
already failing, the command briefly marks it up and fails it again, so the new problem gets its
own email; "(new)" marks it in the report.

### A source alert

1. `docker compose exec web flask ingest health` for the current picture.
2. **FAILING**, error mentions HTTP, timeout, robots.txt: open the source's site in a browser.
   Down for everyone → wait; it clears itself. Blocked (403, timeouts only from the VPS) → see
   `docs/sources.md` §6.1 for how FITR was handled; the fallback is `access_method: manual`.
   Changed shape (the fetcher raises `ValueError`, or normalising sends everything to review) →
   capture a new fixture, fix the fetcher, run its tests, deploy, then
   `flask ingest run <slug>`.
3. **FAILING**, error starts "processing failed": the source is fine and our side is not — model
   key, provider outage, spend ceiling. `/var/log/grants-ingest.log` has the whole message.
4. **NOT_RUNNING**: `crontab`/`/etc/cron.d/grants` installed? `docker compose ps`? Does
   `flask ingest due` print "active in config/sources.yaml but has no fetcher"?
5. **QUIET**: look at the source's own listing. Nothing new published (seasonal: `docs/sources.md`
   §6.4) → fine; raise `staleness_sla_days` if this will recur every year. New calls there but not
   here → the listing parses but no longer lists them: treat as a changed shape.
6. Once fixed, `flask ingest health` again; the check goes back up and emails that too.

### The ingest heartbeat went silent

The box, Docker or cron is not running `flask ingest due` at all. `docker compose ps`,
`systemctl status cron`, `tail /var/log/grants-ingest.log`, disk space (`df -h`). When it runs
again, the next ping clears the check.

---

## 5. The review queue

`/admin/` lists what waits for a decision, previously published calls first. Nothing reaches a
customer until it is approved here. Not available in production until operator sign-in is decided
(`docs/decisions.md` D11).

**A call to publish** ("Повик за објава"):

1. Read each condition's quote in its context. The highlighted words are exactly what the stored
   snapshot says at the recorded offsets.
2. Wrong kind, wrong rule, weak label: "Измени го условот". The edit is checked by the same schema
   extraction uses, and the quote must be found verbatim in the call's documents again, or nothing is
   saved. Copy quotes from one line.
3. A condition that is not a condition: "Отстрани го условот".
4. Title or deadline wrong (compare with "Што вели листата на изворот"): "Измени наслов или рок".
5. "Прифати и објави". It is refused, with the reasons listed, if any quote no longer matches its
   snapshot, if a customer-facing text has a banned phrase, or if a newer item exists for the same call.
6. Not a funding call after all: close it with a reason.

**Entering a call by hand** ("Рачен внес"): paste the call's URLs, the page or document with the
call text first, attachments after, up to five; name the institution as customers should see it.
The entry is queued for the worker and answers in the queue within a minute or two: a call to
approve as above, or a "Рачен внес" item saying the URLs could not be fetched (wrong address,
robots.txt refuses), could not be processed (enter them again once the cause is fixed), or are
already known (it links the existing item). If nothing appears, the worker is not running:
`docker compose ps`, `docker compose logs worker`. After changing code, `docker compose restart
worker`: RQ does not reload. From a shell, `flask ingest manual <url>... --institution "…"` does
the same synchronously.

**Anything else** (the model says it is not a call, quotes not found, invalid model output, an
unreadable document) has nothing to publish. Read why, and close it with a reason. The same document
is not sent to the model again until it changes at the source; if the model was wrong, the fix is a
prompt change (a new version file and an evaluation run), not a retry.

**„Текстот е прочитан со постара верзија"** on an item means what it says: that document's text was
written by a normaliser older than the OCR repairs of 21.09.2026, and normalised text is never
rewritten. The quote you are reading can be verbatim against our text and still not be what the
paper says — a rate may have lost its `%` (`sources.md` §6.10) and a non-Macedonian passage may be
noise (§6.11). It does not block approval, because most quotes out of such a document are fine and
there is no re-normalisation path; **open the original document and compare before you approve.**

To see every document in this state and what still cites it:

```
docker compose exec web flask ingest stale-text
```

It changes nothing. It exits non-zero if a *published* call cites one, which is the case to fix
first. The fix is to delete the snapshot and let the next run fetch and read it again — that moves
every offset citing it, so it is its own deliberate job, not something to do on a weeknight between
approvals.

Every edit and every reason is kept on the item (`corrected_payload`, `reviewer_note`); P2 s34 turns
them into evaluation cases.

---

## 6. If you are unavailable for a while

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
