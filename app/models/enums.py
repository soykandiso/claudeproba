"""Enumerated types.

Native PostgreSQL enums rather than check constraints or lookup tables: the value
set is small, stable and meaningful to read in psql, and the database rejects a
typo at write time instead of letting it sit in a column until someone notices.
"""

import enum


class Lang(enum.StrEnum):
    MK = "mk"
    SQ = "sq"
    EN = "en"
    TR = "tr"


class EntityType(enum.StrEnum):
    SOLE_TRADER = "sole_trader"
    MICRO = "micro"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    NGO = "ngo"
    MUNICIPALITY = "municipality"
    INDIVIDUAL = "individual"
    FARM = "farm"
    STARTUP = "startup"
    OTHER = "other"


class CallStatus(enum.StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    ANNOUNCED = "announced"


class CriterionKind(enum.StrEnum):
    """Who evaluates a criterion, and whether it may exclude an applicant.

    Only HARD_STRUCTURED can produce a 'not eligible' verdict. Everything the
    model touches caps at 'needs verification' (see docs/matching.md section 7).
    """

    HARD_STRUCTURED = "hard_structured"
    SOFT_SCORED = "soft_scored"
    NARRATIVE_VERIFY = "narrative_verify"
    APPLICANT_ATTEST = "applicant_attest"
    DOCUMENTARY = "documentary"


class Verdict(enum.StrEnum):
    ELIGIBLE = "eligible"
    LIKELY_ELIGIBLE = "likely_eligible"
    NEEDS_VERIFICATION = "needs_verification"
    NOT_ELIGIBLE = "not_eligible"


class ReviewKind(enum.StrEnum):
    EXTRACTION = "extraction"
    REPORT = "report"
    DOCUMENT_PACKAGE = "document_package"
    SOURCE_HEALTH = "source_health"


class ReviewState(enum.StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    EDITED = "edited"
    REJECTED = "rejected"


class OrderState(enum.StrEnum):
    CREATED = "created"
    INVOICED = "invoiced"
    PAID = "paid"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class InvoiceKind(enum.StrEnum):
    PROFORMA = "proforma"
    FINAL = "final"
    CREDIT_NOTE = "credit_note"


class AccessMethod(enum.StrEnum):
    API = "api"
    RSS = "rss"
    HTML = "html"
    PDF_INDEX = "pdf_index"
    MANUAL = "manual"
