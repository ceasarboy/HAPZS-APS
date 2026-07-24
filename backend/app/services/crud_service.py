"""通用 CRUD 服务基类，提供14张业务表的增删改查操作。

所有写操作自动设置 sync_status，确保与 HAP 同步机制联动。
"""

from datetime import datetime
from typing import Any, Type, TypeVar

from loguru import logger
from sqlalchemy import select, func, update, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import SyncStatus, SyncBase

T = TypeVar("T", bound=SyncBase)


class CrudService:
    """通用 CRUD 服务，操作本地 PostgreSQL 业务表。"""

    @staticmethod
    async def list_records(
        session: AsyncSession,
        model: Type[T],
        *,
        skip: int = 0,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
        order_by: str | None = None,
    ) -> tuple[list[T], int]:
        """分页查询记录。

        Returns:
            (records, total) 元组
        """
        query = select(model)
        count_query = select(func.count()).select_from(model)

        if filters:
            for key, value in filters.items():
                if value is not None and hasattr(model, key):
                    col = getattr(model, key)
                    query = query.where(col == value)
                    count_query = count_query.where(col == value)

        # 排除已标记删除的记录
        query = query.where(model.sync_status != SyncStatus.PENDING_DELETE)
        count_query = count_query.where(model.sync_status != SyncStatus.PENDING_DELETE)

        if order_by and hasattr(model, order_by.lstrip("-")):
            col_name = order_by.lstrip("-")
            col = getattr(model, col_name)
            if order_by.startswith("-"):
                query = query.order_by(col.desc())
            else:
                query = query.order_by(col.asc())
        else:
            query = query.order_by(model.created_at.desc())

        query = query.offset(skip).limit(limit)

        result = await session.execute(query)
        records = result.scalars().all()

        total_result = await session.execute(count_query)
        total = total_result.scalar() or 0

        return list(records), total

    @staticmethod
    async def get_record(session: AsyncSession, model: Type[T], record_id: str) -> T | None:
        """根据 ID 获取单条记录。"""
        result = await session.execute(select(model).where(model.id == record_id))
        return result.scalar_one_or_none()

    @staticmethod
    async def create_record(
        session: AsyncSession,
        model: Type[T],
        data: dict[str, Any],
    ) -> T:
        """创建记录，自动设置 sync_status=PENDING_CREATE。"""
        # 移除不属于模型的字段
        valid_fields = {c.name for c in model.__table__.columns}
        filtered_data = {k: v for k, v in data.items() if k in valid_fields}

        record = model(
            **filtered_data,
            sync_status=SyncStatus.PENDING_CREATE,
        )
        session.add(record)
        await session.flush()
        await session.refresh(record)
        logger.info("创建记录成功，表: {}, id: {}", model.__tablename__, record.id)
        return record

    @staticmethod
    async def update_record(
        session: AsyncSession,
        model: Type[T],
        record_id: str,
        data: dict[str, Any],
    ) -> T | None:
        """更新记录，自动设置 sync_status=PENDING_UPDATE（仅当原状态为 SYNCED 时）。"""
        record = await CrudService.get_record(session, model, record_id)
        if not record:
            return None

        valid_fields = {c.name for c in model.__table__.columns}
        for key, value in data.items():
            if key in valid_fields and key not in ("id", "hap_row_id", "sync_status", "synced_at", "created_at"):
                setattr(record, key, value)

        # 仅从 SYNCED 状态转为 PENDING_UPDATE
        if record.sync_status == SyncStatus.SYNCED:
            record.sync_status = SyncStatus.PENDING_UPDATE

        await session.flush()
        await session.refresh(record)
        logger.info("更新记录成功，表: {}, id: {}", model.__tablename__, record.id)
        return record

    @staticmethod
    async def delete_record(
        session: AsyncSession,
        model: Type[T],
        record_id: str,
    ) -> bool:
        """软删除记录（标记 sync_status=PENDING_DELETE）。

        如果记录有 hap_row_id，则标记为待删除等待同步；
        如果没有 hap_row_id（从未同步到 HAP），直接物理删除。
        """
        record = await CrudService.get_record(session, model, record_id)
        if not record:
            return False

        if record.hap_row_id:
            record.sync_status = SyncStatus.PENDING_DELETE
            await session.flush()
            logger.info("软删除记录，表: {}, id: {}, hap_row_id: {}", model.__tablename__, record.id, record.hap_row_id)
        else:
            await session.delete(record)
            await session.flush()
            logger.info("物理删除记录，表: {}, id: {}", model.__tablename__, record.id)

        return True

    @staticmethod
    async def batch_delete_records(
        session: AsyncSession,
        model: Type[T],
        record_ids: list[str],
    ) -> int:
        """批量删除记录。"""
        deleted = 0
        for rid in record_ids:
            ok = await CrudService.delete_record(session, model, rid)
            if ok:
                deleted += 1
        return deleted
