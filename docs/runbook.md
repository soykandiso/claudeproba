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
docker compose run --rm web flask legal check       # no placeholder in the terms or the policy
docker compose run --rm web flask invoices check    # the seller's ЕДБ, account and bank on proformas
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
| Alert email from the health check | §4, "A source alert"; a `model spend` line: §14 |
| Alert email from the eval check | §14, "Tier C, weekly" |
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
   snapshot says at the recorded offsets. **If the document was scanned**, the page it was read off
   is rendered underneath the quote — that is the only thing that proves the paper says what the
   text says (`decisions.md` D9 rule 1). "Отвори ја сликата" opens it full size.
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

### What a rejection or an edit becomes

Every edit and every reason is kept on the item (`corrected_payload`, `reviewer_note`), and **the
night after, every rejected or edited item becomes one evaluation case** — `extraction-<id>.yaml` or
`report-<id>.yaml` (P2 s34, `app/review/cases.py`). Cron runs `flask review export-cases` at 02:45
UTC; it writes each case once and never again, so running it by hand any time is safe. An approval
without an edit writes nothing, and neither does an item rejected only because a newer one for the
same call was approved. **Write the reason as if for the evaluation, because that is where it goes**:
"вест, не повик" is a case; "не" is not.

What leaves the server is only what may: public documents by URL and hash, the applicant as the
bands and codes a model is shown (never the answers, the name or the profile id), and the note and
edited statements after the identity scrubber — with the customer's e-mail and profile label as
known names. Do not rely on the scrubber: **do not write a company's name into a note**.

**Once, on the VPS**: `sudo mkdir -p /srv/review-cases && sudo chown 10001 /srv/review-cases`, and
`GRANTS_REVIEW_CASES_HOST_DIR=/srv/review-cases` in `.env`. Outside the checkout on purpose: files
the VPS writes inside it would make the next `git pull` refuse to overwrite them.

**Weekly, on the laptop**, pull the new ones, read them, commit them:

```
rsync -a --ignore-existing <vps>:/srv/review-cases/ evals/cases/from_review/
git status evals/cases/from_review/     # read each new file before committing it
PYTHONPATH=. uv run python evals/run.py # the gate loads and checks them
```

The gate counts them and checks their shape; it scores none yet. An extraction case is re-asked of
the model by tier C (s36). A report case becomes a scored tier A case when you write the expected
verdict for a profile like it into `evals/cases/` — the report case says which verdict was wrong and
why, it does not say what the right one was.

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

---

## 7. A request about personal data

The privacy policy (`/privatnost`) promises an answer within a month. Most people do it
themselves on `/smetka` (download, delete). For a request by e-mail:

```bash
docker compose exec -T web flask accounts export person@example.mk > export.json   # access, portability
docker compose exec -T web flask accounts erase person@example.mk                   # erasure
```

`erase` anonymises rather than deletes: the address is replaced, profiles no order points at are
deleted, a profile behind an order loses its project description and stays (the tax law keeps the
order, and the report it bought must stay reproducible), subscriptions are cancelled, consent
records lose the IP address (`app/accounts.py`). Reply saying exactly that. A correction is the
person editing their profile; an objection or a restriction comes to you, and the answer is to
stop the processing they object to and write down what you did in `docs/decisions.md`.

The retention job (`flask accounts anonymise-stale`, monthly from `ops/cron.d/grants`) forgets
the profiles of accounts quiet for 24 months (D5). `--dry-run` lists them first.

---

## 8. How many people came, and from where

No analytics runs in the page (`decisions.md` D14). The numbers are in Caddy's access log:

```bash
docker compose logs --no-log-prefix caddy | goaccess - --log-format=CADDY -o /srv/report.html
```

Read it over the SSH tunnel, never publish it: it holds IP addresses. Caddy's log rotation keeps
30 days (the privacy policy's promise; configure it at P0.5 s4), so the report covers at most a
month. Useful questions: how many reach `/profil/` from `/`, how many `/povici/` follow, which
`/arhiva/` pages arrive from search engines (the referrer), how many `/tekovna` uploads fail.

**Search Console** (once the domain exists, D2): verify by DNS, submit `/sitemap.xml`.
`/robots.txt` in production allows the public pages and the archive and disallows the form,
the shortlist, the account, the admin and the demo (`PRIVATE` in `app/web/public.py`).

## 9. A payment arrived

1. Open `/admin/uplati`, paste the line from the bank statement, press «Најди профактура».
2. Check the amount against the statement and press «Означи … како платена». The amount must
   be the proforma's total to the denar; a partial or doubled payment is refused on purpose:
   settle it with the customer and the accountant, then mark it.

The customer gets an e-mail at once: the payment arrived, a person reviews the report, and it
comes within five working days of payment (`config/prices.yaml`, `delivery_working_days`). The
order goes to the analysis worker straight away. If the message says the worker did not answer,
do nothing: `flask orders dispatch` (cron, every ten minutes) hands it over.

**A failed analysis is not retried by itself**, because running it again costs model calls. Read
the failure (`docker compose exec web rq info`, then the failed job's traceback), fix the cause,
then:

```bash
docker compose exec web flask orders retry <order-id>
```

The draft lands in the review queue like any other report. The five-day promise runs from the
payment date, so a failure on day four is worth a short e-mail to the customer.

## 10. A report is ready for its buyer

Approving the report of a paid order (`/admin/izveshtaj/<id>`, the page says «Платена нарачка»
above the button) sends it at once: the checks run again, the invoice is issued, and the buyer
gets both PDFs by e-mail. The order becomes «Испорачана».

If it was not sent, the page says why and nothing was spent: no invoice number, no e-mail.
- **The e-mail failed**: fix the mail settings, then «Испрати го на купувачот» on the same page.
- **A call in the report closed since approval**: the report cannot go out as it is. Run the
  analysis again (`flask orders retry <order-id>`) and review the new draft; tell the buyer.

What the buyer received is kept in the snapshot store (`delivered/<order-id>/…`, backed up with
the snapshots) and on their order page, unchanged, for as long as the store is kept.

## 11. Invoice numbers and the year end

Numbers run `ПФ-<year>-0001`, `Ф-<year>-0001`… per kind and year, without gaps. The year is
Skopje's: an order at 00:30 on 1 January is numbered, dated and filed in the new year, even
though the server's clock still says 31 December. The database refuses an invoice whose
`fiscal_year` is not the year of its date.

Before sending the month's or the year's invoices to the accountant:

```bash
docker compose exec web flask invoices audit
```

It prints nothing but «every invoice series is whole» when all is well; otherwise each gap,
duplicate, odd format or wrong year on a line of its own. Do not «fix» a gap by renumbering:
show the line to the accountant.

**Changing a prefix** (`config/invoicing.yaml`) is done on 1 January, with the accountant, or not
at all. Changed in the middle of a year, numbering refuses to continue rather than start again
at 0001 under the new prefix.

## 12. A document package is ready for review

A paid package order is made by the worker and waits in `/admin/` under «Пакети што чекаат».
Open it (`/admin/paket/<id>`) and open **every document in Word**:

- the form is the institution's **current** one: each shows where it was taken from and when.
  If the institution has published a newer form, close the package with that reason, rebuild the
  template (`ops/dev/build_<programme>_templates.py`, after downloading the new form), and tell
  the buyer;
- the company's details are right (they come from the order and the profile);
- nothing of the applicant's (amounts, people, declarations, signatures) was filled.

**Approve** sends it at once: the forms and the checklist as Word files, the invoice, and the
order page then offers the whole package as a ZIP. If the e-mail fails, nothing is spent and
«Испрати го на купувачот» on the same page sends it again. **Close** needs a reason, sends
nothing and leaves the order in progress: settle it with the buyer (a refund is by hand).

Which calls are offered a package is `config/packages.yaml`; a call that fits two packages is
offered none, which `flask documents check` will not catch: read the shortlist after editing it.

## 13. Subscriptions and renewals

Ten days before a subscription's paid period ends, `flask orders renew` (cron) issues the next
period's proforma and mails it. It appears in `/admin/uplati` like any other; when the transfer
arrives, mark it paid: the period is extended from the old end, and the invoice goes out.

**Nothing is charged automatically**, and an unpaid renewal is never chased: the subscription
simply lapses on its end date and alerts stop. A renewal paid after the lapse starts a new period
from the payment date. A stale unpaid renewal proforma can be left; it is overdue in
`/admin/uplati` and harms nothing.

If the command reports renewals «not issued», the mail failed: nothing was issued, no number was
spent, and the next day's run tries again.

A subscriber who unsubscribes (the link in any alert or renewal e-mail, or the account page) stops
getting alerts at once and their subscription will not renew; nothing is refunded, and they can
resume from the account until the paid period ends. Every grant and withdrawal is in
`consent_record` with purpose `alerts`, for a data request (§7).

## 14. What the model costs, and the weekly tier C run

**The spend.** `/admin/troshoci` shows this month's model spend against the ceiling
(`GRANTS_MODEL_SPEND_CEILING_EUR`, 30 EUR, `docs/decisions.md` D8), by task, by delivered report
(its median is the marginal model cost of one report), and the last twelve months. The numbers
are the gateway's estimate at the list prices in `config/models.yaml`, converted at its
`eur_per_usd`; the provider's invoice is the authority. Update the prices when the provider
changes them, and the rate when it is visibly off.

### The model spend alert

`flask ingest health` (daily, §4) adds a line `model spend` to its report. Over the ceiling it
reads `OVER_CEILING` and the health check fails, so the alert arrives by the same e-mail as a
source alert. Nothing is stopped: the ceiling is an alarm.

1. `/admin/troshoci`: which task, and since when.
2. **Extraction** high: a source re-sending changed documents every run (a page whose bytes change
   on every fetch defeats the content hash). `docs/sources.md` for the source; the fix is in its
   fetcher, usually stripping what changes (`without_aspnet_state` is the precedent).
3. **Verification or composition** high: count the reports delivered this month; if it is just
   demand, raise the ceiling in `.env` (and D8). If not, look for repeated runs of one order.
4. A failed-request count well above zero: the provider is refusing or the schema is failing;
   `/var/log/grants-ingest.log` and the review queue.

### Tier C, weekly

Cron runs `docker compose --profile eval run --rm -T eval` on Mondays (07:00 UTC): stage 3 with the
real model over the frozen calls, for the sample of applicants in `evals/suite.yaml`
(`tier_c.profiles`), stopping at `tier_c.max_eur` (5 EUR). It runs in its own database,
`grants_eval`, with the checkout's `evals/` mounted read-only, and pings
`GRANTS_HEARTBEAT_EVAL_URL`. Its cost is **not** in `/admin/troshoci` (its rows are rolled back);
it is in its log and on the provider's invoice: about 4 runs × 5 EUR at most a month.

**Setup, once:**

1. On healthchecks.io a check **grants-eval**: period **7 days**, grace **1 day**; its URL in `.env`
   as `GRANTS_HEARTBEAT_EVAL_URL`. `ANTHROPIC_API_KEY` in `.env` too.
2. On a volume created before 21.10.2026 the database does not exist yet:
   `docker compose exec postgres createdb -U grants grants_eval` (a fresh volume gets it from
   `ops/initdb/02-eval-database.sql`).
3. Run it once by hand and read the report: `docker compose --profile eval run --rm eval`.

**When it fails** (`/var/log/grants-eval.log`, and the e-mail):

- `false eligible` or `false exclusion`: the model now answers a frozen case differently and the
  answer reached a verdict. **Do not deploy a prompt or routing change until it is green.** If
  nothing in this repository changed, the model behind the name did: read the disagreements, and
  pin `config/models.yaml` to a dated model if the provider offers one.
- `tier C stopped at its budget`: more requests than the sample used to need, or dearer ones.
  Read the per-applicant costs before raising `max_eur`.
- `the model and the cassettes disagree` is a warning: either the cassette (a person's answer, P2
  s29) or the model is wrong. Read each one against the call's text in `evals/fixtures/`.
- `went to review`: invalid output twice. A few is the gateway working; many is a schema or prompt
  problem.

Before a **prompt change** (a new version file), run every applicant, not the sample:
`docker compose --profile eval run --rm eval sh -c "alembic upgrade head && python evals/run.py --tier c --all --max-eur 20"`.
