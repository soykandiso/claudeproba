"""review kind verification

Stage 3 (P2 s29) sends two things to a human: a verification whose model output
failed validation twice, and one whose quote is not in the passage it named.
Autogenerate does not see a new value in a native enum, so this is written by hand.

Revision ID: 13672ae6492a
Revises: 1b093080ae25
Create Date: 2026-09-22

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "13672ae6492a"
down_revision: Union[str, Sequence[str], None] = "1b093080ae25"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE review_kind ADD VALUE IF NOT EXISTS 'verification' AFTER 'extraction'")


def downgrade() -> None:
    """Leave the value in place: PostgreSQL cannot drop a value from an enum."""
