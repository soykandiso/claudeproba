# How the platform works, and how to pick it up anywhere

Written 14.10.2026, after P4 (money) was built. For the owner, and for a Claude session that
starts from this repository with no memory of the earlier ones: on this Windows machine, in
claude.ai's browser sessions, or anywhere else. `docs/handoff.md` has the session-by-session
detail. This page is the map.

---

## 1. What it does, in one paragraph

A North Macedonian company describes itself (or uploads its Тековна состојба from the Central
Registry and fills in the rest) and gets, free, a shortlist of open grant and subsidy calls it
can realistically apply for. Every eligibility statement quotes the call's own text, with the
source and the date it was read. For 8.900 МКД (4.900 for the first ten orders) it can order a
**detailed report**: the first five open calls on its list (or all, if fewer) verified condition
by condition, reviewed by a person before it is sent. Payment is by bank transfer against a
proforma. Document packages (P5) and a monitoring subscription (P6) come later.

---

## 2. The customer's path

| Step | Page | What happens |
|---|---|---|
| 1 | `/` | The landing page: what it is, what it is not, the prices |
| 2 | `/profil/` | The intake: legal form, municipality, founding year, size, activity (NACE), amount sought. Or, on the same form, upload the Central Registry PDF and the answers fill themselves (D13) |
| 3 | `/povici/` | The free shortlist: open calls ranked, each with its verdict and quoted conditions; `/povici/izvor/…` shows a quote inside the stored document |
| 4 | `/najava` | Sign-in by an e-mail link. There are no passwords anywhere |
| 5 | `/naracka/` | Order a report: price, the profile it is for, **how many calls it will cover**, and the buyer's name, address, ЕДБ and ЕМБС for the invoice. The proforma (ПФ-2026-0001…) arrives by e-mail as a PDF |
| 6 | (bank) | The buyer pays by transfer, quoting the proforma number |
| 7 | e-mail | «Уплатата е примена»: a person reviews the report, which arrives within **five working days** |
| 8 | e-mail + `/naracka/<id>` | The report and the invoice (Ф-2026-0001…) as PDFs, also downloadable from the order page |
| 5b | `/naracka/paket/<call>` | From a call on the shortlist: a **document package**, 2.900 МКД: the institution's own forms filled with the company's details, the applicant's fields marked, and the checklist; reviewed by a person, delivered as Word files and a ZIP |
| — | `/smetka` | The account: profile versions, orders, data export, deletion |
| — | `/arhiva/`, `/ceni`, `/uslovi`, `/privatnost` | The public archive of calls, prices, terms and privacy policy |

## 3. The operator's path (you)

All under `/admin` (not switched on in production until the operator can sign in, D11):

| Screen | When | What you do |
|---|---|---|
| `/admin/` (Преглед) | After each ingestion | **No call reaches a customer until you approve it here.** Each new or changed call shows its conditions with quotes found in the stored document. Approve, edit a condition, or reject |
| `/admin/rachen-vnes` | When you hear of a call no source fetched | Paste its URLs; it goes through the same path and lands in Преглед |
| `/admin/uplati` (Уплати) | A transfer arrived | Paste the bank statement line, then «Означи како платена». The buyer is told and the analysis starts (runbook §9) |
| `/admin/izveshtaj/<id>` | A paid report's draft is ready | Read it against the quoted documents, edit the wording if needed, approve. **Approving sends it** with the invoice (runbook §10) |
| `/admin/paket/<id>` | A paid document package is made | Open every form in Word; check it is the institution's current form and the company's details are right; approve. **Approving sends it** (runbook §12) |

Commands you will use: `flask invoices audit` before handing invoices to the accountant (runbook
§11); `flask orders retry <id>` if an analysis failed; `flask ingest health` to see whether any
source has gone quiet.

---

## 4. How the calls are kept up to date

This is the part that makes or breaks the business (`docs/risks.md` R1: a scraper that dies
silently). In order:

**Sources.** `config/sources.yaml` lists them, each with a fetcher in `app/ingestion/sources/`:

| Source | Fetcher | How it reads | Active |
|---|---|---|---|
| EU Funding & Tenders portal | `eu_portal.py` | the portal's search API | yes |
| Агенција за вработување (AV) | `av.py` | its API | yes |
| Министерство за економија и труд | `economy.py` | HTML listings + PDFs | yes |
| Град Скопје (and municipalities) | `municipal.py` | an index of PDFs | yes |
| IPARD agency | `ipard.py` | HTML + PDFs | yes |
| ИНОВА (ФИТР's successor) | `inova.py` | its WordPress API (posts and the «Јавни повици» page) | yes |
| Рачен внес | `manual.py` | URLs you paste in the admin | always |

**Schedule.** On the server, cron runs `flask ingest due` **every 4 hours**
(`ops/cron.d/grants`). It runs each active source whose last run failed or is older than 20
hours, so a healthy source is read about once a day and a failed one is retried at the next
wake-up. The crawler is polite: a real User-Agent with contact details, `robots.txt` obeyed, one
request per 5 seconds per host.

**What a run does** (`app/ingestion/pipeline.py`), for every call a source lists:

1. **Fetch and store the raw document**, always, even if it cannot be parsed. Its SHA-256 is
   recorded.
2. **Unchanged bytes cost nothing.** If the hash matches what is stored, the call's «последна
   проверка» date (`last_verified_at`) moves forward and nothing else happens. No model call.
   This is the main cost control.
3. **Normalise**: the PDF or HTML becomes text, with OCR when a PDF has no text layer
   (many Macedonian ones do not).
4. **Extract**: the model reads the text and returns the call's conditions as structured data,
   **each with a verbatim quote**. The code then checks every quote really is in the text. A
   quote that is not found, output that fails the schema, or a document the model says is not a
   call goes to Преглед as a question, never onto the site.
5. **Write the call unpublished**, with one review item. **You approve it in `/admin/`**, and only
   then is it published and matched against profiles.
6. A **changed** document unpublishes its call until you approve it again; nothing a customer
   already saw is silently edited.
7. A call **no longer listed** by its source is closed. A call **past its deadline** stops
   appearing on shortlists automatically.
8. New documents are cut into chunks and embedded (a local model, ~2.2 GB, `flask ingest
   fetch-model` once per machine) for the paid report's verification.

**Health.** `flask ingest health` runs daily at 06:30 UTC and judges each source on its own:
failing, not running, or quiet for longer than its `staleness_sla_days` (`config/sources.yaml`).
It reports to healthchecks.io, which e-mails you (runbook §4). This works even if ingestion
itself is broken.

**Adding a source** touches only `app/ingestion/sources/` and `config/sources.yaml` (CLAUDE.md).
If it needs a real browser, it is not one of the first six (architecture §9.4).

### Where this stands today

- **Nothing runs on a schedule yet.** Cron runs on the VPS, and the VPS deploy waits for the
  domain (D2). Until then, ingestion runs only when someone types `flask ingest due`.
- **Extraction needs `ANTHROPIC_API_KEY`.** Without it, a changed call is reported as an error and
  retried next run. Unchanged calls are still re-verified.
- **On this Windows machine** the database holds the five frozen evaluation calls
  (`ops/dev/seed_shortlist.py`), not live ones, and there is no Redis, no cron and no key.
- **A cloud session starts with an empty database** (see §7). Your local dev data is not in git:
  only code, configuration and reference data are.

---

## 5. How a paid report is made

1. Payment confirmed (`/admin/uplati`). The order goes to the `analysis` queue (Redis + RQ).
   Every 10 minutes `flask orders dispatch` hands over any paid order that missed it.
2. The worker (`app/orders/fulfil.py` → `app/matching/deep.py`) re-runs the free shortlist for
   the order's profile and verifies the **first five open calls**, condition by condition, using
   the stored documents. **The model never decides that someone is not eligible**: only fixed
   rules over the profile's structured answers can (`app/matching/hard_filter.py`). A model's
   doubt always becomes «Потребна е проверка», never «Можете да аплицирате».
3. The report is composed (`app/reports/compose.py`) and queued for review; banned phrases
   («гарантирано», «ќе добиете»…) block it.
4. You approve it; `app/orders/deliver.py` prints it again with every check, issues the invoice,
   keeps both PDFs as sent, e-mails them, and marks the order delivered.

The five rules that must never break are in `CLAUDE.md`. Read them first, every session.

---

## 6. The code, by folder

| Folder | What lives there |
|---|---|
| `app/web/` | Flask blueprints: `intake/`, `shortlist/`, `account/`, `checkout/`, `admin/`, `archive/`, `public.py`, `legal.py`; Jinja templates in `templates/`, CSS in `static/` |
| `app/matching/` | Profile normalising, hard filter, ranking, the deep analysis, the тековна PDF reader |
| `app/ingestion/` | Fetchers, the polite HTTP client, snapshot store, normalisers (PDF/OCR/HTML), extraction, health |
| `app/ai/` | `gateway.py`, **the only door to a model**: scrubs identity data, validates every answer against a schema, caches by content hash |
| `app/reports/` | Report composition, lint, PDF rendering (WeasyPrint) |
| `app/orders/` | Orders, payment, proforma and invoice PDFs, numbering, reconciliation, fulfilment, delivery |
| `app/review/` | The decisions you make in the admin |
| `app/models/` | The database (SQLAlchemy). `migrations/` holds Alembic migrations; `docs/schema.sql` is generated |
| `config/` | Sources, prices, invoicing, legal entity, model routing, scoring weights: every business number |
| `data/` | Versioned reference data: NACE, municipalities, regions |
| `evals/` | The evaluation harness: frozen calls and profiles, recorded model answers. **A false «eligible» blocks a deploy** |
| `ops/` | Backup, cron, schema dump; `ops/dev/` seed and rehearsal scripts |
| `docs/` | Everything written down; see the table at the end of `CLAUDE.md` |

---

## 7. Continuing in a claude.ai browser session

A browser session clones `github.com/soykandiso/claudeproba` into a fresh Linux container. It
reads `CLAUDE.md` by itself. Nothing from this machine comes along except what is committed.

### First message to give it

> Read `CLAUDE.md`, `docs/how-it-works.md` and `docs/handoff.md` §1–§4, then continue the
> roadmap from where the handoff says. Commit, pull with rebase and push to `main` yourself after
> each session.

### Setting up the container (once per session; it does not persist)

From handoff §5, «In a claude.ai cloud container». Docker does not build there, so run natively:

```bash
sudo apt-get install -y postgresql-16-pgvector redis-server
sudo service postgresql start && sudo service redis-server start
sudo -u postgres psql -c "CREATE USER grants SUPERUSER PASSWORD 'grants';" -c "CREATE DATABASE grants OWNER grants;"
cp .env.example .env
uv sync
uv run alembic upgrade head
uv run flask --app "app:create_app()" ingest sync-sources
PYTHONPATH=. uv run python ops/dev/seed_shortlist.py
uv run flask --app "app:create_app()" run --port 8080
```

Optional seeds: `ops/dev/seed_review_queue.py` (items in Преглед), `ops/dev/seed_report.py` (a
report draft), `ops/dev/rehearse_order.py` (the whole paid path, kept in `var/proba/`).
Then `uv run pytest`. Tests that need a database skip when there is none, so a green run with
many skips means the database is not up.

**What may not work there:**
- **Government sites may be unreachable.** The container's network may not reach them, and a
  crawl will fail. That is the container, not the fetchers.
- **No model key** unless you add one to the environment. Without it, extraction and the deep
  analysis cannot run; everything else can.
- **No browser pane like this one.** Visual checks need headless Chromium (handoff §5 says
  where it is and to run it as `nobody`).

### Working agreements carried over from the sessions on this machine

These lived in Claude's local memory here, so they are written down for a fresh session:

- **Git:** commit, `git pull --rebase` and push `main` at the end of every session without
  asking. Commit only that session's own files. End each commit message with the
  `Co-Authored-By` line from the session's instructions.
- **Each «continue»** means: build the next roadmap session, test it, check it visually where
  there is UI (375 / 768 / 1440, light and dark, axe clean), update `docs/roadmap.md` and
  `docs/handoff.md`, commit and push, then report briefly.
- **Ask only for decisions that are really the owner's** (prices, promises to customers, legal
  wording, which programme first). Otherwise take the conservative default, record it in
  `docs/decisions.md`, and say so in the report.
- **Never commit personal data.** The real Тековна состојба sample has a person's name, ЕМБС and
  ЕДБ. It stays out of the repository.
- **Macedonian is the launch language** and customer-facing Macedonian goes through human review.
  Dates `dd.mm.yyyy`, money МКД / EUR.

---

## 8. What is waiting on you (the owner)

From `docs/handoff.md` §4, the ones that block launch:

| | What | Why it blocks |
|---|---|---|
| **D2** | The domain | Deploy, e-mail to customers, Search Console |
| **D4** | Your ЕДБ, bank account and bank; the accountant's look at the sample proforma and invoice (`flask invoices sample OUT [--final]`) | No real proforma can be issued; `flask invoices check` fails until then |
| — | A native reader for the public pages, a lawyer for the terms and privacy policy | Customer-facing text |
| **Forms** | **Decided (D3): all programmes**, in the order АВ, Economy, IPARD, ИНОВА. Each set needs the institution's **official blank application forms** (the owner's copies, or a current call's attachments) | P5 from session 58 |
| s55 | The real rehearsal: your own profile, a real transfer, the real server | Brief §14's proof that money flows |

Next by the roadmap: **P6, the monitoring subscription** (P5 is built: document packages at 2.900 МКД for the Employment Agency's and the Ministry of Economy's calls (built: the engine, the checklist, the Employment Agency's three forms, the Ministry of Economy's eight, the draft label; IPARD's set waits for its next call's forms).
