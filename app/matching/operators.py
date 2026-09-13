"""The vocabulary a hard_structured criterion may use: which profile fields, which operators.

Shared by extraction (P1 s10), which refuses a criterion outside this vocabulary,
and the stage-1 rule interpreter (P2), which adds the evaluating functions here.
Keeping the list in one place means an extracted criterion can never name a
field the interpreter does not know (docs/matching.md §3).

The list is deliberately short. A field belongs here only when the normalised
profile holds exactly the fact a call's condition is about. Geography is absent
until the region and municipality reference data exists in data/; until then a
location condition is extracted as applicant_attest, which asks rather than
excludes.
"""

import enum
import re
from dataclasses import dataclass

from app.models.enums import EntityType


class Operator(enum.StrEnum):
    IN = "in"
    NOT_IN = "not_in"
    PREFIX_IN = "prefix_in"
    PREFIX_NOT_IN = "prefix_not_in"
    GTE = "gte"
    LTE = "lte"
    BETWEEN = "between"


class ProfileField(enum.StrEnum):
    ENTITY_TYPE = "entity_type"
    NACE_CODE = "nace_code"
    AGE_MONTHS = "age_months"
    HEADCOUNT = "headcount"
    INVESTMENT_SIZE_MKD = "investment_size_mkd"


LIST_OPERATORS = frozenset(
    {Operator.IN, Operator.NOT_IN, Operator.PREFIX_IN, Operator.PREFIX_NOT_IN}
)
NUMBER_OPERATORS = frozenset({Operator.GTE, Operator.LTE, Operator.BETWEEN})

# A NACE Rev. 2 section letter, division, group or class: C, 10, 10.1, 10.13.
NACE_CODE = re.compile(r"^(?:[A-U]|\d{2}(?:\.\d{1,2})?)$")


@dataclass(frozen=True)
class FieldSpec:
    operators: frozenset[Operator]
    allowed_values: frozenset[str] | None = None  # for list operators
    value_pattern: re.Pattern[str] | None = None  # for list operators


FIELDS: dict[ProfileField, FieldSpec] = {
    # Entity types overlap (a startup is also micro), so `not_in` over the types a
    # call clearly excludes is safer than `in` over the ones it names.
    ProfileField.ENTITY_TYPE: FieldSpec(
        frozenset({Operator.IN, Operator.NOT_IN}),
        allowed_values=frozenset(EntityType),
    ),
    ProfileField.NACE_CODE: FieldSpec(
        frozenset({Operator.PREFIX_IN, Operator.PREFIX_NOT_IN}), value_pattern=NACE_CODE
    ),
    ProfileField.AGE_MONTHS: FieldSpec(NUMBER_OPERATORS),
    ProfileField.HEADCOUNT: FieldSpec(NUMBER_OPERATORS),
    ProfileField.INVESTMENT_SIZE_MKD: FieldSpec(NUMBER_OPERATORS),
}
