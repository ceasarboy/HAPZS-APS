"""通用 CRUD 路由工厂，为14张业务表自动生成 RESTful CRUD 端点。

每张表自动获得：
- GET    /           列表查询（分页+筛选）
- GET    /{id}       单条查询
- POST   /           创建
- PUT    /{id}       更新
- DELETE /{id}       删除（软删除）
"""

from typing import Type

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.base import SyncBase
from app.services.crud_service import CrudService
from app.schemas.entities import PaginatedResponse


def create_crud_router(
    model: Type[SyncBase],
    create_schema: Type[BaseModel],
    update_schema: Type[BaseModel],
    out_schema: Type[BaseModel],
    prefix: str,
    tags: list[str],
) -> APIRouter:
    """为指定模型创建 CRUD 路由。

    Args:
        model: SQLAlchemy ORM 模型类
        create_schema: 创建请求 Pydantic 模型
        update_schema: 更新请求 Pydantic 模型
        out_schema: 响应 Pydantic 模型
        prefix: 路由前缀
        tags: OpenAPI 标签

    Returns:
        APIRouter: 包含完整 CRUD 端点的路由器
    """
    router = APIRouter()
    table_name = model.__tablename__

    @router.get("/", response_model=PaginatedResponse, summary=f"查询{table_name}列表")
    async def list_records(
        skip: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
        filter_field: str = Query(default=None, description="过滤字段名"),
        filter_value: str = Query(default=None, description="过滤值"),
        sort_field: str = Query(default=None, description="排序字段名"),
        sort_order: str = Query(default="asc", description="排序方向: asc/desc"),
        db: AsyncSession = Depends(get_db),
    ):
        # M6修复: 支持按字段过滤和排序
        filters = None
        if filter_field and filter_value is not None:
            filters = {filter_field: filter_value}
        order_by = None
        if sort_field:
            order_by = f"-{sort_field}" if sort_order.lower() == "desc" else sort_field
        records, total = await CrudService.list_records(
            db, model, skip=skip, limit=limit, filters=filters, order_by=order_by
        )
        return PaginatedResponse(
            items=[out_schema.model_validate(r) for r in records],
            total=total,
            skip=skip,
            limit=limit,
        )

    @router.get("/{record_id}", response_model=out_schema, summary=f"查询{table_name}详情")
    async def get_record(
        record_id: str,
        db: AsyncSession = Depends(get_db),
    ):
        record = await CrudService.get_record(db, model, record_id)
        if not record:
            raise HTTPException(status_code=404, detail=f"{table_name} 记录不存在")
        return out_schema.model_validate(record)

    @router.post("/", response_model=out_schema, status_code=201, summary=f"创建{table_name}记录")
    async def create_record(
        body: create_schema,
        db: AsyncSession = Depends(get_db),
    ):
        data = body.model_dump(exclude_none=True)
        record = await CrudService.create_record(db, model, data)
        return out_schema.model_validate(record)

    @router.put("/{record_id}", response_model=out_schema, summary=f"更新{table_name}记录")
    async def update_record(
        record_id: str,
        body: update_schema,
        db: AsyncSession = Depends(get_db),
    ):
        data = body.model_dump(exclude_none=True)
        record = await CrudService.update_record(db, model, record_id, data)
        if not record:
            raise HTTPException(status_code=404, detail=f"{table_name} 记录不存在")
        return out_schema.model_validate(record)

    @router.delete("/{record_id}", summary=f"删除{table_name}记录")
    async def delete_record(
        record_id: str,
        db: AsyncSession = Depends(get_db),
    ):
        ok = await CrudService.delete_record(db, model, record_id)
        if not ok:
            raise HTTPException(status_code=404, detail=f"{table_name} 记录不存在")
        return {"detail": "删除成功"}

    return router
