"""ORM 公共基类，包含同步字段"""
import uuid
import enum
from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class SyncStatus(str, enum.Enum):
    SYNCED = "SYNCED"
    PENDING_CREATE = "PENDING_CREATE"
    PENDING_UPDATE = "PENDING_UPDATE"
    PENDING_DELETE = "PENDING_DELETE"


class SyncBase(Base):
    """公共基类：包含 id, hap_row_id, sync_status, synced_at, created_at, updated_at"""
    __abstract__ = True

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    hap_row_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True, comment="HAP 行 ID")
    sync_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="SYNCED", server_default="SYNCED", index=True, comment="同步状态"
    )
    synced_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="最后同步时间")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, comment="创建时间")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
