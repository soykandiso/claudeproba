"""entity type craftsman

A registered craftsman is a legal form of its own, and two of the five calls in
the evaluation suite turn on it (Skopje's endangered crafts, the Economy
ministry's machines-and-tools call). Autogenerate does not see a new value in a
native enum, so this one is written by hand.

Revision ID: 1b093080ae25
Revises: 3adfce186d77
Create Date: 2026-09-22 19:17:11.847053

"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "1b093080ae25"
down_revision: Union[str, Sequence[str], None] = "3adfce186d77"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.execute("ALTER TYPE entity_type ADD VALUE IF NOT EXISTS 'craftsman' AFTER 'sole_trader'")


def downgrade() -> None:
    """Leave the value in place.

    PostgreSQL cannot drop a value from an enum, and rebuilding the type would have
    to rewrite every column and array that uses it. An unused value costs nothing.
    """
