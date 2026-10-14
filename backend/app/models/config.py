"""求解器配置 SQLAlchemy 模型，使用 SQLAlchemy 2.0 mapped_column 风格。"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SolverConfig(Base):
    """求解器配置表。"""

    __tablename__ = "solver_configs"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        comment="主键 UUID",
    )
    name: Mapped[str] = mapped_column(
        String(128),
        nullable=False,
        comment="配置名称",
    )
    constraints: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="约束配置 JSON",
    )
    objective_weights: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="目标权重 JSON",
    )
    solver_params: Mapped[dict] = mapped_column(
        JSON,
        nullable=False,
        default=dict,
        comment="求解器参数 JSON",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否为默认配置",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        comment="更新时间",
    )

    def __repr__(self) -> str:
        return f"<SolverConfig(name={self.name}, is_default={self.is_default})>"
