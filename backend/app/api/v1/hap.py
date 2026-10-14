"""HAP 数据代理接口（V3：从本地 PostgreSQL 读取数据）。

V2 从 HAP 明道云实时拉取，V3 改为从本地 DB 读取。
API 路径和返回格式保持不变，确保前端无需修改。
"""

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import verify_api_key
from app.database import get_db
from app.models.entities import (
    Product, ProcessInfo, ProductionLine, ProductProcess, LineProcessConfig,
    MaterialMaster, ProcessBOM, MaterialKitting, DemandPlan, ResourceCalendar,
)
from app.models.base import SyncStatus

router = APIRouter()


# ── V3 端点（从本地 DB 读取） ────────────────────────────────────────────


@router.get("/products", summary="拉取产品列表")
async def get_products(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """从本地 DB 查询产品主数据列表。"""
    result = await db.execute(
        select(Product).where(Product.sync_status != SyncStatus.PENDING_DELETE)
    )
    products = result.scalars().all()
    return [
        {
            "id": p.id,
            "code": p.prod_code or "",
            "name": p.prod_name or "",
        }
        for p in products
    ]


@router.get("/demand-plans", summary="拉取需求计划列表")
async def get_demand_plans(
    status: str | None = Query(default=None, description="需求计划状态筛选"),
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """从本地 DB 查询需求计划列表。"""
    query = select(DemandPlan).where(DemandPlan.sync_status != SyncStatus.PENDING_DELETE)
    if status:
        query = query.where(DemandPlan.status == status)
    result = await db.execute(query)
    plans = result.scalars().all()
    return [
        {
            "id": dp.id,
            "dp_code": dp.dp_code or "",
            "dp_quantity": dp.quantity or 0,
            "dp_unit": dp.unit or "",
            "dp_due_date": str(dp.due_date) if dp.due_date else "",
            "dp_priority": dp.priority or "",
            "dp_status": dp.status or "",
            "dp_product": "",
            "dp_remark": dp.remark or "",
        }
        for dp in plans
    ]


@router.get("/resource-calendar", summary="拉取资源日历")
async def get_resource_calendar(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """从本地 DB 查询资源日历数据。"""
    result = await db.execute(
        select(ResourceCalendar).where(ResourceCalendar.sync_status != SyncStatus.PENDING_DELETE)
    )
    calendars = result.scalars().all()
    return [
        {
            "id": rc.id,
            "rc_code": rc.rc_code or "",
            "rc_date": str(rc.rc_date) if rc.rc_date else "",
            "rc_is_workday": "是" if rc.is_working else "否",
            "rc_daily_capacity": 0,
            "rc_efficiency": 0,
            "rc_effective_capacity": rc.available_capacity or 0,
            "rc_equipment_count": 0,
            "rc_worker_count": 0,
            "rc_line": "",
        }
        for rc in calendars
    ]


@router.get("/production-lines", summary="拉取产线列表")
async def get_production_lines(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """从本地 DB 查询产线数据。"""
    result = await db.execute(
        select(ProductionLine).where(ProductionLine.sync_status != SyncStatus.PENDING_DELETE)
    )
    lines = result.scalars().all()
    return [
        {
            "id": pl.id,
            "line_code": pl.line_code or "",
            "line_name": pl.line_name or "",
            "line_type": pl.line_type or "",
            "line_load": 0,
            "line_location": pl.location or "",
            "line_status": pl.status or "",
        }
        for pl in lines
    ]


@router.get("/material-kitting", summary="拉取物料齐套信息")
async def get_material_kitting(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """从本地 DB 查询物料齐套信息数据。"""
    result = await db.execute(
        select(MaterialKitting).where(MaterialKitting.sync_status != SyncStatus.PENDING_DELETE)
    )
    kittings = result.scalars().all()
    rows = [
        {
            "id": mk.id,
            "demand_id": mk.demand_id or "",
            "product_id": mk.product_id or "",
            "process_id": mk.process_id or "",
            "material_id": mk.material_id or "",
            "required_qty": mk.required_qty or 0,
            "available_qty": mk.available_qty or 0,
            "shortage_qty": mk.shortage_qty or 0,
            "kitting_date": str(mk.kitting_date) if mk.kitting_date else "",
            "kitting_status": mk.kitting_status or "",
        }
        for mk in kittings
    ]
    return {"total": len(rows), "rows": rows}


@router.get("/process-info", summary="拉取工序信息")
async def get_process_info(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """从本地 DB 查询工序信息数据。"""
    result = await db.execute(
        select(ProcessInfo).where(ProcessInfo.sync_status != SyncStatus.PENDING_DELETE)
    )
    processes = result.scalars().all()
    return [
        {
            "id": pi.id,
            "proc_code": pi.proc_code or "",
            "proc_name": pi.proc_name or "",
            "proc_type": pi.proc_type or "",
            "constraint_type": pi.constraint_type or "",
            "is_qc_point": str(pi.is_qc_point) if pi.is_qc_point is not None else "",
            "status": pi.status or "",
        }
        for pi in processes
    ]


@router.get("/product-processes", summary="拉取产品工艺")
async def get_product_processes(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """从本地 DB 查询产品工艺数据。"""
    result = await db.execute(
        select(ProductProcess).where(ProductProcess.sync_status != SyncStatus.PENDING_DELETE)
    )
    pps = result.scalars().all()
    return [
        {
            "id": pp.id,
            "product_id": pp.product_id or "",
            "process_id": pp.process_id or "",
            "seq": pp.seq or 0,
            "auto_type": pp.auto_type or "非自动",
            "cycle_time": pp.cycle_time or 0,
            "max_units_per_beat": pp.max_units_per_beat or 1,
            "prep_time": pp.prep_time or 0,
            "wait_time": pp.wait_time or 0,
            "dependency_type": pp.dependency_type or "",
            "wait_includes_offhours": str(pp.wait_includes_offhours) if pp.wait_includes_offhours is not None else "False",
            "is_key": str(pp.is_key) if pp.is_key is not None else "",
            "remark": pp.remark or "",
        }
        for pp in pps
    ]


@router.get("/line-process-configs", summary="拉取产线工艺配置")
async def get_line_process_configs(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """从本地 DB 查询产线工艺配置数据。"""
    result = await db.execute(
        select(LineProcessConfig).where(LineProcessConfig.sync_status != SyncStatus.PENDING_DELETE)
    )
    configs = result.scalars().all()
    return [
        {
            "id": lpc.id,
            "lpc_code": lpc.lpc_code or "",
            "line_id": lpc.line_id or "",
            "process_id": lpc.process_id or "",
            "auto_type": lpc.auto_type or "非自动",
            "is_bottleneck": str(lpc.is_bottleneck) if lpc.is_bottleneck is not None else "",
            "equipment_count": lpc.equipment_count or 0,
            "worker_count": lpc.worker_count or 0,
            "status": lpc.status or "",
        }
        for lpc in configs
    ]


@router.get("/process-bom", summary="拉取工序BOM")
async def get_process_bom(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """从本地 DB 查询工序 BOM 数据。"""
    result = await db.execute(
        select(ProcessBOM).where(ProcessBOM.sync_status != SyncStatus.PENDING_DELETE)
    )
    boms = result.scalars().all()
    return [
        {
            "id": pb.id,
            "product_id": pb.product_id or "",
            "process_id": pb.process_id or "",
            "material_id": pb.material_id or "",
            "unit_qty": pb.unit_qty or 0,
            "reusable": str(pb.reusable) if pb.reusable is not None else "",
            "remark": pb.remark or "",
        }
        for pb in boms
    ]


# ── V1 兼容端点 ──────────────────────────────────────────────────────────


@router.get("/orders", summary="拉取订单明细列表（兼容V1）")
async def get_orders(
    status: str | None = Query(default=None, description="订单状态筛选"),
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """从本地 DB 查询订单明细列表（V1 兼容）。"""
    return await get_demand_plans(status=status, api_key=api_key, db=db)


@router.get("/calendar", summary="拉取生产日历（兼容V1）")
async def get_calendar(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """从本地 DB 查询生产日历数据（V1 兼容）。"""
    return await get_resource_calendar(api_key=api_key, db=db)


@router.get("/workcenters", summary="拉取工作中心（兼容V1）")
async def get_workcenters(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """从本地 DB 查询工作中心数据（V1 兼容）。"""
    return await get_production_lines(api_key=api_key, db=db)


@router.get("/kitting", summary="拉取齐套信息（兼容V1）")
async def get_kitting(
    api_key: str = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """从本地 DB 查询齐套信息数据（V1 兼容）。"""
    return await get_material_kitting(api_key=api_key, db=db)


@router.post("/sync", summary="手动触发全量数据同步")
async def sync_all(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """手动触发全量数据同步（从 HAP 拉取到本地 DB）。"""
    from app.services.sync_service import SyncService
    svc = SyncService()
    results = await svc.pull_all()
    total_created = sum(r.get("created", 0) for r in results.values())
    total_updated = sum(r.get("updated", 0) for r in results.values())
    return {
        "status": "success",
        "message": f"全量数据同步完成: 新增 {total_created} 条, 更新 {total_updated} 条",
        "details": results,
    }
