# Document templates

One folder per programme, one Word file per document and version:
`<programme-slug>/<document-slug>/<version>.docx` (the first sets are P5 s58–65, `docs/decisions.md` D3).

- Every field is written `{{r key }}` — with the `r` — and every key is one of
  `config/document_fields.yaml`. No `{% … %}` logic.
- Money, exact counts, people, declarations and signatures are `source: applicant` fields: the
  engine never fills them and prints «[Пополнува барателот: …]» instead (brief §8).
- Beside each `.docx`, a manifest of the same name, `<version>.yaml`:

  ```yaml
  title_mk: Барање за финансиска поддршка
  attachments:                # keys of config/document_attachments.yaml
    - key: tekovna_sostojba
      note_mk: Не постара од шест месеци.   # the call's own condition, if it has one
    - key: ujp_potvrda
  ```
- `flask documents check` lints every template here; it must print nothing but the count.
