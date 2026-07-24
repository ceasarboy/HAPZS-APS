"""add_process_schedule_orders

Revision ID: 341a77bbdf1f
Revises: d27061625358
Create Date: 2026-07-16 20:24:50.125042

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '341a77bbdf1f'
down_revision: Union[str, Sequence[str], None] = 'd27061625358'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 创建工序排产单表
    op.create_table('process_schedule_orders',
    sa.Column('pso_code', sa.String(length=100), nullable=True, comment='工序排产单编号(PSO-YYYYMMDD-序号)'),
    sa.Column('demand_id', sa.String(length=36), nullable=True, comment='关联需求计划'),
    sa.Column('product_id', sa.String(length=36), nullable=True, comment='关联产品'),
    sa.Column('process_id', sa.String(length=36), nullable=True, comment='关联工序'),
    sa.Column('seq', sa.Integer(), nullable=True, comment='工序顺序'),
    sa.Column('line_id', sa.String(length=36), nullable=True, comment='关联产线'),
    sa.Column('prev_pso_id', sa.String(length=36), nullable=True, comment='前道工序排产单ID'),
    sa.Column('plan_id', sa.String(length=50), nullable=True, comment='关联排产方案编码'),
    sa.Column('pso_date', sa.Date(), nullable=True, comment='排产日期'),
    sa.Column('pso_time_slot', sa.String(length=50), nullable=True, comment='时间段'),
    sa.Column('pso_quantity', sa.Integer(), nullable=True, comment='排产数量'),
    sa.Column('pso_completed_qty', sa.Integer(), nullable=True, comment='已完成数量'),
    sa.Column('pso_unfinished_qty', sa.Integer(), nullable=True, comment='未完成数量'),
    sa.Column('pso_status', sa.String(length=20), nullable=True, comment='状态(待排产/已排产/报工中/已完成/已失效)'),
    sa.Column('dependency_type', sa.String(length=10), nullable=True, comment='依赖类型(FS/SS/FF/SF)'),
    sa.Column('wait_time', sa.Float(), nullable=True, comment='等待时间(分钟)'),
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('hap_row_id', sa.String(length=64), nullable=True, comment='HAP 行 ID'),
    sa.Column('sync_status', sa.String(length=20), nullable=False, server_default='SYNCED', comment='同步状态'),
    sa.Column('synced_at', sa.DateTime(), nullable=True, comment='最后同步时间'),
    sa.Column('created_at', sa.DateTime(), nullable=False, comment='创建时间'),
    sa.Column('updated_at', sa.DateTime(), nullable=False, comment='更新时间'),
    sa.ForeignKeyConstraint(['demand_id'], ['demand_plans.id'], ),
    sa.ForeignKeyConstraint(['line_id'], ['production_lines.id'], ),
    sa.ForeignKeyConstraint(['process_id'], ['process_info.id'], ),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_process_schedule_orders_demand_id'), 'process_schedule_orders', ['demand_id'], unique=False)
    op.create_index(op.f('ix_process_schedule_orders_line_id'), 'process_schedule_orders', ['line_id'], unique=False)
    op.create_index(op.f('ix_process_schedule_orders_plan_id'), 'process_schedule_orders', ['plan_id'], unique=False)
    op.create_index(op.f('ix_process_schedule_orders_prev_pso_id'), 'process_schedule_orders', ['prev_pso_id'], unique=False)
    op.create_index(op.f('ix_process_schedule_orders_process_id'), 'process_schedule_orders', ['process_id'], unique=False)
    op.create_index(op.f('ix_process_schedule_orders_product_id'), 'process_schedule_orders', ['product_id'], unique=False)
    op.create_index(op.f('ix_process_schedule_orders_pso_code'), 'process_schedule_orders', ['pso_code'], unique=True)
    op.create_index(op.f('ix_process_schedule_orders_pso_date'), 'process_schedule_orders', ['pso_date'], unique=False)
    op.create_index(op.f('ix_process_schedule_orders_pso_status'), 'process_schedule_orders', ['pso_status'], unique=False)

    # 在排产结果表添加关联工序排产单的字段
    op.add_column('schedule_results', sa.Column('pso_id', sa.String(length=36), nullable=True, comment='关联工序排产单'))
    op.create_index(op.f('ix_schedule_results_pso_id'), 'schedule_results', ['pso_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_schedule_results_pso_id'), table_name='schedule_results')
    op.drop_column('schedule_results', 'pso_id')
    op.drop_index(op.f('ix_process_schedule_orders_pso_status'), table_name='process_schedule_orders')
    op.drop_index(op.f('ix_process_schedule_orders_pso_date'), table_name='process_schedule_orders')
    op.drop_index(op.f('ix_process_schedule_orders_pso_code'), table_name='process_schedule_orders')
    op.drop_index(op.f('ix_process_schedule_orders_product_id'), table_name='process_schedule_orders')
    op.drop_index(op.f('ix_process_schedule_orders_process_id'), table_name='process_schedule_orders')
    op.drop_index(op.f('ix_process_schedule_orders_prev_pso_id'), table_name='process_schedule_orders')
    op.drop_index(op.f('ix_process_schedule_orders_plan_id'), table_name='process_schedule_orders')
    op.drop_index(op.f('ix_process_schedule_orders_line_id'), table_name='process_schedule_orders')
    op.drop_index(op.f('ix_process_schedule_orders_demand_id'), table_name='process_schedule_orders')
    op.drop_table('process_schedule_orders')
