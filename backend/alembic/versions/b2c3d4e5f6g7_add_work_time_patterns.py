"""add_work_time_patterns

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-26 11:00:00.000000

V3.9 新增工作时间模式表，支持灵活配置工作时间和休息时间。
- 周一到周五：8小时（常规）/ 10小时（加班）
- 周六周日：7小时
- 午休：11:45-12:45
- 晚饭（加班时）：14:30-15:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: 新建 work_time_patterns 表并插入默认数据。"""
    op.create_table(
        'work_time_patterns',
        sa.Column('id', sa.String(36), primary_key=True, comment='主键ID'),
        sa.Column('hap_row_id', sa.String(64), nullable=True, comment='HAP 行 ID'),
        sa.Column('sync_status', sa.String(20), nullable=False, server_default='SYNCED', comment='同步状态'),
        sa.Column('synced_at', sa.DateTime(), nullable=True, comment='同步时间'),
        sa.Column('created_at', sa.DateTime(), nullable=True, comment='创建时间'),
        sa.Column('updated_at', sa.DateTime(), nullable=True, comment='更新时间'),
        sa.Column('pattern_code', sa.String(50), nullable=True, comment='模式编号'),
        sa.Column('pattern_name', sa.String(100), nullable=True, comment='模式名称'),
        sa.Column('day_type', sa.String(20), nullable=True, comment='日期类型'),
        sa.Column('work_hours', sa.Float(), nullable=True, comment='每日工时(小时)'),
        sa.Column('slot_duration_minutes', sa.Integer(), nullable=True, comment='时间槽粒度(分钟)'),
        sa.Column('work_periods', sa.Text(), nullable=True, comment='工作时段JSON'),
        sa.Column('break_periods', sa.Text(), nullable=True, comment='休息时段JSON'),
        sa.Column('description', sa.String(200), nullable=True, comment='描述'),
        sa.Column('is_active', sa.Boolean(), nullable=True, comment='是否启用'),
    )

    op.create_index('ix_work_time_patterns_pattern_code', 'work_time_patterns', ['pattern_code'], unique=True)
    op.create_index('ix_work_time_patterns_day_type', 'work_time_patterns', ['day_type'])
    op.create_index('ix_work_time_patterns_hap_row_id', 'work_time_patterns', ['hap_row_id'])
    op.create_index('ix_work_time_patterns_sync_status', 'work_time_patterns', ['sync_status'])

    # 插入默认数据
    import json
    import uuid

    # 周一到周五 8小时（常规）
    op.execute(f"""
        INSERT INTO work_time_patterns (id, sync_status, pattern_code, pattern_name, day_type, work_hours, slot_duration_minutes, work_periods, break_periods, description, is_active, created_at, updated_at)
        VALUES (
            '{str(uuid.uuid4())}', 'SYNCED',
            'WTP-WEEKDAY-NORMAL', '工作日(常规8小时)', 'weekday_normal',
            8.0, 15,
            '{json.dumps([{"start": "08:00", "end": "11:45"}, {"start": "12:45", "end": "17:15"}])}',
            '{json.dumps([{"start": "11:45", "end": "12:45", "type": "lunch"}])}',
            '周一到周五常规工作制，8小时/天', true,
            NOW(), NOW()
        )
    """)

    # 周一到周五 10小时（加班）
    op.execute(f"""
        INSERT INTO work_time_patterns (id, sync_status, pattern_code, pattern_name, day_type, work_hours, slot_duration_minutes, work_periods, break_periods, description, is_active, created_at, updated_at)
        VALUES (
            '{str(uuid.uuid4())}', 'SYNCED',
            'WTP-WEEKDAY-OVERTIME', '工作日(加班10小时)', 'weekday_overtime',
            10.0, 15,
            '{json.dumps([{"start": "08:00", "end": "11:45"}, {"start": "12:45", "end": "14:30"}, {"start": "15:00", "end": "19:30"}])}',
            '{json.dumps([{"start": "11:45", "end": "12:45", "type": "lunch"}, {"start": "14:30", "end": "15:00", "type": "dinner"}])}',
            '周一到周五加班制，10小时/天，含晚饭时间', true,
            NOW(), NOW()
        )
    """)

    # 周六周日 7小时
    op.execute(f"""
        INSERT INTO work_time_patterns (id, sync_status, pattern_code, pattern_name, day_type, work_hours, slot_duration_minutes, work_periods, break_periods, description, is_active, created_at, updated_at)
        VALUES (
            '{str(uuid.uuid4())}', 'SYNCED',
            'WTP-WEEKEND', '周末(7小时)', 'weekend',
            7.0, 15,
            '{json.dumps([{"start": "08:00", "end": "11:45"}, {"start": "12:45", "end": "15:45"}])}',
            '{json.dumps([{"start": "11:45", "end": "12:45", "type": "lunch"}])}',
            '周六周日工作制，7小时/天', true,
            NOW(), NOW()
        )
    """)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_work_time_patterns_sync_status', table_name='work_time_patterns')
    op.drop_index('ix_work_time_patterns_hap_row_id', table_name='work_time_patterns')
    op.drop_index('ix_work_time_patterns_day_type', table_name='work_time_patterns')
    op.drop_index('ix_work_time_patterns_pattern_code', table_name='work_time_patterns')
    op.drop_table('work_time_patterns')
