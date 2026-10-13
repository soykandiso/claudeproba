"""The whole paid path, end to end (roadmap P4 s55's dress rehearsal, `ops/dev/rehearse_order.py`).

Sign-in by link → order → proforma → a statement line marked paid → the analysis (recorded
model answers) → approval → the report and the invoice delivered → the series audited. On the
evaluation suite's clock, in a rolled-back transaction, through the real screens.
"""

import importlib.util
from pathlib import Path

from tests.test_shortlist import db, registry  # noqa: F401 (fixture)

SCRIPT = Path(__file__).resolve().parents[1] / "ops" / "dev" / "rehearse_order.py"


@db
def test_a_buyer_goes_from_sign_in_to_a_delivered_report(registry, tmp_path):  # noqa: F811
    spec = importlib.util.spec_from_file_location("rehearse_order", SCRIPT)
    rehearsal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rehearsal)

    steps = rehearsal.rehearse(registry[0], tmp_path)

    assert steps and all(line.startswith("✓") for line in steps)
    kept = {p.name for p in tmp_path.iterdir()}
    assert {"1-profaktura.pdf", "2-uplata.txt", "5-isporaka.txt", "checklist.txt"} <= kept
    delivered = (tmp_path / "5-isporaka.txt").read_text(encoding="utf-8")
    assert "отворени повици од вашата листа" in delivered and "првите пет" not in delivered
