"""human handoff destinations and requests

Revision ID: d9e1f2a3b4c5
Revises: c7e9a1b2d3f4
Create Date: 2026-11-16 21:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d9e1f2a3b4c5"
down_revision: str | None = "c7e9a1b2d3f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("companies", sa.Column("handoff_email", sa.String(length=320), nullable=True))
    op.add_column("companies", sa.Column("telegram_chat_id", sa.String(length=64), nullable=True))
    op.create_table(
        "handoff_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=8), nullable=True),
        sa.Column("email_status", sa.String(length=20), nullable=False),
        sa.Column("telegram_status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_handoff_requests_company_id", "handoff_requests", ["company_id"])


def downgrade() -> None:
    op.drop_index("ix_handoff_requests_company_id", table_name="handoff_requests")
    op.drop_table("handoff_requests")
    op.drop_column("companies", "telegram_chat_id")
    op.drop_column("companies", "handoff_email")