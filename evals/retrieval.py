"""Retrieval for the verification pass, measured (roadmap P2 s30).

Acceptance: the correct clause is in the top 6 for at least 90% of criteria. What
"correct" means has two answers, and both are measured:

- **the criterion's own quote** — the clause it was extracted from. Every approved
  criterion of the five frozen calls.
- **the evidence** — the words a verification answer rests on, from the tier B
  cassettes. Where the answer quotes something other than the criterion (the craft
  list of Skopje's call, the section of the Economy call that exempts craftsmen),
  this is the passage the model could not answer without.

Each is measured two ways:

- **production** — `verify.call_retriever`: the call's own documents, the cited
  chunk pinned first, the query the criterion's quote. This is gated. For the
  criterion's own quote it is close to certain by construction, and it should be:
  the citation is on record, so finding it is not a search problem.
- **search alone** — the same query without the pin, over *all five* documents at
  once. Reported, not gated. The frozen calls are 3 to 15 chunks each, so inside one
  call six passages is most of the document; pooled, 43 chunks stand in for the long
  guideline of a real call, where the ranking has to earn its place.

Real embedder, real PostgreSQL, inside the caller's rolled-back transaction. Embedding
the frozen documents takes about a minute, so this is its own command and not a part
of the gate every change runs.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.normalise import find_quote
from app.matching import verify
from app.models import Call, EligibilityCriterion
from app.retrieval.embedder import Embedder
from app.retrieval.index import index_pending
from app.retrieval.search import Retrieval, call_snapshot_ids, hybrid_retrieve
from evals import harness, tier_b


@dataclass(frozen=True)
class Target:
    call: str
    label: str
    needle: str
    kind: str  # "quote" | "evidence"


@dataclass(frozen=True)
class Measured:
    target: Target
    production: int | None  # rank in the production path, None = not in the top k
    search: int | None  # rank of the unpinned search over every frozen document


@dataclass
class RetrievalReport:
    k: int
    minimum: float
    rows: list[Measured] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)

    def share(self, kind: str, attr: str, within: int) -> tuple[int, int]:
        rows = [r for r in self.rows if r.target.kind == kind]
        hits = sum(1 for r in rows if (rank := getattr(r, attr)) is not None and rank <= within)
        return hits, len(rows)

    def blocking(self) -> list[str]:
        reasons = [f"incomplete retrieval: {what}" for what in self.incomplete]
        hits, total = self.share("quote", "production", self.k)
        if not total:
            reasons.append("no criteria measured")
        elif hits / total < self.minimum:
            share = f"{hits}/{total}, below {self.minimum:.0%}"
            reasons.append(f"criteria in the top {self.k}: {share}")
        return reasons

    def text(self) -> str:
        lines = [f"Retrieval for verification — top {self.k}", ""]
        for kind, name in (("quote", "criterion's own clause"), ("evidence", "cassette evidence")):
            p = self.share(kind, "production", self.k)
            s1, s = self.share(kind, "search", 1), self.share(kind, "search", self.k)
            lines.append(
                f"  {name:<24} production {p[0]}/{p[1]}   "
                f"search alone, pooled: first {s1[0]}/{s1[1]}, top {self.k} {s[0]}/{s[1]}"
            )
        misses = [r for r in self.rows if r.production is None or r.search != 1]
        if misses:
            lines += ["", "  Not first, or missed (production rank / pooled search rank):"]
            for r in misses:
                said = " ".join(r.target.needle.split())[:60]
                lines.append(
                    f"    {r.production or '—'} / {r.search or '—'}  {r.target.call}  "
                    f"[{r.target.kind}] {said!r}"
                )
        blocking = self.blocking()
        lines += ["", "BLOCKED: " + "; ".join(blocking) if blocking else "Retrieval: pass"]
        return "\n".join(lines)


def targets(fixtures: dict) -> list[Target]:
    found = []
    cassettes = tier_b.load_cassettes()
    for slug, fixture in fixtures.items():
        for criterion in fixture.criteria:
            found.append(Target(slug, criterion["label_mk"], criterion["quote"], "quote"))
        for label, answers in cassettes.get(slug, {}).items():
            quotes = {a.get("quote") for a in answers.values() if isinstance(a, dict)} - {None}
            found += [Target(slug, label, quote, "evidence") for quote in sorted(quotes)]
    return found


def _rank(retrieval: Retrieval, own: list[int], needle: str) -> int | None:
    for rank, passage in enumerate(retrieval.passages, 1):
        # Folded like citations are located (the IPARD notice's Latin "A").
        if passage.snapshot_id in own and find_quote(passage.text, needle, fold=True):
            return rank
    return None


def measure(
    session: Session, session_factory, embedder: Embedder, suite: dict | None = None
) -> RetrievalReport:
    suite = suite or harness.load_suite()
    fixtures = harness.load_fixtures()
    calls: dict[str, Call] = harness.load_registry(session, fixtures)
    session.commit()  # a savepoint: the indexer reads through sessions of its own
    index_pending(session_factory, embedder)

    settings = suite.get("retrieval", {})
    report = RetrievalReport(
        k=settings.get("k", verify.PASSAGES), minimum=settings.get("top_k_share_min", 0.9)
    )
    production = verify.call_retriever(session, embedder, k=report.k)
    documents = {slug: call_snapshot_ids(session, call.id) for slug, call in calls.items()}
    pooled = [i for ids in documents.values() for i in ids]

    for target in targets(fixtures):
        call = calls[target.call]
        criterion = session.scalars(
            select(EligibilityCriterion).where(
                EligibilityCriterion.call_id == call.id,
                EligibilityCriterion.label_mk == target.label,
            )
        ).first()
        pinned = production(call, criterion)
        alone = hybrid_retrieve(session, embedder, pooled, verify.query_for(criterion), k=report.k)
        for name, retrieval in (("production", pinned), ("pooled", alone)):
            if not retrieval.complete:
                report.incomplete.append(f"{target.call} {name}: {target.label}")
        own = documents[target.call]
        report.rows.append(
            Measured(target, _rank(pinned, own, target.needle), _rank(alone, own, target.needle))
        )
    return report
