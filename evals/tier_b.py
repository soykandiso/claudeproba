"""Tier B: the verification pass over the frozen calls, with recorded answers (P2 s29).

Tier A stops where the rules stop. Tier B runs `app/matching/verify.py` on top of it —
the real gateway, the real schema validation, the real verbatim check and clamp — with
two stand-ins, both deterministic so the suite answers the same on every run:

- **the model** is `CassetteProvider`, replaying `evals/cassettes/verify/<call>.yaml`;
- **retrieval** is `FixtureRetriever`, the frozen document cut by the production
  chunker and ranked by the words it shares with the query. Retrieval quality is
  P2 s30's to measure; here it only has to hand the model the passages it needs.

A recorded answer that fails a gate is not hidden: the harness reports every one as a
property failure, because in tier B a rejected answer means the cassette or the
retriever is wrong, not the model.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from app.ai.gateway import ProviderReply
from app.models import Call
from app.retrieval.chunker import chunk_spans
from app.retrieval.search import Passage, Retrieval

CASSETTES = Path(__file__).resolve().parent / "cassettes" / "verify"

# The prompt names the condition on the line after this one (prompts/verify_criterion).
_LABEL = re.compile(r"The condition, as the call's reviewer labelled it:\n(.+)\n")
_PASSAGE = re.compile(r'<passage number="(\d+)">\n(.*?)\n</passage>', re.S)
_WORD = re.compile(r"\w{4,}")

K = 6


def load_cassettes() -> dict[str, dict]:
    found = {}
    for path in sorted(CASSETTES.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        found[data["call"]] = data["criteria"]
    return found


class CassetteMissing(RuntimeError):
    pass


@dataclass
class CassetteProvider:
    """A model that answers from the cassettes, for the call and profile it is told."""

    cassettes: dict[str, dict]
    call: str = ""
    profile: str = ""
    requests: list = field(default_factory=list)

    def complete(self, request) -> ProviderReply:
        self.requests.append(request)
        label = _LABEL.search(request.user)
        answers = self.cassettes.get(self.call, {}).get(label.group(1) if label else "")
        if answers is None:
            raise CassetteMissing(f"{self.call}: no cassette for {label and label.group(1)!r}")
        answer = dict(answers.get(self.profile) or answers["default"])
        if answer.get("quote"):
            # The passage is found, not recorded: see evals/cassettes/verify/README.md.
            # A quote in no passage is sent as passage 1, where the verbatim check
            # rejects it — which is what the harness then reports.
            answer["passage"] = next(
                (int(n) for n, text in _PASSAGE.findall(request.user) if answer["quote"] in text),
                1,
            )
        return ProviderReply(
            text=json.dumps(answer, ensure_ascii=False),
            stop_reason="end_turn",
            input_tokens=0,
            output_tokens=0,
        )


class FixtureRetriever:
    """The frozen document's chunks, ranked by shared words with the query."""

    def __init__(self, texts: dict):
        # call id -> (snapshot id, normalised text)
        self._texts = texts

    def __call__(self, call: Call, query: str) -> Retrieval:
        snapshot_id, text = self._texts[call.id]
        wanted = {w.lower() for w in _WORD.findall(query)}
        spans = chunk_spans(text)

        def shared(span) -> int:
            return len(wanted & {w.lower() for w in _WORD.findall(text[span.start : span.end])})

        best = sorted(spans, key=lambda s: (-shared(s), s.ordinal))[:K]
        return Retrieval(
            passages=[
                Passage(
                    chunk_id=s.ordinal,
                    snapshot_id=snapshot_id,
                    char_start=s.start,
                    char_end=s.end,
                    text=text[s.start : s.end],
                    score=float(shared(s)),
                    vector_rank=None,
                    trigram_rank=None,
                )
                for s in best
            ],
            unembedded=0,
            unindexed_snapshots=0,
        )
