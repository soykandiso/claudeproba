"""Pydantic response models: the only shapes model output is accepted in (CLAUDE.md invariant 5).

The gateway validates every reply against one of these. A reply that fails is
retried once and then goes to the review queue, so the validators below are the
place to refuse anything that must never be stored -- not a place to repair it.
"""

import datetime as dt
from collections.abc import Iterator
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.matching.operators import FIELDS, LIST_OPERATORS, Operator, ProfileField
from app.models.enums import CriterionKind


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Quoted(_Strict):
    """A fact and the words it was read from.

    Only the words are taken from the model. Where they are -- snapshot and
    character offsets -- is computed in code by finding them verbatim in the
    document (app/ingestion/extract.py), because an offset a model reports is a
    claim, not a citation.
    """

    document: int = Field(ge=1, description="Index of the <document> the quote is copied from.")
    quote: str = Field(
        min_length=8,
        max_length=1000,
        description="Copied character for character from one line of that document.",
    )


class CitedText(Quoted):
    value: str = Field(min_length=1, max_length=500)


class CitedDate(Quoted):
    value: dt.date


class CitedDeadline(CitedDate):
    time: str | None = Field(
        default=None,
        pattern=r"^([01]\d|2[0-3]):[0-5]\d$",
        description="HH:MM if the text gives one.",
    )


class CitedAmount(Quoted):
    amount: float = Field(gt=0)
    currency: Literal["MKD", "EUR"]


class CitedPercent(Quoted):
    value: float = Field(gt=0, le=100)


class ExtractedCriterion(Quoted):
    kind: CriterionKind
    label_mk: str = Field(min_length=3, max_length=300)
    applies_to_all_applicants: bool = Field(
        description="False when the condition applies only to some applicant types."
    )
    field: ProfileField | None = None
    operator: Operator | None = None
    values: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    confidence: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _predicate_matches_kind(self) -> "ExtractedCriterion":
        predicate = (self.field, self.operator, self.values, self.minimum, self.maximum)
        if self.kind != CriterionKind.HARD_STRUCTURED:
            if any(part is not None for part in predicate):
                raise ValueError(f"a {self.kind} criterion carries no field, operator or values")
            return self

        # hard_structured is the only kind that can exclude an applicant, so it is
        # held to the whole vocabulary in app/matching/operators.py.
        if self.field is None or self.operator is None:
            raise ValueError("a hard_structured criterion needs a field and an operator")
        if not self.applies_to_all_applicants:
            raise ValueError(
                "a condition for only some applicant types cannot be hard_structured; "
                "use narrative_verify or applicant_attest"
            )
        spec = FIELDS[self.field]
        if self.operator not in spec.operators:
            allowed = ", ".join(sorted(spec.operators))
            raise ValueError(f"{self.field} takes only these operators: {allowed}")

        if self.operator in LIST_OPERATORS:
            if not self.values or self.minimum is not None or self.maximum is not None:
                raise ValueError(f"{self.operator} needs a non-empty values list and nothing else")
            for value in self.values:
                if spec.allowed_values is not None and value not in spec.allowed_values:
                    raise ValueError(f"{value!r} is not a valid {self.field}")
                if spec.value_pattern is not None and not spec.value_pattern.match(value):
                    raise ValueError(f"{value!r} is not a valid {self.field}")
            return self

        if self.values is not None:
            raise ValueError(f"{self.operator} takes minimum/maximum, not values")
        needs = {
            Operator.GTE: (True, False),
            Operator.LTE: (False, True),
            Operator.BETWEEN: (True, True),
        }[self.operator]
        if (self.minimum is not None, self.maximum is not None) != needs:
            raise ValueError(f"{self.operator} needs exactly: {_bounds_needed(self.operator)}")
        if any(bound is not None and bound < 0 for bound in (self.minimum, self.maximum)):
            raise ValueError("bounds cannot be negative")
        if self.operator == Operator.BETWEEN and self.minimum > self.maximum:
            raise ValueError("minimum is greater than maximum")
        return self

    def value_json(self) -> dict | None:
        """The eligibility_criterion.value_json this predicate is stored as."""
        if self.operator is None:
            return None
        if self.operator in LIST_OPERATORS:
            return {"values": list(self.values)}
        return {
            key: bound
            for key, bound in (("min", self.minimum), ("max", self.maximum))
            if bound is not None
        }


def _bounds_needed(operator: Operator) -> str:
    return {"gte": "minimum", "lte": "maximum", "between": "minimum and maximum"}[operator]


class CallExtraction(_Strict):
    """What extraction reads from a call's documents (docs/architecture.md §3.1).

    Every fact carries its quote. Nothing here is published: it becomes an
    unpublished call with unapproved criteria, and a human approves it.
    """

    document_kind: Literal["call", "advance_notice", "not_a_funding_call"]
    title_mk: CitedText | None
    reference_code: CitedText | None = None
    published_on: CitedDate | None = None
    opens_on: CitedDate | None = None
    deadline: CitedDeadline | None = None
    total_budget: CitedAmount | None = None
    grant_min: CitedAmount | None = None
    grant_max: CitedAmount | None = None
    grant_share_pct: CitedPercent | None = Field(
        default=None, description="Share of eligible costs the grant pays, as a percentage."
    )
    criteria: list[ExtractedCriterion] = Field(default_factory=list)
    notes_for_reviewer: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _a_call_has_a_title(self) -> "CallExtraction":
        if self.document_kind != "not_a_funding_call" and self.title_mk is None:
            raise ValueError(f"a document of kind {self.document_kind} needs title_mk")
        return self

    def quoted(self) -> Iterator[tuple[str, Quoted]]:
        """Every cited item with a stable path ("deadline", "criteria.3")."""
        for name in type(self).model_fields:
            value = getattr(self, name)
            if isinstance(value, Quoted):
                yield name, value
        for index, criterion in enumerate(self.criteria):
            yield f"criteria.{index}", criterion


# ------------------------------------------------------------------ verification (P2 s29)


class VerificationResult(_Strict):
    """One criterion checked against the passages retrieved for it (docs/matching.md §5).

    The model's vocabulary, not the customer's: `satisfied`, `not_satisfied` or
    `unclear`. `app/matching/verify.py` clamps it, and nothing the model says here
    can make a call `not_eligible` (CLAUDE.md invariant 1).

    **The passage is named by its number in the prompt, not by a database id.** An
    id the model copies is a claim like any offset (see `Quoted`); the number maps
    to the passage in code, and the quote is then searched for in that passage.
    """

    verdict: Literal["satisfied", "not_satisfied", "unclear"]
    confidence: float = Field(ge=0, le=1)
    passage: int | None = Field(
        default=None, ge=1, description="Number of the <passage> the quote is copied from."
    )
    quote: str | None = Field(
        default=None,
        min_length=8,
        max_length=1000,
        description="Copied character for character from that passage.",
    )
    reasoning_mk: str = Field(min_length=10, max_length=1500)

    @model_validator(mode="after")
    def _decided_means_quoted(self) -> "VerificationResult":
        # A decision without the words it rests on is the claim invariant 2
        # forbids; only "unclear" may come back without a quote.
        if self.verdict != "unclear" and (self.passage is None or self.quote is None):
            raise ValueError(f"a {self.verdict} verdict needs a passage and a quote")
        if (self.passage is None) != (self.quote is None):
            raise ValueError("passage and quote come together or not at all")
        return self
