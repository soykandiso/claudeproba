# Document templates

One folder per programme, one Word file per document and version:
`<programme-slug>/<document-slug>/<version>.docx` (the first sets are P5 s58–65, `docs/decisions.md` D3).

- Every field is written `{{r key }}` — with the `r` — and every key is one of
  `config/document_fields.yaml`. No `{% … %}` logic.
- Money, exact counts, people, declarations and signatures are `source: applicant` fields: the
  engine never fills them and prints «[Пополнува барателот: …]» instead (brief §8).
- `flask documents check` lints every template here; it must print nothing but the count.
