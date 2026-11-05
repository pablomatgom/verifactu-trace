"""Baseline: empty schema

Revision ID: 0001
Revises:
Create Date: 2026-10-27
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic to order the migrations into a chain.
revision: str = "0001"  # this migration
down_revision: str | Sequence[str] | None = None  # previous revision; None = first one
branch_labels: str | Sequence[str] | None = None  # only used for parallel histories
depends_on: str | Sequence[str] | None = None  # only used to order across branches


def upgrade() -> None:
    """Upgrade schema."""
    # No tables yet. env.py has already created the schema and the version table,
    # so this revision marks the starting point of the history.


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to undo: there is no state before the baseline.
