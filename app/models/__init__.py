"""SQLAlchemy models.

Every model module is imported here so that `Base.metadata` is complete from a
single import. Alembic's autogenerate depends on that: a model that is not
imported is a table that silently disappears from the next migration.
"""

from app.models.ai import EmailEvent, ModelCall, ModelCallPayload, PromptVersion
from app.models.applicant import Account, ApplicantProfile, ConsentRecord
from app.models.base import Base
from app.models.commerce import Invoice, Order, Product, Subscription
from app.models.documents import DocumentPackage, DocumentTemplate, GeneratedDocument
from app.models.matching import (
    Evidence,
    MatchCriterionOutcome,
    MatchResult,
    MatchRun,
    ReviewQueueItem,
)
from app.models.registry import (
    Call,
    CallDocument,
    Chunk,
    EligibilityCriterion,
    IngestionRun,
    Programme,
    RawSnapshot,
    SourceFeed,
    SourceHealth,
)

__all__ = [
    "Account",
    "ApplicantProfile",
    "Base",
    "Call",
    "CallDocument",
    "Chunk",
    "ConsentRecord",
    "DocumentPackage",
    "DocumentTemplate",
    "EligibilityCriterion",
    "EmailEvent",
    "Evidence",
    "GeneratedDocument",
    "IngestionRun",
    "Invoice",
    "MatchCriterionOutcome",
    "MatchResult",
    "MatchRun",
    "ModelCall",
    "ModelCallPayload",
    "Order",
    "Product",
    "Programme",
    "PromptVersion",
    "RawSnapshot",
    "ReviewQueueItem",
    "SourceFeed",
    "SourceHealth",
    "Subscription",
]
