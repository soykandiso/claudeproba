Cases generated from reviewer decisions by `flask review export-cases` (`app/review/cases.py`,
P2 s34): every extraction or report item a person rejected or edited in `/admin` becomes one file,
`<kind>-<item id>.yaml`, written once. Nothing in this directory is hand-written — the files beside
it, in `evals/cases/`, are. On the VPS they are written outside the checkout and pulled here to be
read and committed (`docs/runbook.md` §5).

`evals/run.py` loads them and checks their shape; it scores none. An extraction case is the model's
output, the documents it read (by URL and hash) and the reviewer's correction — tier C (s36)
re-asks the model. A report case is the draft, the reviewer's edits or reason, and the applicant as
bands and codes — it becomes a scored case when a person writes the expected verdict into
`evals/cases/`.
