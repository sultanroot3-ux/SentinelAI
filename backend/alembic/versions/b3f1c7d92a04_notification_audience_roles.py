"""notification audience_roles

Restricts who may see a notification. NULL means everyone, so every row that
exists when this runs keeps its current visibility and no data migration is
needed — the restriction is opt-in per notification.

Revision ID: b3f1c7d92a04
Revises: 6c946c8f3423
Create Date: 2026-08-05 21:05:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'b3f1c7d92a04'
down_revision: Union[str, Sequence[str], None] = '6c946c8f3423'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add the nullable audience column."""
    op.add_column(
        'notifications',
        sa.Column('audience_roles', sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    """Drop it again.

    Downgrading makes every restricted notification visible to every role, so
    any watchlist alerts already stored become readable by a receptionist.
    Prune them first if that matters.
    """
    op.drop_column('notifications', 'audience_roles')
