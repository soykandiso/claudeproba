"""Document packages (roadmap P5): templates per programme, filled as drafts for the applicant.

`engine.py` fills one template (s56). Templates live in `app/documents/templates/<programme>/`
as Word files under version control; `flask documents check` lints every one of them.
"""

from pathlib import Path

import click
from flask.cli import AppGroup

TEMPLATES = Path(__file__).resolve().parent / "templates"

cli = AppGroup("documents", help="Document templates (P5).")


@cli.command("check")
@click.argument("paths", nargs=-1, type=click.Path(exists=True, dir_okay=False))
def check_command(paths):
    """Lint templates (default: every .docx under app/documents/templates/)."""
    from app.documents import engine

    files = [Path(p) for p in paths] or sorted(TEMPLATES.rglob("*.docx"))
    failed = 0
    for path in files:
        problems = engine.check(path.read_bytes())
        for problem in problems:
            click.echo(f"{path}: {problem}")
        failed += bool(problems)
    click.echo(f"{len(files) - failed} of {len(files)} templates can be filled")
    if failed:
        raise SystemExit(1)
