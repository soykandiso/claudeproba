# Reference data

Activities, municipalities and planning regions, as **versioned files** rather than rows someone
edits in production (CLAUDE.md, `docs/matching.md` §2). A reclassification must show up in a diff,
be reviewed, and be deployed — because a report delivered last month has to stay explainable with
the data that produced it. `reference.yaml` carries the version that `app/matching/reference.py`
exposes and that a `match_run` will record from P2 s27.

**Do not edit these files by hand.** Rebuild them:

```bash
uv run --with xlrd python ops/dev/import_reference_data.py
```

The importer refuses to run if either upstream archive has changed since the hash in
`reference.yaml`; `--accept-new-hashes` is how you say you have looked at the diff.

| File | Rows | What it is |
|---|---:|---|
| `nace.csv` | 1000 | НКД Рев.2 — sections, divisions, groups, classes, and four national subclasses |
| `municipalities.csv` | 80 | НТЕС level 4, with its planning region and the ДЗС municipality number |
| `regions.csv` | 8 | НТЕС level 3 — the eight planning regions |
| `reference.yaml` | — | version, retrieval date, upstream URLs and SHA-256 of each archive |

## Provenance

Both archives are published by the **Државен завод за статистика** and were fetched through
`app/ingestion/http.py`, so robots.txt and the rate limit applied as they do to any source.

| Source | Archive | Member read | Retrieved |
|---|---|---|---|
| НКД Рев.2 | `stat.gov.mk/KlasifikaciiNomenklaturi/NKDRev2.zip` | `NKD Rev.2_soMKpodrska_2019-09-05.xls` | 22.09.2026 |
| НТЕС 2013 (исправена) | `stat.gov.mk/KlasifikaciiNomenklaturi/NTES_2013corr.zip` | `NTES2013corr.xls` | 22.09.2026 |

The NKD archive holds four workbooks. Only the one above is in Cyrillic; the others are in a legacy
transliteration font (`ZEMJODELSTVO, [UMARSTVO`) and are unusable without a font mapping nobody
should be writing. NTES level 5 is settlements — around 1,800 of them, and nothing in matching is
finer than a municipality, so they are not imported.

## What the import repairs, and why

Two defects in the published workbook, both systematic, both repaired in
`ops/dev/import_reference_data.py` and asserted in `tests/test_reference_data.py`:

1. **Fourteen division rows carry the code of their first group.** Division 10 is typed `10.0`,
   division 62 as `62.0`. Left alone, the code `10` would not exist in the classification, and a call
   open to division 10 — food manufacturing, one of the most commonly funded activities in the
   country — would have matched nobody. The affected divisions are
   10, 29, 30, 41, 45, 55, 56, 58, 59, 60, 61, 62, 66, 70.
2. **Latin `x` stands for Cyrillic `х` in 92 names** (`xрана`, `теxнологија`, `xартија`) — the
   fingerprint of the same legacy font. It is the only Latin letter anywhere in the file, so the
   substitution is unambiguous. Machine-mangled Macedonian in front of a customer is a product
   failure (CLAUDE.md), and these names are shown in the intake picker and in reports.

## Two things about this data worth knowing before using it

- **A Macedonian section letter is not the Latin one.** Section C (manufacturing) is written `В` in
  Macedonian — which is a perfectly good Latin `B` to a computer, and `B` is mining. Both letters are
  in `nace.csv`, and `reference.resolve_nace` accepts either and always answers with the Latin code.
  Nothing else in the codebase should be guessing at this.
- **Град Скопје is not the Skopje region.** The City of Skopje is the ten municipalities flagged
  `city_of_skopje` (the list comes from the note in the NTES sheet, not from anyone's memory); the
  Скопски planning region holds seventeen. A call from the city and a call for the region have
  different eligible populations, and `sources.yaml` has a fetcher for the former (P1 s19).

## Codes

`municipalities.csv` and `regions.csv` use the NTES code (`MK008`, `MK00814`) as the identifier, so a
municipality's region is a prefix of its own code and the hierarchy needs no join. `dzs_id` is the
statistical office's own municipality number, which is how their other datasets refer to it — keep it
for the day one of those is imported.
