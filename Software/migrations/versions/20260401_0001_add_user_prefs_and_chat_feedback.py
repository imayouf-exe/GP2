"""add user preferences and chatbot feedback tables

Revision ID: 20260401_0001
Revises:
Create Date: 2026-04-01
"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20260401_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_preferences (
            user_id INTEGER PRIMARY KEY,
            display_name TEXT,
            profile_photo_url TEXT,
            ui_theme TEXT NOT NULL DEFAULT 'dark',
            ui_font TEXT NOT NULL DEFAULT 'dm',
            ui_reduced_motion INTEGER NOT NULL DEFAULT 0,
            calendar_default_view TEXT NOT NULL DEFAULT 'month',
            calendar_time_format TEXT NOT NULL DEFAULT '12h',
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS chat_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            role TEXT,
            user_message TEXT NOT NULL,
            bot_reply TEXT NOT NULL,
            confidence TEXT,
            sources TEXT,
            feedback TEXT,
            note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS chat_feedback")
    op.execute("DROP TABLE IF EXISTS user_preferences")
