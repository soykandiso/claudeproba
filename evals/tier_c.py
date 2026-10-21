"""Tier C: the verification pass over the frozen calls, with the real model (P2 s36).

Tier B with one stand-in removed: the answers come from the model `config/models.yaml`
routes `verify_criterion` to, through the real gateway (scrubbing, schema, retry, review).
Retrieval stays `tier_b.FixtureRetriever`, so a difference from tier B is the model's and
not the search's; retrieval has its own measurement (`run.py --retrieval`).

What it is for: weekly, so a model that changes behind the same name is noticed; and
before any prompt change, which is a new prompt version and an evaluation run (CLAUDE.md).

What it costs is bounded twice:

- **a sample**: `suite.yaml`'s `tier_c.profiles`, a few applicants chosen so every frozen
  call is asked about at least once; `--all` asks for every profile, for a prompt change;
- **a budget**: `tier_c.max_eur` (or `--max-eur`), counted from the replies' tokens at
  `config/models.yaml`'s prices and its `eur_per_usd`. A request that would start past it
  is not sent; the run stops, says so, and fails, because a partial measurement is not a
  pass.

What it reports beside the gate: the requests, their tokens and their cost, the cost per
applicant (a stand-in for one report's verification until real reports exist; the real
number is `/admin/troshoci`), and **where the model and the cassette disagree**. A
disagreement does not block: the cassettes are a person's answers, written in P2 s29,
and either side may be the wrong one. It is the list to read before rewriting either.

What blocks is what blocks tier A and B: a false eligible, a false exclusion over 2%, a
model quote that is not verbatim at its offsets. An answer that went to the review queue
(invalid twice) is counted and listed, not blocked on: that is the gateway working.
"""

import re
from dataclasses import dataclass, field

from app.ai.gateway import ProviderReply, Routing
from evals import tier_b

_PROFILE_SAMPLE_KEY = "tier_c"


class BudgetSpent(RuntimeError):
    pass


@dataclass
class Disagreement:
    call: str
    profile: str
    label: str
    recorded: str
    live: str


@dataclass
class LiveProvider:
    """The real provider, counted, capped, and compared with the cassettes as it goes."""

    inner: object
    routing: Routing
    max_eur: float
    rate: float
    cassettes: dict[str, dict]
    call: str = ""
    profile: str = ""
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cost_eur: float = 0.0
    by_profile: dict[str, float] = field(default_factory=dict)
    disagreements: list[Disagreement] = field(default_factory=list)
    compared: int = 0
    asked_pairs: set = field(default_factory=set)

    def complete(self, request) -> ProviderReply:
        if self.cost_eur >= self.max_eur:
            raise BudgetSpent(f"{self.cost_eur:.2f} EUR spent, the budget is {self.max_eur:.2f}")
        reply = self.inner.complete(request)
        usd = self.routing.cost_usd(request.model, reply.input_tokens, reply.output_tokens)
        cost = (usd or 0) * self.rate
        self.requests += 1
        self.asked_pairs.add((self.call, self.profile))
        self.input_tokens += reply.input_tokens
        self.output_tokens += reply.output_tokens
        self.cost_eur += cost
        self.by_profile[self.profile] = self.by_profile.get(self.profile, 0.0) + cost
        self._compare(request, reply)
        return reply

    def _compare(self, request, reply: ProviderReply) -> None:
        label = tier_b._LABEL.search(request.user)
        if not label:
            return
        answers = self.cassettes.get(self.call, {}).get(label.group(1))
        if not answers:
            return
        recorded = (answers.get(self.profile) or answers.get("default") or {}).get("verdict")
        live = _verdict(reply.text)
        if recorded is None or live is None:
            return
        self.compared += 1
        if recorded != live:
            self.disagreements.append(
                Disagreement(self.call, self.profile, label.group(1), recorded, live)
            )


_VERDICT = re.compile(r'"verdict"\s*:\s*"(\w+)"')


def _verdict(text: str) -> str | None:
    found = _VERDICT.search(text or "")
    return found.group(1) if found else None


def sample(suite: dict, profiles: dict, everyone: bool) -> list[str]:
    """Which profiles tier C asks the model about."""
    if everyone:
        return list(profiles)
    chosen = (suite.get(_PROFILE_SAMPLE_KEY) or {}).get("profiles") or []
    unknown = [key for key in chosen if key not in profiles]
    if unknown:
        raise ValueError(f"suite.yaml tier_c.profiles names unknown profiles: {unknown}")
    return list(chosen)


def lines(provider: LiveProvider, asked: list[str], went_to_review: list[str], stopped: str):
    """Tier C's own section of the report."""
    out = ["", "tier C — the real model"]
    out.append(f"  asked about {len(asked)} profile(s): {', '.join(asked)}")
    out.append(
        f"  {provider.requests} request(s), {provider.input_tokens} tokens in, "
        f"{provider.output_tokens} out, {provider.cost_eur:.2f} EUR at list prices"
    )
    for key in asked:
        if key in provider.by_profile:
            out.append(f"      {key:<34} {provider.by_profile[key]:.2f} EUR")
    if stopped:
        out.append(f"  STOPPED: {stopped}")
    out.append(
        f"  agrees with the cassettes on {provider.compared - len(provider.disagreements)} "
        f"of {provider.compared}"
    )
    for d in provider.disagreements:
        out.append(
            f"      {d.profile} × {d.call}: {d.label!r} recorded {d.recorded}, live {d.live}"
        )
    out.append(f"  went to the review queue: {len(went_to_review)}")
    out += [f"      {line}" for line in went_to_review]
    return out
