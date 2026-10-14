"""报工管理接口，提供报工单查询、报工操作和每日重置。"""

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import select, and_, func, delete

from app.core.security import verify_api_key
from app.database import async_session
from app.models.base import SyncStatus
from app.models.entities import (
    ReportWorkOrder as ORMReportWorkOrder,
    ScheduleResult as ORMScheduleResult,
    ProcessScheduleOrder as ORMProcessScheduleOrder,
    ProcessDeliveryPlan as ORMProcessDeliveryPlan,
    DemandPlan as ORMDemandPlan,
    ProductProcess as ORMProductProcess,
    Product as ORMProduct,
    ProcessInfo as ORMProcessInfo,
)

router = APIRouter()


class ReportWorkRequest(BaseModel):
    """报工请求模型。"""
    rw_actual_qty: int = Field(..., ge=0, description="实际完成数量")
    rw_defect_qty: int = Field(0, ge=0, description="不良数量")
    rw_remark: str = Field("", max_length=200, description="备注")


@router.get("/list", summary="查询报工工单列表（含可报工数量）")
async def list_report_work_orders(
    status: Optional[str] = None,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """查询报工工单列表，可按状态筛选。

    V3.9.3: 返回 available_qty（可报工数量）字段：
    - 有前置工序：可报工数量 = 前置工序完成数量 - 本工序已报工数量
    - 无前置工序（首道工序）：可报工数量 = 排产数量 - 已报工数量
    """
    async with async_session() as session:
        stmt = select(ORMReportWorkOrder)
        if status:
            stmt = stmt.where(ORMReportWorkOrder.rw_status == status)
        result = await session.execute(stmt.order_by(ORMReportWorkOrder.created_at.desc()))
        rows = result.scalars().all()

        # V3.9.3 批量查询关联的 SR 和前置 PSO 完成数量，计算可报工数量
        dispatch_ids = [r.dispatch_id for r in rows if r.dispatch_id]
        sr_map: dict[str, ORMScheduleResult] = {}
        if dispatch_ids:
            sr_result = await session.execute(
                select(ORMScheduleResult).where(ORMScheduleResult.id.in_(dispatch_ids))
            )
            for sr in sr_result.scalars().all():
                sr_map[sr.id] = sr

        # 查询所有相关 PSO（含 prev_pso_id 链）
        pso_ids = {sr.pso_id for sr in sr_map.values() if sr.pso_id}
        prev_pso_ids = set()
        pso_map: dict[str, ORMProcessScheduleOrder] = {}
        if pso_ids:
            pso_result = await session.execute(
                select(ORMProcessScheduleOrder).where(ORMProcessScheduleOrder.id.in_(pso_ids))
            )
            for pso in pso_result.scalars().all():
                pso_map[pso.id] = pso
                if pso.prev_pso_id:
                    prev_pso_ids.add(pso.prev_pso_id)
        # 查询前置 PSO
        if prev_pso_ids:
            prev_result = await session.execute(
                select(ORMProcessScheduleOrder).where(ORMProcessScheduleOrder.id.in_(prev_pso_ids))
            )
            for pso in prev_result.scalars().all():
                pso_map[pso.id] = pso

    items = []
    for r in rows:
        # V3.9.3 计算可报工数量
        available_qty = 0
        sr = sr_map.get(r.dispatch_id) if r.dispatch_id else None
        if sr:
            pso = pso_map.get(sr.pso_id) if sr.pso_id else None
            # V3.9.3 本工序已报工数量统一从 PSO 维度取（与前置工序口径一致）
            current_completed = (pso.pso_completed_qty or 0) if pso else (sr.sr_completed_qty or 0)
            if pso and pso.prev_pso_id:
                # 有前置工序：可报工数量 = 前置工序完成数量 - 本工序已报工数量
                prev_pso = pso_map.get(pso.prev_pso_id)
                prev_completed = (prev_pso.pso_completed_qty or 0) if prev_pso else 0
                available_qty = max(0, prev_completed - current_completed)
            else:
                # 无前置工序（首道工序）：可报工数量 = 排产数量 - 已报工数量
                planned_qty = (pso.pso_quantity or 0) if pso else (sr.sr_quantity or 0)
                available_qty = max(0, planned_qty - current_completed)

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
            "available_qty": available_qty,  # V3.9.3 可报工数量
            "created_at": r.created_at.isoformat() if r.created_at else None,
        })
    return {"items": items, "total": len(items)}


@router.get("/process-progress", summary="工序进展看板（订单视角）")
async def process_progress(
    api_key: str = Depends(verify_api_key),
) -> dict:
    """工序进展看板：从订单视角展示每道工序进展 + 最后一道工序交付计划。

    返回两部分数据：
    - orders: 每订单×每工序的计划/已完成/未完成/预计完成时间
    - delivery: 最后一道工序的交付安排（按日期×订单堆积）
    """
    from collections import defaultdict

    async with async_session() as session:
        # 查询所有 PSO（工序计划单）
        pso_result = await session.execute(
            select(ORMProcessScheduleOrder).order_by(
                ORMProcessScheduleOrder.demand_id, ORMProcessScheduleOrder.seq
            )
        )
        psos = pso_result.scalars().all()

        # 缓存关联数据
        demand_ids = {pso.demand_id for pso in psos if pso.demand_id}
        product_ids = {pso.product_id for pso in psos if pso.product_id}
        process_ids = {pso.process_id for pso in psos if pso.process_id}
        pso_ids = {pso.id for pso in psos}

        # 批量查询关联数据
        dp_map = {}
        if demand_ids:
            dp_result = await session.execute(
                select(ORMDemandPlan).where(ORMDemandPlan.id.in_(demand_ids))
            )
            for dp in dp_result.scalars().all():
                dp_map[dp.id] = dp

        prod_map = {}
        if product_ids:
            prod_result = await session.execute(
                select(ORMProduct).where(ORMProduct.id.in_(product_ids))
            )
            for p in prod_result.scalars().all():
                prod_map[p.id] = p

        proc_map = {}
        if process_ids:
            proc_result = await session.execute(
                select(ORMProcessInfo).where(ORMProcessInfo.id.in_(process_ids))
            )
            for p in proc_result.scalars().all():
                proc_map[p.id] = p

        # 查询每个PSO关联的SR，获取预计完成日期（MAX(sr_date)）和交付数据
        sr_map = defaultdict(list)  # pso_id -> [sr, ...]
        if pso_ids:
            sr_result = await session.execute(
                select(ORMScheduleResult).where(
                    ORMScheduleResult.pso_id.in_(pso_ids),
                    ORMScheduleResult.sr_status.in_(["已排产", "待确认", "待生产", "报工中", "已完成", "已锁定"]),
                )
            )
            for sr in sr_result.scalars().all():
                if sr.pso_id:
                    sr_map[sr.pso_id].append(sr)

        # 按订单分组，找最后一道工序
        order_processes = defaultdict(list)  # demand_id -> [pso, ...]
        for pso in psos:
            order_processes[pso.demand_id].append(pso)

        # 构建订单进展列表
        orders = []
        # 构建交付计划：最后一道工序的SR按日期×订单汇总
        delivery_raw = defaultdict(lambda: defaultdict(int))  # date_str -> dp_code -> qty

        for demand_id, group_psos in order_processes.items():
            dp = dp_map.get(demand_id)
            dp_code = dp.dp_code if dp else "?"
            prod = prod_map.get(group_psos[0].product_id) if group_psos[0].product_id else None
            prod_name = prod.prod_name if prod else "?"
            dp_qty = dp.quantity if dp else 0

            # 找最后一道工序（seq最大）
            sorted_psos = sorted(group_psos, key=lambda x: x.seq or 0)
            last_pso = sorted_psos[-1] if sorted_psos else None

            for pso in sorted_psos:
                proc = proc_map.get(pso.process_id) if pso.process_id else None
                proc_name = proc.proc_name if proc else "?"
                planned = pso.planned_qty or 0
                completed = pso.pso_completed_qty or 0
                unfinished = pso.pso_unfinished_qty or 0
                progress = round(completed / planned * 100, 1) if planned > 0 else 0.0

                # 预计完成时间 = MAX(SR.sr_date)
                pso_srs = sr_map.get(pso.id, [])
                expected_date = max((sr.sr_date for sr in pso_srs if sr.sr_date), default=None)
                expected_date_str = expected_date.isoformat() if expected_date else None

                orders.append({
                    "demand_id": demand_id,
                    "dp_code": dp_code,
                    "product_name": prod_name,
                    "demand_qty": dp_qty,
                    "seq": pso.seq or 0,
                    "process_name": proc_name,
                    "planned_qty": planned,
                    "completed_qty": completed,
                    "unfinished_qty": unfinished,
                    "progress": progress,
                    "expected_complete_date": expected_date_str,
                    "status": pso.pso_status or "?",
                    "is_last_process": pso.id == last_pso.id if last_pso else False,
                })

            # 交付计划：最后一道工序的SR按日期汇总 + 待排产部分
            if last_pso:
                last_srs = sr_map.get(last_pso.id, [])
                scheduled_qty = 0
                for sr in last_srs:
                    if sr.sr_date and sr.sr_quantity:
                        date_str = sr.sr_date.isoformat() if hasattr(sr.sr_date, 'isoformat') else str(sr.sr_date)
                        delivery_raw[date_str][dp_code] += int(sr.sr_quantity)
                        scheduled_qty += int(sr.sr_quantity)
                # 待排产部分：计划数量 - 已排产数量
                unscheduled = (last_pso.planned_qty or 0) - scheduled_qty
                if unscheduled > 0:
                    delivery_raw["待排产"][dp_code] += unscheduled

        # 构建交付图表数据（echarts格式）
        all_dates = sorted(delivery_raw.keys())
        all_dp_codes = sorted({dp_code for date_data in delivery_raw.values() for dp_code in date_data})
        delivery_series = []
        for dp_code in all_dp_codes:
            series_data = [delivery_raw[d].get(dp_code, 0) for d in all_dates]
            delivery_series.append({"name": dp_code, "data": series_data})

        return {
            "orders": orders,
            "delivery": {
                "dates": all_dates,
                "series": delivery_series,
            },
        }


@router.post("/daily-reset", summary="每日重置")
async def daily_reset(
    sim_date: Optional[str] = None,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """每日重置：处理所有"待生产"排产结果，为重新排产做准备。

    - 已报工的SR（sr_completed_qty > 0）→ 锁定为"已锁定"，保留历史记录和对应RWO
    - 未报工的SR（sr_completed_qty = 0）→ 物理删除，对应的"待报工"RWO 也物理删除

    重新排产时通过 DemandPlan.completed_qty 正确扣除已报工数量。

    Args:
        sim_date: 仿真日期（保留参数用于日志记录，不影响处理范围）。
    """
    today = date.fromisoformat(sim_date) if sim_date else date.today()

    async with async_session() as session:
        # 查找所有未报工的排产结果（"待生产"和"待确认"状态，已锁定的保留）
        stmt = select(ORMScheduleResult).where(
            ORMScheduleResult.sr_status.in_(["待生产", "待确认"]),
        )
        result = await session.execute(stmt)
        expired_results = result.scalars().all()

        locked_count = 0
        deleted_sr_count = 0
        deleted_rwo_count = 0

        # 收集需要物理删除的 SR ID 和 RWO ID
        sr_ids_to_delete: list[str] = []
        rwo_ids_to_delete: list[str] = []

        for sr in expired_results:
            sr.sr_unfinished_qty = (sr.sr_quantity or 0) - (sr.sr_completed_qty or 0)

            if (sr.sr_completed_qty or 0) > 0:
                # 已报工的SR → 锁定保留（作为历史记录）
                sr.sr_status = "已锁定"
                sr.sync_status = SyncStatus.PENDING_UPDATE
                locked_count += 1
            else:
                # 未报工的SR → 收集待物理删除
                sr_ids_to_delete.append(sr.id)
                deleted_sr_count += 1

        # 查询未报工SR对应的"待报工"RWO，准备物理删除
        if sr_ids_to_delete:
            rwo_stmt = select(ORMReportWorkOrder).where(
                and_(
                    ORMReportWorkOrder.dispatch_id.in_(sr_ids_to_delete),
                    ORMReportWorkOrder.rw_status == "待报工",
                )
            )
            rwo_result = await session.execute(rwo_stmt)
            for rwo in rwo_result.scalars().all():
                rwo_ids_to_delete.append(rwo.id)
            deleted_rwo_count = len(rwo_ids_to_delete)

        # 物理删除：先删 RWO（外键引用 SR），再删 SR
        if rwo_ids_to_delete:
            await session.execute(
                delete(ORMReportWorkOrder).where(ORMReportWorkOrder.id.in_(rwo_ids_to_delete))
            )
        if sr_ids_to_delete:
            await session.execute(
                delete(ORMScheduleResult).where(ORMScheduleResult.id.in_(sr_ids_to_delete))
            )

        # V3.9.3 修复：删除SR后，重新计算所有PSO的pso_quantity = SUM(剩余SR.sr_quantity)
        # 避免pso_quantity累加超过planned_qty，导致排产引擎认为已排够
        pso_recalc_result = await session.execute(
            select(ORMProcessScheduleOrder).where(
                ORMProcessScheduleOrder.pso_status.in_(["已排产", "待生产", "待确认", "报工中"])
            )
        )
        all_active_psos = pso_recalc_result.scalars().all()
        recalc_count = 0
        for pso in all_active_psos:
            sum_result = await session.execute(
                select(func.sum(ORMScheduleResult.sr_quantity))
                .where(ORMScheduleResult.pso_id == pso.id)
            )
            new_qty = int(sum_result.scalar() or 0)
            old_qty = pso.pso_quantity or 0
            if new_qty != old_qty:
                pso.pso_quantity = new_qty
                pso.pso_unfinished_qty = max(0, (pso.planned_qty or 0) - (pso.pso_completed_qty or 0))
                pso.sync_status = SyncStatus.PENDING_UPDATE
                recalc_count += 1
        if recalc_count > 0:
            logger.info("日终重置: 重新计算 {} 条PSO的pso_quantity", recalc_count)

        # 清理未报工的 PSO（pso_completed_qty=0 且 pso_quantity=0），避免残留数据
        pso_delete_result = await session.execute(
            delete(ORMProcessScheduleOrder).where(
                and_(
                    ORMProcessScheduleOrder.pso_completed_qty == 0,
                    ORMProcessScheduleOrder.pso_quantity == 0,
                )
            )
        )
        deleted_pso_count = pso_delete_result.rowcount or 0

        # 已报工SR对应的"待报工"RWO（理论上不存在，保险起见关闭）
        locked_sr_ids = [sr.id for sr in expired_results if (sr.sr_completed_qty or 0) > 0]
        closed_report_count = 0
        if locked_sr_ids:
            rwo_close_stmt = select(ORMReportWorkOrder).where(
                and_(
                    ORMReportWorkOrder.dispatch_id.in_(locked_sr_ids),
                    ORMReportWorkOrder.rw_status == "待报工",
                )
            )
            rwo_close_result = await session.execute(rwo_close_stmt)
            for rwo in rwo_close_result.scalars().all():
                rwo.rw_status = "已关闭"
                rwo.sync_status = SyncStatus.PENDING_UPDATE
                closed_report_count += 1

        await session.commit()

    logger.info(
        "每日重置: 锁定{}条SR, 删除{}条SR, 删除{}条RWO, 删除{}条PSO, 关闭{}条RWO",
        locked_count, deleted_sr_count, deleted_rwo_count, deleted_pso_count, closed_report_count,
    )
    return {
        "locked_count": locked_count,
        "deleted_sr_count": deleted_sr_count,
        "deleted_rwo_count": deleted_rwo_count,
        "deleted_pso_count": deleted_pso_count,
        "closed_report_count": closed_report_count,
    }


@router.post("/{dispatch_id}", summary="报工")
async def report_work(
    dispatch_id: str,
    req: ReportWorkRequest,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """对单个派工单进行报工。"""
    # M5修复: 统一错误处理，业务校验异常按原状态码抛出，其他异常返回统一格式
    try:
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

            # V3.9.3 在制品流转约束：报工数量 ≤ 前置工序完成数量 - 本工序已报工数量
            # 本工序已报工数量统一从 PSO 维度取（与前置工序口径一致）
            if sr.pso_id:
                pso = await session.get(ORMProcessScheduleOrder, sr.pso_id)
                current_completed = (pso.pso_completed_qty or 0) if pso else (sr.sr_completed_qty or 0)
                if pso and pso.prev_pso_id:
                    prev_pso = await session.get(ORMProcessScheduleOrder, pso.prev_pso_id)
                    prev_completed = (prev_pso.pso_completed_qty or 0) if prev_pso else 0
                    available_qty = max(0, prev_completed - current_completed)
                    if req.rw_actual_qty > available_qty:
                        raise HTTPException(
                            status_code=400,
                            detail=f"报工数量 {req.rw_actual_qty} 超过可报工数量 {available_qty}（前置工序完成 {prev_completed} - 本工序已报工 {current_completed}）",
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

            # 6. 更新工序计划单
            if sr.pso_id:
                pso = await session.get(ORMProcessScheduleOrder, sr.pso_id)
                if pso:
                    # V3.5修复: pso_completed_qty 改为 SUM(SR.sr_completed_qty)
                    sum_sr_result = await session.execute(
                        select(func.sum(ORMScheduleResult.sr_completed_qty))
                        .where(ORMScheduleResult.pso_id == sr.pso_id)
                    )
                    total_sr_completed = sum_sr_result.scalar() or 0
                    pso.pso_completed_qty = int(total_sr_completed)
                    # V3.9.3: 未完成数量 = 计划数量 - 已完成数量（基于需求数量，非排产数量）
                    pso.pso_unfinished_qty = max(0, (pso.planned_qty or 0) - pso.pso_completed_qty)
                    # 已完成 = 已完成数量 >= 计划数量
                    if pso.pso_completed_qty >= (pso.planned_qty or 0) and (pso.planned_qty or 0) > 0:
                        pso.pso_status = "已完成"
                    elif pso.pso_completed_qty > 0:
                        pso.pso_status = "报工中"
                    pso.sync_status = SyncStatus.PENDING_UPDATE

            # V3.8: 更新工序交付计划（PDP）- 持久化的工序级别完成数量
            if sr.pdp_id:
                pdp = await session.get(ORMProcessDeliveryPlan, sr.pdp_id)
                if pdp:
                    # PDP.completed_qty = SUM(关联的 SR.sr_completed_qty)
                    sum_pdp_sr_result = await session.execute(
                        select(func.sum(ORMScheduleResult.sr_completed_qty))
                        .where(ORMScheduleResult.pdp_id == sr.pdp_id)
                    )
                    total_pdp_completed = sum_pdp_sr_result.scalar() or 0
                    pdp.completed_qty = int(total_pdp_completed)
                    pdp.unfinished_qty = max(0, (pdp.planned_qty or 0) - pdp.completed_qty)
                    # 当 completed_qty >= planned_qty，更新状态和完成时间
                    if pdp.completed_qty >= (pdp.planned_qty or 0) and pdp.planned_qty > 0:
                        pdp.pdp_status = "已完成"
                        if not pdp.planned_finish_time:
                            pdp.planned_finish_time = date.today()
                    elif pdp.completed_qty > 0:
                        pdp.pdp_status = "排产中"
                    pdp.sync_status = SyncStatus.PENDING_UPDATE

                    # V3.8: 最后一道工序完成时，反馈到 demand_plans.completed_qty
                    # 最后一道工序 = 该 demand_id 下 seq 最大的 PDP
                    if sr.demand_id:
                        max_seq_result = await session.execute(
                            select(func.max(ORMProcessDeliveryPlan.seq))
                            .where(ORMProcessDeliveryPlan.demand_id == sr.demand_id)
                        )
                        max_seq = max_seq_result.scalar() or 0
                        if pdp.seq == max_seq:
                            # 当前工序是最后一道，更新 demand_plans.completed_qty
                            dp = await session.get(ORMDemandPlan, sr.demand_id)
                            if dp:
                                dp.completed_qty = pdp.completed_qty
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
    except HTTPException:
        raise  # 业务校验异常，按原状态码抛出
    except Exception as e:
        logger.error("报工操作异常: dispatch_id={}, error={}", dispatch_id, str(e))
        return {"success": False, "error": str(e)}
