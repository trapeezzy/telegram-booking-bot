"""time off

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-29 02:44:54.727795

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0002'
down_revision: Union[str, Sequence[str], None] = '0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('time_off',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('starts_at', sa.DateTime(), nullable=False),
    sa.Column('ends_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('time_off', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_time_off_starts_at'), ['starts_at'], unique=False)



def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('time_off', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_time_off_starts_at'))

    op.drop_table('time_off')
