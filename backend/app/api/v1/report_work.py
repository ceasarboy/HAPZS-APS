"""报工管理接口，提供报工单查询、报工操作和每日重置。"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, func

from app.core.security import verify_api_key
from app.database import async_session
from app.models.base import SyncStatus
from app.models.entities import (
    ReportWorkOrder as ORMReportWorkOrder,
    ScheduleResult as ORMScheduleResult,
    ProcessScheduleOrder as ORMProcessScheduleOrder,
    DemandPlan as ORMDemandPlan,
    ProductProcess as ORMProductProcess,
)

router = APIRouter()


class ReportWorkRequest(BaseModel):
    """报工请求模型。"""
    rw_actual_qty: int = Field(..., ge=0, description="实际完成数量")
    rw_defect_qty: int = Field(0, ge=0, description="不良数量")
    rw_remark: str = Field("", max_length=200, description="备注")


@router.get("", summary="查询报工工单列表")
async def list_report_work_orders(
    status: Optional[str] = None,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """查询报工工单列表，可按状态筛选。"""
    async with async_session() as session:
        stmt = select(ORMReportWorkOrder)
        if status:
            stmt = stmt.where(ORMReportWorkOrder.rw_status == status)
        result = await session.execute(stmt.order_by(ORMReportWorkOrder.created_at.desc()))
        rows = result.scalars().all()

    items = []
    for r in rows:
        items.append({
            "id": r.id,
            "rw_code": r.rw_code,
            "dispatch_id": r.dispatch_id,
            "product_id": r.product_id,
            "process_id": r.process_id,
            "line_id": r.line_id,
            "rw_date": r.rw_date.isoformat() if r.rw_date else None,
            "rw_time_slot": r.rw_time_slot,
            "rw_plan_qty": r.rw_plan_qty,
            "rw_actual_qty": r.rw_actual_qty,
            "rw_defect_qty": r.rw_defect_qty,
            "rw_status": r.rw_status,
            "rw_remark": r.rw_remark,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"items": items, "total": len(items)}


@router.post("/daily-reset", summary="每日重置")
async def daily_reset(
    sim_date: Optional[str] = None,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """每日重置：将指定日期之前的"待生产"标记为"已失效"，关闭对应的"待报工"报工工单。

    Args:
        sim_date: 仿真日期（格式 YYYY-MM-DD），用于多日仿真场景。
                  如果不传，默认使用 date.today()。
    """
    today = date.fromisoformat(sim_date) if sim_date else date.today()

    async with async_session() as session:
        # 查找指定日期之前的"待生产"排产结果
        stmt = select(ORMScheduleResult).where(
            and_(
                ORMScheduleResult.sr_date < today,
                ORMScheduleResult.sr_status == "待生产",
            )
        )
        result = await session.execute(stmt)
        expired_results = result.scalars().all()

        expired_count = 0
        closed_report_count = 0
        for sr in expired_results:
            sr.sr_status = "已失效"
            sr.sr_unfinished_qty = (sr.sr_quantity or 0) - (sr.sr_completed_qty or 0)
            sr.sync_status = SyncStatus.PENDING_UPDATE
            expired_count += 1

            # V3.5修复: 不再同步失效工序排产单
            # 原BUG: 当 SR 过期失效时，会把对应 PSO 状态改为"已失效"，
            # 但 PSO 可能跨多天（多 SR 共享一个 PSO），其中部分 SR 已报工
            # 这导致"报工中"的 PSO 被误标"已失效"，被日清删除，pso_completed_qty 丢失
            # completed_qty 暴跌，最终下游工序（如涂覆/包装）PSO 全部被删，排产返回 0 条
            # PSO 状态应由报工逻辑独立维护（已排产→报工中→已完成）

            # 关闭对应的"待报工"报工工单
            rwo_stmt = select(ORMReportWorkOrder).where(
                and_(
                    ORMReportWorkOrder.dispatch_id == sr.id,
                    ORMReportWorkOrder.rw_status == "待报工",
                )
            )
            rwo_result = await session.execute(rwo_stmt)
            rwo = rwo_result.scalars().first()
            if rwo:
                rwo.rw_status = "已关闭"
                rwo.sync_status = SyncStatus.PENDING_UPDATE
                closed_report_count += 1

        await session.commit()

    logger.info("每日重置: 失效{}条, 关闭报工单{}条", expired_count, closed_report_count)
    return {"expired_count": expired_count, "closed_report_count": closed_report_count}


@router.post("/{dispatch_id}", summary="报工")
async def report_work(
    dispatch_id: str,
    req: ReportWorkRequest,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """对单个派工单进行报工。"""
    async with async_session() as session:
        # 1. 查找报工工单
        result = await session.execute(
            select(ORMReportWorkOrder).where(ORMReportWorkOrder.dispatch_id == dispatch_id)
        )
        rwo = result.scalars().first()
        if not rwo:
            raise HTTPException(status_code=404, detail="报工工单不存在")
        if rwo.rw_status != "待报工":
            raise HTTPException(status_code=400, detail=f"报工工单状态为 {rwo.rw_status}，不可报工")

        # 2. 查找对应的排产结果
        sr = await session.get(ORMScheduleResult, dispatch_id)
        if not sr:
            raise HTTPException(status_code=404, detail="排产结果不存在")
        if sr.sr_status != "待生产":
            raise HTTPException(status_code=400, detail=f"排产结果状态为 {sr.sr_status}，不可报工")

        # 3. 校验报工数量
        unfinished_qty = sr.sr_unfinished_qty or 0
        if req.rw_actual_qty > unfinished_qty:
            raise HTTPException(
                status_code=400,
                detail=f"报工数量 {req.rw_actual_qty} 超过未完成数量 {unfinished_qty}",
            )

        # 4. 更新报工工单
        rwo.rw_actual_qty = req.rw_actual_qty
        rwo.rw_defect_qty = req.rw_defect_qty
        rwo.rw_remark = req.rw_remark
        rwo.rw_status = "已报工"
        rwo.sync_status = SyncStatus.PENDING_UPDATE

        # 5. 更新排产结果
        sr.sr_completed_qty = (sr.sr_completed_qty or 0) + req.rw_actual_qty
        sr.sr_unfinished_qty = sr.sr_quantity - sr.sr_completed_qty
        if sr.sr_completed_qty >= sr.sr_quantity:
            sr.sr_status = "已完成"
        sr.sync_status = SyncStatus.PENDING_UPDATE

        # 6. 更新工序排产单
        if sr.pso_id:
            pso = await session.get(ORMProcessScheduleOrder, sr.pso_id)
            if pso:
                # V3.5修复: pso_completed_qty 改为 SUM(SR.sr_completed_qty)
                # 原BUG: 直接赋值 sr.sr_completed_qty 会覆盖多 SR 累积
                # （一个 PSO 可能对应多个 SR，多天排产累积）
                sum_sr_result = await session.execute(
                    select(func.sum(ORMScheduleResult.sr_completed_qty))
                    .where(ORMScheduleResult.pso_id == sr.pso_id)
                )
                total_sr_completed = sum_sr_result.scalar() or 0
                pso.pso_completed_qty = int(total_sr_completed)
                pso.pso_unfinished_qty = max(0, (pso.pso_quantity or 0) - pso.pso_completed_qty)
                if pso.pso_completed_qty >= (pso.pso_quantity or 0):
                    pso.pso_status = "已完成"
                elif pso.pso_completed_qty > 0:
                    pso.pso_status = "报工中"
                pso.sync_status = SyncStatus.PENDING_UPDATE

                # 7. 更新需求计划的已完成数量
                # V3.5修复: completed_qty = 瓶颈工序的累计报工量
                # 瓶颈工序 = 所有已排产工序中 SUM(pso_completed_qty) 最小的工序
                # 原BUG1: min(pso_completed_qty) 取到 0（默认值 0 不是 NULL）
                # 原BUG2: min(单 PSO) 不正确，多天排产需 SUM 后再 min
                if sr.demand_id:
                    seq_sums_stmt = (
                        select(
                            ORMProcessScheduleOrder.seq,
                            func.sum(ORMProcessScheduleOrder.pso_completed_qty).label("seq_sum"),
                        )
                        .where(ORMProcessScheduleOrder.demand_id == sr.demand_id)
                        .where(ORMProcessScheduleOrder.pso_status != "已失效")
                        .group_by(ORMProcessScheduleOrder.seq)
                    )
                    seq_sums_result = await session.execute(seq_sums_stmt)
                    seq_sums = [(r[0], r[1] or 0) for r in seq_sums_result.fetchall()]
                    positive_sums = [s for _, s in seq_sums if s > 0]
                    min_completed = min(positive_sums) if positive_sums else 0
                    dp = await session.get(ORMDemandPlan, sr.demand_id)
                    if dp:
                        dp.completed_qty = int(min_completed)
                        dp.sync_status = SyncStatus.PENDING_UPDATE

        await session.commit()

    logger.info("报工: dispatch_id={}, actual_qty={}, defect_qty={}", dispatch_id, req.rw_actual_qty, req.rw_defect_qty)
    return {
        "dispatch_id": dispatch_id,
        "rw_actual_qty": req.rw_actual_qty,
        "sr_completed_qty": sr.sr_completed_qty,
        "sr_unfinished_qty": sr.sr_unfinished_qty,
        "sr_status": sr.sr_status,
    }
