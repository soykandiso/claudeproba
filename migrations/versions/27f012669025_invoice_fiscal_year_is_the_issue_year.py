"""invoice fiscal year is the issue year

P4 s54: the number's year, the fiscal year and the issue date are one year.

Revision ID: 27f012669025
Revises: d5c80c005c25
Create Date: 2026-10-13 16:05:06.557449

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy


# revision identifiers, used by Alembic.
revision: str = "27f012669025"
down_revision: Union[str, Sequence[str], None] = "d5c80c005c25"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_check_constraint(
        "fiscal_year", "invoice", "fiscal_year = EXTRACT(YEAR FROM issued_at)"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint("fiscal_year", "invoice", type_="check")
