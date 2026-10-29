"""initial

Revision ID: 0001
Revises: 
Create Date: 2026-10-29 02:42:02.441086

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('services',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=64), nullable=False),
    sa.Column('duration_min', sa.Integer(), nullable=False),
    sa.Column('price', sa.Integer(), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('users',
    sa.Column('id', sa.BigInteger(), autoincrement=False, nullable=False),
    sa.Column('full_name', sa.String(length=128), nullable=False),
    sa.Column('username', sa.String(length=64), nullable=True),
    sa.Column('phone', sa.String(length=20), nullable=True),
    sa.Column('is_blocked', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('bookings',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('service_id', sa.Integer(), nullable=False),
    sa.Column('starts_at', sa.DateTime(), nullable=False),
    sa.Column('ends_at', sa.DateTime(), nullable=False),
    sa.Column('price', sa.Integer(), nullable=False),
    sa.Column('status', sa.Enum('ACTIVE', 'CANCELLED', name='bookingstatus'), nullable=False),
    sa.Column('reminded_day', sa.Boolean(), nullable=False),
    sa.Column('reminded_hour', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=False),
    sa.ForeignKeyConstraint(['service_id'], ['services.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.create_index('ix_bookings_status_starts_at', ['status', 'starts_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('bookings', schema=None) as batch_op:
        batch_op.drop_index('ix_bookings_status_starts_at')

    op.drop_table('bookings')
    op.drop_table('users')
    op.drop_table('services')
    sa.Enum(name='bookingstatus').drop(op.get_bind(), checkfirst=True)  # тип enum в Postgres
