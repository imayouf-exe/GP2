"""add admin audit log table

Revision ID: 20260401_0002
Revises: 20260401_0001
Create Date: 2026-04-01
"""

from alembic import op


revision = "20260401_0002"
down_revision = "20260401_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_user_id INTEGER,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            details TEXT,
            outcome TEXT NOT NULL DEFAULT 'success',
            ip_address TEXT,
            user_agent TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_audit_log")
