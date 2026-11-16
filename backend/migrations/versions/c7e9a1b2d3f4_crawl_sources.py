"""crawl sources and document crawl_source_id

Revision ID: c7e9a1b2d3f4
Revises: b434832f5b46
Create Date: 2026-11-16 20:05:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7e9a1b2d3f4"
down_revision: str | None = "b434832f5b46"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "crawl_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("pages_crawled", sa.Integer(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "url", name="uq_crawl_source_company_url"),
    )
    op.create_index("ix_crawl_sources_company_id", "crawl_sources", ["company_id"])
    op.add_column("documents", sa.Column("crawl_source_id", sa.Uuid(), nullable=True))
    op.create_index("ix_documents_crawl_source_id", "documents", ["crawl_source_id"])
    op.create_foreign_key(
        "fk_documents_crawl_source_id",
        "documents",
        "crawl_sources",
        ["crawl_source_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_documents_crawl_source_id", "documents", type_="foreignkey")
    op.drop_index("ix_documents_crawl_source_id", table_name="documents")
    op.drop_column("documents", "crawl_source_id")
    op.drop_index("ix_crawl_sources_company_id", table_name="crawl_sources")
    op.drop_table("crawl_sources")