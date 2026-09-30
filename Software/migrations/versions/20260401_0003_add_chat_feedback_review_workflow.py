"""add chatbot feedback review workflow columns

Revision ID: 20260401_0003
Revises: 20260401_0002
Create Date: 2026-04-01
"""

from alembic import op


revision = "20260401_0003"
down_revision = "20260401_0002"
branch_labels = None
depends_on = None


def _column_exists(bind, table, col):
    rows = bind.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == col for r in rows)


def upgrade() -> None:
    bind = op.get_bind()
    if not _column_exists(bind, "chat_feedback", "review_action"):
        op.execute("ALTER TABLE chat_feedback ADD COLUMN review_action TEXT")
    if not _column_exists(bind, "chat_feedback", "review_status"):
        op.execute("ALTER TABLE chat_feedback ADD COLUMN review_status TEXT")
    if not _column_exists(bind, "chat_feedback", "review_note"):
        op.execute("ALTER TABLE chat_feedback ADD COLUMN review_note TEXT")
    if not _column_exists(bind, "chat_feedback", "reviewed_at"):
        op.execute("ALTER TABLE chat_feedback ADD COLUMN reviewed_at DATETIME")
    if not _column_exists(bind, "chat_feedback", "reviewed_by"):
        op.execute("ALTER TABLE chat_feedback ADD COLUMN reviewed_by INTEGER")


def downgrade() -> None:
    # SQLite does not support DROP COLUMN safely without table rebuild.
    pass
