"""add_simulation_fields_and_system_config

Revision ID: d27061625358
Revises: bad71a523007
Create Date: 2026-07-13 21:45:30.258264

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd27061625358'
down_revision: Union[str, Sequence[str], None] = 'bad71a523007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 创建系统配置表
    op.create_table('system_config',
        sa.Column('key', sa.String(length=100), nullable=False, comment='配置键'),
        sa.Column('value', sa.String(length=500), nullable=True, comment='配置值'),
        sa.PrimaryKeyConstraint('key')
    )

    # 排产结果表新增仿真字段
    op.add_column('schedule_results', sa.Column('sr_completed_qty', sa.Integer(), nullable=True, comment='已完成数量'))
    op.add_column('schedule_results', sa.Column('sr_unfinished_qty', sa.Integer(), nullable=True, comment='未完成数量'))

    # 将现有状态统一为"待生产"
    op.execute("UPDATE schedule_results SET sr_status='待生产' WHERE sr_status='待确认' OR sr_status IS NULL")

    # 为已有记录填充新字段的默认值
    op.execute("UPDATE schedule_results SET sr_completed_qty=0 WHERE sr_completed_qty IS NULL")
    op.execute("UPDATE schedule_results SET sr_unfinished_qty=sr_quantity WHERE sr_unfinished_qty IS NULL AND sr_quantity IS NOT NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('schedule_results', 'sr_unfinished_qty')
    op.drop_column('schedule_results', 'sr_completed_qty')
    op.drop_table('system_config')
