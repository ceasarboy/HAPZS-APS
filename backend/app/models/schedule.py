"""排产任务 SQLAlchemy 模型，使用 SQLAlchemy 2.0 mapped_column 风格。"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class TaskStatus(str, enum.Enum):
    """排产任务状态枚举。"""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class ScheduleTask(Base):
    """排产任务表。"""

    __tablename__ = "schedule_tasks"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="主键 UUID",
    )
    task_id: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        index=True,
        comment="Celery 任务 ID",
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus),
        nullable=False,
        default=TaskStatus.PENDING,
        comment="任务状态",
    )
    config: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="求解配置 JSON",
    )
    result_summary: Mapped[dict | None] = mapped_column(
        JSON,
        nullable=True,
        comment="结果汇总 JSON",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="创建时间",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="开始执行时间",
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
        comment="完成时间",
    )
    error_msg: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="错误信息",
    )

    def __repr__(self) -> str:
        return f"<ScheduleTask(task_id={self.task_id}, status={self.status})>"
