"""add_process_delivery_plans

Revision ID: a1b2c3d4e5f6
Revises: 90c9e533a38c
Create Date: 2026-07-26 10:00:00.000000

V3.8 新增工序交付计划表，用于持久化记录各工序的计划和完成情况。
- process_delivery_plans 表：工序交付计划（持久化，日终不清理）
- schedule_results 表增加 pdp_id 字段关联到工序交付计划
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '90c9e533a38c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: 新建 process_delivery_plans 表，schedule_results 增加 pdp_id 字段。"""
    # 1. 创建 process_delivery_plans 表
    op.create_table(
        'process_delivery_plans',
        sa.Column('id', sa.String(36), primary_key=True, comment='主键ID'),
        sa.Column('hap_row_id', sa.String(64), nullable=True, comment='HAP 行 ID'),
        sa.Column('sync_status', sa.String(20), nullable=False, server_default='SYNCED', comment='同步状态'),
        sa.Column('synced_at', sa.DateTime(), nullable=True, comment='同步时间'),
        sa.Column('created_at', sa.DateTime(), nullable=True, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=True, comment='更新时间'),
        sa.Column('pdp_code', sa.String(100), nullable=True, comment='工序交付计划编号'),
        sa.Column('demand_id', sa.String(36), sa.ForeignKey('demand_plans.id'), nullable=True, comment='关联需求计划'),
        sa.Column('product_id', sa.String(36), sa.ForeignKey('products.id'), nullable=True, comment='关联产品'),
        sa.Column('process_id', sa.String(36), sa.ForeignKey('process_info.id'), nullable=True, comment='关联工序'),
        sa.Column('seq', sa.Integer(), nullable=True, comment='工序顺序'),
        sa.Column('line_id', sa.String(36), sa.ForeignKey('production_lines.id'), nullable=True, comment='关联产线'),
        sa.Column('prev_pdp_id', sa.String(36), nullable=True, comment='前道工序交付计划ID'),
        sa.Column('plan_id', sa.String(50), nullable=True, comment='关联排产方案编码'),
        sa.Column('planned_qty', sa.Integer(), nullable=True, comment='计划数量(=需求数量)'),
        sa.Column('completed_qty', sa.Integer(), nullable=True, comment='已完成数量'),
        sa.Column('unfinished_qty', sa.Integer(), nullable=True, comment='未完成数量'),
        sa.Column('planned_start_time', sa.Date(), nullable=True, comment='计划开始时间'),
        sa.Column('planned_finish_time', sa.Date(), nullable=True, comment='计划完成时间'),
        sa.Column('pdp_status', sa.String(20), nullable=True, comment='状态'),
        sa.Column('dependency_type', sa.String(10), nullable=True, comment='依赖类型'),
        sa.Column('wait_time', sa.Float(), nullable=True, comment='等待时间(分钟)'),
    )

    # 创建索引
    op.create_index('ix_process_delivery_plans_hap_row_id', 'process_delivery_plans', ['hap_row_id'])
    op.create_index('ix_process_delivery_plans_sync_status', 'process_delivery_plans', ['sync_status'])
    op.create_index('ix_process_delivery_plans_pdp_code', 'process_delivery_plans', ['pdp_code'], unique=True)
    op.create_index('ix_process_delivery_plans_demand_id', 'process_delivery_plans', ['demand_id'])
    op.create_index('ix_process_delivery_plans_product_id', 'process_delivery_plans', ['product_id'])
    op.create_index('ix_process_delivery_plans_process_id', 'process_delivery_plans', ['process_id'])
    op.create_index('ix_process_delivery_plans_line_id', 'process_delivery_plans', ['line_id'])
    op.create_index('ix_process_delivery_plans_prev_pdp_id', 'process_delivery_plans', ['prev_pdp_id'])
    op.create_index('ix_process_delivery_plans_plan_id', 'process_delivery_plans', ['plan_id'])
    op.create_index('ix_process_delivery_plans_planned_start_time', 'process_delivery_plans', ['planned_start_time'])
    op.create_index('ix_process_delivery_plans_planned_finish_time', 'process_delivery_plans', ['planned_finish_time'])
    op.create_index('ix_process_delivery_plans_pdp_status', 'process_delivery_plans', ['pdp_status'])

    # 2. schedule_results 表增加 pdp_id 字段
    op.add_column('schedule_results', sa.Column('pdp_id', sa.String(36), sa.ForeignKey('process_delivery_plans.id'), nullable=True, comment='关联工序交付计划(V3.8)'))
    op.create_index('ix_schedule_results_pdp_id', 'schedule_results', ['pdp_id'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_schedule_results_pdp_id', table_name='schedule_results')
    op.drop_column('schedule_results', 'pdp_id')

    op.drop_index('ix_process_delivery_plans_pdp_status', table_name='process_delivery_plans')
    op.drop_index('ix_process_delivery_plans_planned_finish_time', table_name='process_delivery_plans')
    op.drop_index('ix_process_delivery_plans_planned_start_time', table_name='process_delivery_plans')
    op.drop_index('ix_process_delivery_plans_plan_id', table_name='process_delivery_plans')
    op.drop_index('ix_process_delivery_plans_prev_pdp_id', table_name='process_delivery_plans')
    op.drop_index('ix_process_delivery_plans_line_id', table_name='process_delivery_plans')
    op.drop_index('ix_process_delivery_plans_process_id', table_name='process_delivery_plans')
    op.drop_index('ix_process_delivery_plans_product_id', table_name='process_delivery_plans')
    op.drop_index('ix_process_delivery_plans_demand_id', table_name='process_delivery_plans')
    op.drop_index('ix_process_delivery_plans_pdp_code', table_name='process_delivery_plans')
    op.drop_table('process_delivery_plans')
