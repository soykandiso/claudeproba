"""From an institution's form to a template and its manifest (roadmap P5 s58, s62).

One `FormSpec` per official form says where it came from and where each field goes; `build`
reads the downloaded form, checks it is the same file (by hash), places the fields with
`derive`, refuses the result unless `engine.check` passes, and writes
`app/documents/templates/<programme>/<document>/<version>.docx` with its `.yaml` manifest.
The spec lists are in `ops/dev/build_<programme>_templates.py`, one per institution.

The ways a field is placed, all of which keep the institution's own text:

- `cells`: into an empty answer cell beside a label (`derive.place`);
- `appended`: as a new line inside a one-cell row, after its label (`derive.append`);
- `lines`: into the blank line written just above a caption such as «(име и презиме)»
  (`derive.fill_line_above`);
- `signature_after`: a marker paragraph after the signature caption (`derive.mark_after`).
"""

import datetime as dt
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

import docx
import yaml

from app.documents import TEMPLATES, derive, engine


@dataclass
class FormSpec:
    programme: str  # the folder under app/documents/templates/
    slug: str  # the document's folder: «msp/barane», «ppr»
    title_mk: str
    source_url: str
    file: str  # as downloaded
    converted: str | None  # the .docx Word made of a .doc, if any
    version: str  # the form's own date
    sha256: str  # a prefix of the downloaded file's hash: the form the spec was written for
    retrieved: dt.date
    cells: list[tuple[str, str]] = field(default_factory=list)
    appended: list[tuple[str, str]] = field(default_factory=list)
    lines: list[tuple[str, str]] = field(default_factory=list)
    signature_after: str | None = None
    by_hand_mk: str | None = None
    package_note_mk: str | None = None
    attachments: list[dict] = field(default_factory=list)


class BuildRefused(ValueError):
    """The template cannot be made from this file as the spec describes."""


def build(spec: FormSpec, forms_dir: Path, root: Path = TEMPLATES) -> Path:
    served = (forms_dir / spec.file).read_bytes()
    digest = hashlib.sha256(served).hexdigest()
    if not digest.startswith(spec.sha256):
        raise BuildRefused(f"{spec.file}: not the form the spec was written for ({digest[:16]})")
    document = docx.Document(forms_dir / (spec.converted or spec.file))
    for label, key in spec.cells:
        derive.place(document, label, key)
    for label, key in spec.appended:
        derive.append(document, label, key)
    for caption, key in spec.lines:
        derive.fill_line_above(document, caption, key)
    if spec.signature_after:
        derive.mark_after(document, spec.signature_after, "signature_and_stamp")
    template = derive.to_bytes(document)
    problems = engine.check(template)
    if problems:
        raise BuildRefused(f"{spec.slug}: {problems}")

    out = root / spec.programme / spec.slug / f"{spec.version}.docx"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(template)
    manifest = {
        "title_mk": spec.title_mk,
        "source_url": spec.source_url,
        "source_sha256": digest,
        "retrieved": spec.retrieved.isoformat(),
        "fill_by_hand_mk": spec.by_hand_mk,
        "package_note_mk": spec.package_note_mk,
        "attachments": spec.attachments,
    }
    out.with_suffix(".yaml").write_text(
        yaml.safe_dump(manifest, allow_unicode=True, sort_keys=False, width=100), encoding="utf-8"
    )
    return out
