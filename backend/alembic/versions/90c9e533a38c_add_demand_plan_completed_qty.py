"""add_demand_plan_completed_qty

Revision ID: 90c9e533a38c
Revises: 341a77bbdf1f
Create Date: 2026-07-16 21:29:56.939053

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '90c9e533a38c'
down_revision: Union[str, Sequence[str], None] = '341a77bbdf1f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: 仅添加 demand_plans.completed_qty 列。"""
    op.add_column('demand_plans', sa.Column('completed_qty', sa.Integer(), nullable=True, comment='已完成数量'))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('demand_plans', 'completed_qty')
