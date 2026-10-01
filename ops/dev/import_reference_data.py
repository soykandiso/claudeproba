"""Rebuild data/ from the official classifications (P2 session 22).

    uv run --with xlrd python ops/dev/import_reference_data.py

Two published archives from the State Statistical Office are the only inputs:

- **НКД Рев.2** — the national activity classification. Identical in structure to
  NACE Rev. 2, with four extra national subclasses under 69.10 and, on every
  section, a Macedonian section letter that is *not* the Latin one (section C,
  manufacturing, is written `В` in Macedonian). Only one of the four workbooks in
  the archive is in Cyrillic; the others are in a legacy transliteration font and
  are ignored.
- **НТЕС 2013 (corrected)** — territorial units. Level 3 is the eight planning
  regions, level 4 the eighty municipalities, level 5 settlements (not imported;
  nothing in matching is finer than a municipality).

The ten municipalities that make up the City of Skopje are read from the note at
the top of the НТЕС sheet rather than typed here, so the flag stays sourced.

`xlrd` is not a project dependency: it reads a 2003-era .xls once a decade, and
the image has no reason to carry it. Hence `--with` above.

The download is content-hashed and the run **fails** if either archive differs
from the hash in `data/reference.yaml`. That is the point: a reclassification
must be a deliberate diff, reviewed, not something that silently lands in a
customer's report. Pass `--accept-new-hashes` once you have looked at it.
"""

import argparse
import csv
import datetime as dt
import hashlib
import io
import re
import sys
import zipfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ingestion.http import PoliteClient, Request  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
MANIFEST = DATA / "reference.yaml"

UA = "grantbot/0.1 (+https://github.com/soykandiso; reference data import; contact via repository)"

NACE_URL = "https://www.stat.gov.mk/KlasifikaciiNomenklaturi/NKDRev2.zip"
NACE_MEMBER = "NKDRev2/NKD REV.2/NKD Rev.2_soMKpodrska_2019-09-05.xls"
NTES_URL = "https://www.stat.gov.mk/KlasifikaciiNomenklaturi/NTES_2013corr.zip"
NTES_MEMBER = "NTES2013corr.xls"

# What the classification must contain. NACE Rev. 2 is a published, fixed shape;
# if an import produces anything else it has misread the sheet, and writing the
# files would be worse than stopping.
EXPECTED_NACE = {1: 21, 2: 88, 3: 272, 4: 615, 5: 4}
EXPECTED_REGIONS = 8
EXPECTED_MUNICIPALITIES = 80
EXPECTED_SKOPJE = 10


def fetch(url: str) -> bytes:
    with PoliteClient(UA, min_interval_s=5.0, timeout_s=90.0) as client:
        return client.fetch(Request(url)).content


def member(archive: bytes, name: str) -> bytes:
    with zipfile.ZipFile(io.BytesIO(archive)) as zf:
        return zf.read(name)


def sheet(blob: bytes):
    import xlrd  # imported here so the file is readable without the dependency

    return xlrd.open_workbook(file_contents=blob).sheet_by_index(0)


def clean(value: object) -> str:
    """One trimmed line. The sheets are full of trailing spaces and hard spaces."""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def level_of(value: object) -> int | None:
    """The level column is sometimes a float and sometimes text ('02' is text)."""
    try:
        return int(float(clean(value)))
    except ValueError:
        return None


# ------------------------------------------------------------------ НКД Рев.2

# A section row carries both alphabets: "C/В" is Latin C, Macedonian В.
SECTION_ROW = re.compile(r"^([A-U])/(.)$")

# Two defects in the published workbook, both systematic, both repaired here and
# recorded in data/README.md. Faithfulness to a typo is not a virtue when the
# name goes in front of a customer and the code goes into a filter.
#
# 1. Fourteen division rows carry the code of their first group: division 10 is
#    typed "10.0". Left alone, "10" would not exist, so a call open to division
#    10 would match nobody. Every one of the fourteen is a division row (level 2)
#    whose groups are numbered separately, checked in tests/test_reference_data.py.
DIVISION_AS_GROUP = re.compile(r"^(\d{2})\.0$")
# 2. Latin "x" stands for Cyrillic "х" in 92 names ("xрана", "теxнологија") — the
#    fingerprint of a legacy transliteration font. It is the only Latin letter in
#    the whole file, so the substitution is unambiguous.
MANGLED_H = str.maketrans({"x": "х"})


def nace_rows(blob: bytes) -> list[dict]:
    s = sheet(blob)
    rows: list[dict] = []
    section = ""
    for r in range(s.nrows):
        level = level_of(s.cell_value(r, 1))
        code, name = clean(s.cell_value(r, 2)), clean(s.cell_value(r, 3))
        if level is None or not code or not name:
            continue
        name = name.translate(MANGLED_H)
        letter_mk = ""
        if level == 1:
            match = SECTION_ROW.match(code)
            if not match:
                raise SystemExit(f"row {r}: section code {code!r} is not 'X/Х'")
            code, letter_mk = match.group(1), match.group(2)
            section = code
            parent = ""
        elif level == 2:
            code = DIVISION_AS_GROUP.sub(r"\1", code)
            parent = section
        elif level == 3:
            parent = code[:2]
        elif level == 4:
            parent = code[:4]
        else:
            parent = code.split("/")[0]
        rows.append(
            {
                "code": code,
                "level": level,
                "parent": parent,
                "section": section,
                "letter_mk": letter_mk,
                "name_mk": name,
            }
        )
    return rows


# ------------------------------------------------------------------ НТЕС 2013

# The codes are typed in mixed alphabets in the source: МК001 (Cyrillic) beside
# MK00102 (Latin). One alphabet, or every lookup is a coin toss.
CYRILLIC_TO_LATIN = str.maketrans({"М": "M", "К": "K"})

# "... 10-те скопски општини ... (Скопје-Аеродром, Скопје-Бутел, ...)"
SKOPJE_NOTE = re.compile(r"Скопје-([^,)]+)")


def ntes_rows(blob: bytes) -> tuple[list[dict], list[dict]]:
    s = sheet(blob)
    skopje: set[str] = set()
    regions: list[dict] = []
    municipalities: list[dict] = []
    region = ""
    for r in range(s.nrows):
        first = clean(s.cell_value(r, 0))
        if "скопски општини" in first:
            skopje = {clean(n) for n in SKOPJE_NOTE.findall(first)}
        level = level_of(first)
        if level not in (3, 4):
            continue
        name_mk, name_en = clean(s.cell_value(r, 1)), clean(s.cell_value(r, 2))
        code = clean(s.cell_value(r, 3)).translate(CYRILLIC_TO_LATIN)
        if level == 3:
            region = code
            regions.append({"code": code, "name_mk": name_mk, "name_en": name_en})
        else:
            # The identification number is the office's own municipality code and
            # is how their other datasets refer to it. Floats in the sheet.
            raw = clean(s.cell_value(r, 4))
            dzs_id = f"{int(float(raw)):04d}" if raw else ""
            municipalities.append(
                {
                    "code": code,
                    "name_mk": name_mk,
                    "name_en": name_en,
                    "region_code": region,
                    "dzs_id": dzs_id,
                    "city_of_skopje": "true" if name_mk in skopje else "false",
                }
            )
    if not skopje:
        raise SystemExit("the note listing the City of Skopje municipalities is gone")
    return regions, municipalities


# ------------------------------------------------------------------ writing


def write_csv(path: Path, rows: list[dict], columns: list[str]) -> None:
    """Deterministic: same input, byte-identical file, so a diff means a change."""
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--accept-new-hashes", action="store_true")
    parser.add_argument("--version", default=dt.date.today().strftime("%Y-%m-%d.1"))
    args = parser.parse_args()

    known = yaml.safe_load(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    known_hashes = {k: v["sha256"] for k, v in (known.get("sources") or {}).items()}

    archives = {"nace": fetch(NACE_URL), "ntes": fetch(NTES_URL)}
    hashes = {k: hashlib.sha256(v).hexdigest() for k, v in archives.items()}
    changed = [k for k, v in hashes.items() if known_hashes.get(k, v) != v]
    if changed and not args.accept_new_hashes:
        for k in changed:
            print(f"{k}: upstream is now {hashes[k]}, manifest says {known_hashes[k]}")
        raise SystemExit("upstream changed; look at the diff, then --accept-new-hashes")

    nace = nace_rows(member(archives["nace"], NACE_MEMBER))
    regions, municipalities = ntes_rows(member(archives["ntes"], NTES_MEMBER))

    counts = {level: sum(1 for row in nace if row["level"] == level) for level in EXPECTED_NACE}
    if counts != EXPECTED_NACE:
        raise SystemExit(f"NACE levels {counts} != {EXPECTED_NACE}")
    if len(regions) != EXPECTED_REGIONS or len(municipalities) != EXPECTED_MUNICIPALITIES:
        raise SystemExit(f"{len(regions)} regions, {len(municipalities)} municipalities")
    in_skopje = sum(1 for m in municipalities if m["city_of_skopje"] == "true")
    if in_skopje != EXPECTED_SKOPJE:
        raise SystemExit(f"{in_skopje} municipalities in the City of Skopje, expected 10")

    DATA.mkdir(exist_ok=True)
    write_csv(
        DATA / "nace.csv", nace, ["code", "level", "parent", "section", "letter_mk", "name_mk"]
    )
    write_csv(DATA / "regions.csv", regions, ["code", "name_mk", "name_en"])
    write_csv(
        DATA / "municipalities.csv",
        municipalities,
        ["code", "name_mk", "name_en", "region_code", "dzs_id", "city_of_skopje"],
    )
    MANIFEST.write_text(
        "# Provenance of the files in data/. Written by ops/dev/import_reference_data.py;\n"
        "# the version is recorded on a match run so a delivered report stays reproducible.\n"
        + yaml.safe_dump(
            {
                "version": args.version,
                "retrieved": dt.date.today().strftime("%d.%m.%Y"),
                "sources": {
                    "nace": {"url": NACE_URL, "member": NACE_MEMBER, "sha256": hashes["nace"]},
                    "ntes": {"url": NTES_URL, "member": NTES_MEMBER, "sha256": hashes["ntes"]},
                },
                "counts": {
                    "nace": len(nace),
                    "regions": len(regions),
                    "municipalities": len(municipalities),
                },
            },
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    print(f"{len(nace)} NACE rows, {len(regions)} regions, {len(municipalities)} municipalities")


if __name__ == "__main__":
    main()
