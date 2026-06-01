"""guest users and event_views funnel

Revision ID: 7a2f1c9b4e10
Revises: 16e0db2e2abd
Create Date: 2026-06-01 18:30:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "7a2f1c9b4e10"
down_revision: Union[str, None] = "16e0db2e2abd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users.is_guest — server_default false so the column populates on existing rows.
    op.add_column(
        "users",
        sa.Column("is_guest", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # event_views — the funnel's view stage (one row per event+browser session).
    op.create_table(
        "event_views",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("session_token", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "session_token", name="uq_event_view_session"),
    )
    op.create_index(op.f("ix_event_views_event_id"), "event_views", ["event_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_event_views_event_id"), table_name="event_views")
    op.drop_table("event_views")
    op.drop_column("users", "is_guest")
