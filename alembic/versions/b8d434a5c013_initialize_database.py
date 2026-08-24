"""initialize database

Revision ID: b8d434a5c013
Revises: 
Create Date: 2026-08-24 15:14:20.172135

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b8d434a5c013'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "persistent_boards",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("guild_id", sa.BigInteger, nullable=False),
        sa.Column("discord_channel_id", sa.BigInteger, nullable=False),
        sa.Column("discord_message_id", sa.BigInteger, nullable=True),
        sa.Column("inserted_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("persistent_boards")
