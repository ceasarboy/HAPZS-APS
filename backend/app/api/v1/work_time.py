"""V3.9 工作时间模式设置 API。

提供 WorkTimePattern 的 CRUD 操作，支持灵活配置工作时间和休息时间。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.models.entities import WorkTimePattern as ORMWorkTimePattern

router = APIRouter(prefix="/work-time-patterns", tags=["工作时间模式"])


# ── Pydantic 模型 ────────────────────────────────────────────────────────

class WorkPeriod(BaseModel):
    start: str
    end: str


class BreakPeriod(BaseModel):
    start: str
    end: str
    type: str = "lunch"


class WorkTimePatternBase(BaseModel):
    pattern_code: str | None = None
    pattern_name: str | None = None
    day_type: str | None = None
    work_hours: float | None = None
    slot_duration_minutes: int | None = 15
    work_periods: list[WorkPeriod] | None = None
    break_periods: list[BreakPeriod] | None = None
    description: str | None = None
    is_active: bool | None = True


class WorkTimePatternCreate(WorkTimePatternBase):
    pass


class WorkTimePatternUpdate(WorkTimePatternBase):
    pattern_code: str | None = None
    pattern_name: str | None = None
    day_type: str | None = None
    work_hours: float | None = None
    slot_duration_minutes: int | None = None
    work_periods: list[WorkPeriod] | None = None
    break_periods: list[BreakPeriod] | None = None
    description: str | None = None
    is_active: bool | None = None


class WorkTimePatternResponse(WorkTimePatternBase):
    id: str
    created_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


# ── 辅助函数 ────────────────────────────────────────────────────────────

def _to_orm_fields(data: WorkTimePatternBase) -> dict[str, Any]:
    """将 Pydantic 模型转换为 ORM 字段。"""
    fields: dict[str, Any] = {}
    if data.pattern_code is not None:
        fields["pattern_code"] = data.pattern_code
    if data.pattern_name is not None:
        fields["pattern_name"] = data.pattern_name
    if data.day_type is not None:
        fields["day_type"] = data.day_type
    if data.work_hours is not None:
        fields["work_hours"] = data.work_hours
    if data.slot_duration_minutes is not None:
        fields["slot_duration_minutes"] = data.slot_duration_minutes
    if data.work_periods is not None:
        fields["work_periods"] = json.dumps([p.dict() for p in data.work_periods])
    if data.break_periods is not None:
        fields["break_periods"] = json.dumps([p.dict() for p in data.break_periods])
    if data.description is not None:
        fields["description"] = data.description
    if data.is_active is not None:
        fields["is_active"] = data.is_active
    return fields


def _to_response(orm: ORMWorkTimePattern) -> WorkTimePatternResponse:
    """将 ORM 对象转换为响应模型。"""
    work_periods = []
    if orm.work_periods:
        try:
            work_periods = [WorkPeriod(**p) for p in json.loads(orm.work_periods)]
        except (json.JSONDecodeError, TypeError):
            pass
    break_periods = []
    if orm.break_periods:
        try:
            break_periods = [BreakPeriod(**p) for p in json.loads(orm.break_periods)]
        except (json.JSONDecodeError, TypeError):
            pass
    return WorkTimePatternResponse(
        id=orm.id,
        pattern_code=orm.pattern_code,
        pattern_name=orm.pattern_name,
        day_type=orm.day_type,
        work_hours=orm.work_hours,
        slot_duration_minutes=orm.slot_duration_minutes,
        work_periods=work_periods,
        break_periods=break_periods,
        description=orm.description,
        is_active=orm.is_active,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


# ── API 端点 ────────────────────────────────────────────────────────────

@router.get("", response_model=list[WorkTimePatternResponse], summary="获取所有工作时间模式")
async def list_work_time_patterns():
    """获取所有工作时间模式列表。"""
    async with async_session() as session:
        result = await session.execute(
            select(ORMWorkTimePattern).order_by(ORMWorkTimePattern.day_type)
        )
        rows = result.scalars().all()
    return [_to_response(r) for r in rows]


@router.get("/{pattern_id}", response_model=WorkTimePatternResponse, summary="获取单个工作时间模式")
async def get_work_time_pattern(pattern_id: str):
    """根据 ID 获取工作时间模式。"""
    async with async_session() as session:
        result = await session.execute(
            select(ORMWorkTimePattern).where(ORMWorkTimePattern.id == pattern_id)
        )
        orm = result.scalar_one_or_none()
        if not orm:
            raise HTTPException(status_code=404, detail="工作时间模式不存在")
    return _to_response(orm)


@router.post("", response_model=WorkTimePatternResponse, summary="创建工作时间模式")
async def create_work_time_pattern(data: WorkTimePatternCreate):
    """创建新的工作时间模式。"""
    fields = _to_orm_fields(data)
    fields["id"] = str(uuid.uuid4())
    fields["sync_status"] = "SYNCED"
    fields["created_at"] = datetime.now()
    fields["updated_at"] = datetime.now()

    orm = ORMWorkTimePattern(**fields)
    async with async_session() as session:
        session.add(orm)
        await session.commit()
        await session.refresh(orm)
    return _to_response(orm)


@router.put("/{pattern_id}", response_model=WorkTimePatternResponse, summary="更新工作时间模式")
async def update_work_time_pattern(pattern_id: str, data: WorkTimePatternUpdate):
    """更新工作时间模式。"""
    fields = _to_orm_fields(data)
    fields["updated_at"] = datetime.now()

    async with async_session() as session:
        result = await session.execute(
            select(ORMWorkTimePattern).where(ORMWorkTimePattern.id == pattern_id)
        )
        orm = result.scalar_one_or_none()
        if not orm:
            raise HTTPException(status_code=404, detail="工作时间模式不存在")

        for k, v in fields.items():
            setattr(orm, k, v)

        await session.commit()
        await session.refresh(orm)
    return _to_response(orm)


@router.delete("/{pattern_id}", summary="删除工作时间模式")
async def delete_work_time_pattern(pattern_id: str):
    """删除工作时间模式。"""
    async with async_session() as session:
        result = await session.execute(
            select(ORMWorkTimePattern).where(ORMWorkTimePattern.id == pattern_id)
        )
        orm = result.scalar_one_or_none()
        if not orm:
            raise HTTPException(status_code=404, detail="工作时间模式不存在")
        await session.delete(orm)
        await session.commit()
    return {"message": "已删除", "id": pattern_id}
