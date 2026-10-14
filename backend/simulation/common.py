"""仿真共享工具：API客户端、数据收集器、配置常量。"""
from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from typing import Any

import httpx

sys.stdout.reconfigure(line_buffering=True)

# ── 配置常量 ────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8001/api/v1"
API_KEY = "aps-hap-local-2026"
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
SIM_START_DATE = date(2026, 7, 16)
SCHEDULE_HORIZON = 25


# ── HTTP 工具 ────────────────────────────────────────────────────────


async def api_call(method: str, path: str, json_data=None, params=None) -> dict:
    async with httpx.AsyncClient(headers=HEADERS, timeout=180, follow_redirects=True) as client:
        url = f"{BASE_URL}{path}"
        if method == "GET":
            r = await client.get(url, params=params)
        elif method == "POST":
            r = await client.post(url, json=json_data, params=params)
        elif method == "DELETE":
            r = await client.delete(url, params=params)
        else:
            raise ValueError(f"Unsupported method: {method}")
        if r.status_code >= 400:
            print(f"  API错误: {method} {path} -> {r.status_code}: {r.text[:300]}")
        r.raise_for_status()
        return r.json()


# ── 业务数据查询 ─────────────────────────────────────────────────────


async def get_products() -> list[dict]:
    data = await api_call("GET", "/products/", params={"limit": 1000})
    return data.get("items", [])


async def get_processes() -> list[dict]:
    data = await api_call("GET", "/process-info/", params={"limit": 1000})
    return data.get("items", [])


async def get_product_processes() -> list[dict]:
    data = await api_call("GET", "/product-processes/", params={"limit": 1000})
    return data.get("items", [])


async def get_demand_plans() -> list[dict]:
    data = await api_call("GET", "/demand-plans/", params={"limit": 1000})
    return data.get("items", [])


async def delete_demand_plan(dp_id: str) -> dict:
    return await api_call("DELETE", f"/demand-plans/{dp_id}")


async def create_demand_plan(payload: dict) -> dict:
    return await api_call("POST", "/demand-plans/", json_data=payload)


async def get_all_process_schedule_orders() -> list[dict]:
    all_items: list[dict] = []
    skip = 0
    while True:
        data = await api_call("GET", "/process-schedule-orders/", params={"skip": skip, "limit": 1000})
        items = data.get("items", [])
        all_items.extend(items)
        if len(items) < 1000:
            break
        skip += 1000
    return all_items


async def get_report_work_orders(status: str | None = None) -> list[dict]:
    params = {}
    if status:
        params["status"] = status
    data = await api_call("GET", "/report-work/", params=params)
    return data.get("items", [])


async def create_schedule(
    start_date: str,
    end_date: str,
    scheduling_mode: str = "capacity",
) -> str:
    """创建排产任务。

    Args:
        start_date: 排产开始日期 (YYYY-MM-DD)
        end_date: 排产结束日期 (YYYY-MM-DD)
        scheduling_mode: 求解模式 ("capacity" 或 "time_exclusive")
            - capacity: 产能累加模式，多任务共享时间槽（日级粒度）
            - time_exclusive: 时间独占模式，任务占用连续时间区间（小时级粒度）
    """
    payload = {
        "start_time": start_date,
        "end_time": end_date,
        "solver_type": "ortools",
        "solver_params": {"scheduling_mode": scheduling_mode},
    }
    result = await api_call("POST", "/schedule/create", json_data=payload)
    return result.get("task_id", "")


async def wait_for_schedule(task_id: str, max_wait: int = 180) -> dict:
    for _ in range(max_wait // 3):
        status = await api_call("GET", f"/schedule/{task_id}/status")
        if status.get("status") in ("SUCCESS", "FAILURE", "CANCELLED"):
            return status
        await asyncio.sleep(3)
    return {"status": "TIMEOUT"}


async def confirm_schedule(task_id: str) -> dict:
    return await api_call("POST", f"/result/{task_id}/confirm")


async def report_work(dispatch_id: str, actual_qty: int) -> dict:
    return await api_call("POST", f"/report-work/{dispatch_id}", json_data={
        "rw_actual_qty": actual_qty,
        "rw_defect_qty": 0,
        "rw_remark": "",
    })


async def daily_reset(sim_date: str) -> dict:
    return await api_call("POST", f"/report-work/daily-reset?sim_date={sim_date}")


# ── DB直接操作（日清清理、同步重置）────────────────────────────────


async def daily_cleanup() -> dict:
    from app.database import async_session
    from app.models.entities import ScheduleResult, ReportWorkOrder, ProcessScheduleOrder
    from sqlalchemy import delete, select

    async with async_session() as session:
        expired_sr = (await session.execute(
            select(ScheduleResult).where(ScheduleResult.sr_status == "已失效")
        )).scalars().all()
        expired_sr_ids = [sr.id for sr in expired_sr]

        closed_rwo = (await session.execute(
            select(ReportWorkOrder).where(
                (ReportWorkOrder.rw_status == "已关闭") |
                (ReportWorkOrder.dispatch_id.in_(expired_sr_ids) if expired_sr_ids else False)
            )
        )).scalars().all()

        expired_pso = (await session.execute(
            select(ProcessScheduleOrder).where(ProcessScheduleOrder.pso_status == "已失效")
        )).scalars().all()

        rwo_count = len(closed_rwo)
        sr_count = len(expired_sr)
        pso_count = len(expired_pso)

        if closed_rwo:
            rwo_ids = [rwo.id for rwo in closed_rwo]
            await session.execute(delete(ReportWorkOrder).where(ReportWorkOrder.id.in_(rwo_ids)))
        if expired_sr:
            await session.execute(delete(ScheduleResult).where(ScheduleResult.id.in_(expired_sr_ids)))
        if expired_pso:
            pso_ids = [pso.id for pso in expired_pso]
            await session.execute(delete(ProcessScheduleOrder).where(ProcessScheduleOrder.id.in_(pso_ids)))

        await session.commit()

    return {"expired_sr": sr_count, "closed_rwo": rwo_count, "expired_pso": pso_count}


async def reset_all_sync_status() -> None:
    from app.database import async_session
    from app.models.entities import ScheduleResult, ProcessScheduleOrder, DemandPlan, ReportWorkOrder
    from app.models.base import SyncStatus
    from sqlalchemy import update

    async with async_session() as session:
        await session.execute(
            update(ScheduleResult)
            .where(ScheduleResult.sync_status != SyncStatus.PENDING_DELETE)
            .values(sync_status=SyncStatus.SYNCED)
        )
        await session.execute(
            update(ProcessScheduleOrder)
            .where(ProcessScheduleOrder.sync_status != SyncStatus.PENDING_DELETE)
            .values(sync_status=SyncStatus.SYNCED)
        )
        await session.execute(
            update(DemandPlan)
            .where(DemandPlan.sync_status != SyncStatus.PENDING_DELETE)
            .values(sync_status=SyncStatus.SYNCED)
        )
        await session.execute(
            update(ReportWorkOrder)
            .where(ReportWorkOrder.sync_status != SyncStatus.PENDING_DELETE)
            .values(sync_status=SyncStatus.SYNCED)
        )
        await session.commit()


async def cleanup_all_schedule_data() -> None:
    """清理所有排产相关数据，物理删除所有需求计划。

    注意：直接物理删除所有 demand_plans 记录（包括软删除的 PENDING_DELETE），
    避免 reset_all_sync_status() 之后软删除记录"复活"。
    """
    from app.database import async_session
    from app.models.entities import (
        ScheduleResult, ReportWorkOrder, DemandPlan, SchedulePlan, ProcessScheduleOrder,
        MaterialKitting,
    )
    from sqlalchemy import delete

    async with async_session() as session:
        await session.execute(delete(ReportWorkOrder))
        await session.execute(delete(ScheduleResult))
        await session.execute(delete(ProcessScheduleOrder))
        await session.execute(delete(SchedulePlan))
        await session.execute(delete(MaterialKitting))  # 先删物料齐套（外键引用demand_plans）
        await session.execute(delete(DemandPlan))  # 物理删除所有需求
        await session.commit()


async def cleanup_schedule_artifacts() -> None:
    """清理排产产物（SR/PSO/SchedulePlan/RWO），保留需求计划和主数据。

    V3.2新增：用于 run_simulation 开头清理上次仿真残留的排产结果，
    避免 snapshot_day 读取到多 plan_id 叠加数据造成"超产"假象。

    与 cleanup_all_schedule_data() 的区别：
    - 保留 DemandPlan（由 generate_demands 管理）
    - 保留 MaterialKitting（与 DemandPlan 关联）
    - 仅清理 ScheduleResult/ProcessScheduleOrder/SchedulePlan/ReportWorkOrder
    """
    from app.database import async_session
    from app.models.entities import (
        ScheduleResult, ReportWorkOrder, SchedulePlan, ProcessScheduleOrder,
    )
    from sqlalchemy import delete

    async with async_session() as session:
        await session.execute(delete(ReportWorkOrder))
        await session.execute(delete(ScheduleResult))
        await session.execute(delete(ProcessScheduleOrder))
        await session.execute(delete(SchedulePlan))
        await session.commit()


async def cleanup_schedule_results() -> None:
    """清理排产结果（SR/RWO），保留 PSO 和需求计划。

    用于 run_simulation 每天排产前清理旧的排产结果，避免多天 SR 叠加。
    保留 PSO 是因为 pso_completed_qty 记录了历史报工数据，
    删除 PSO 会导致 completed_qty 计算丢失历史数据。
    """
    from app.database import async_session
    from app.models.entities import ScheduleResult, ReportWorkOrder
    from sqlalchemy import delete

    async with async_session() as session:
        await session.execute(delete(ReportWorkOrder))
        await session.execute(delete(ScheduleResult))
        await session.commit()


async def hard_delete_all_demands() -> None:
    """物理删除所有需求计划及关联数据（保留产品/工序/产线等主数据）。

    用于测试前彻底清理，避免软删除记录残留。
    """
    await cleanup_all_schedule_data()


# ── 数据收集器 ───────────────────────────────────────────────────────


class SimDataCollector:
    """仿真数据收集器：在每天日清前快照当天数据。"""

    def __init__(
        self,
        products: list[dict],
        processes: list[dict],
        product_processes: list[dict],
    ) -> None:
        self.products_map = {p["id"]: p for p in products}
        self.processes_map = {p["id"]: p for p in processes}
        self.product_processes = product_processes

        # (product_id, process_id) -> seq / dependency_type / 三时间参数 查找映射
        # PSO/RWO 不一定带 seq 字段，需从 product_processes 查
        # V3.2: 增加 cycle_time/prep_time/wait_time 等参数捕获，供甘特图显示与核对
        self._pp_seq_map: dict[tuple[str, str], int] = {}
        self._pp_dep_map: dict[tuple[str, str], str] = {}
        self._pp_params_map: dict[tuple[str, str], dict] = {}
        for pp in product_processes:
            key = (pp["product_id"], pp["process_id"])
            self._pp_seq_map[key] = pp.get("seq", 0) or 0
            self._pp_dep_map[key] = pp.get("dependency_type", "FS") or "FS"
            self._pp_params_map[key] = {
                "cycle_time": pp.get("cycle_time", 0) or 0,
                "prep_time": pp.get("prep_time", 0) or 0,
                "wait_time": pp.get("wait_time", 0) or 0,
                "wait_includes_offhours": pp.get("wait_includes_offhours", False) or False,
                "auto_type": pp.get("auto_type", "非自动") or "非自动",
                "max_units_per_beat": pp.get("max_units_per_beat", 1) or 1,
            }

        # 识别并行工序：相同 (product_id, seq) 有多个 process_id
        parallel_keys: dict[tuple[str, int], list[str]] = {}
        for pp in product_processes:
            key = (pp["product_id"], pp["seq"])
            parallel_keys.setdefault(key, []).append(pp["process_id"])
        self.parallel_process_ids: set[str] = set()
        for proc_ids in parallel_keys.values():
            if len(proc_ids) > 1:
                self.parallel_process_ids.update(proc_ids)

        self.daily_process_data: dict[str, dict[str, dict[str, int]]] = {}
        self.daily_summary: dict[str, dict[str, int]] = {}
        self.gantt_data: dict[str, dict[str, Any]] = {}
        self.daily_demand_progress: dict[str, list[dict]] = {}
        self.dates: list[str] = []
        # dispatch_id -> demand_id 持久映射（SR可能被日清删除，保留映射供RWO查找）
        self._dispatch_demand_map: dict[str, str] = {}
        # demand_id -> 需求总量（quantity字段，原始需求量）
        self._demand_qty_map: dict[str, int] = {}
        # demand_id -> dp_code 映射（RWO/PSO 不带 dp_code，需从需求计划查）
        self._demand_dp_code_map: dict[str, str] = {}

    def _init_gantt_entry(self, demand_id: str, proc_id: str, source: dict) -> None:
        """初始化甘特图数据条目（需求+工序维度）。"""
        if demand_id not in self.gantt_data:
            product_id = source.get("product_id", "")
            product = self.products_map.get(product_id, {})
            # dp_code 优先从 demand_plans 映射查（RWO/PSO 不一定带）
            dp_code = self._demand_dp_code_map.get(demand_id, "") or source.get("dp_code", "") or source.get("pso_code", "")
            self.gantt_data[demand_id] = {
                "dp_code": dp_code,
                "product_id": product_id,
                "product_name": product.get("prod_name", ""),
                "product_code": product.get("prod_code", ""),
                "processes": {},
            }
        processes = self.gantt_data[demand_id]["processes"]
        if proc_id not in processes:
            product_id = self.gantt_data[demand_id]["product_id"]
            pp_key = (product_id, proc_id)
            # seq 和 dependency_type 从 product_processes 查（PSO/RWO 不一定带）
            seq = self._pp_seq_map.get(pp_key, source.get("seq", 0) or 0)
            dep_type = self._pp_dep_map.get(pp_key, source.get("dependency_type", "FS") or "FS")
            # V3.2: 三时间参数从 product_processes 查，供甘特图核对
            pp_params = self._pp_params_map.get(pp_key, {})
            proc = self.processes_map.get(proc_id, {})
            processes[proc_id] = {
                "process_id": proc_id,  # 供前端 JS 回退显示
                "process_name": proc.get("proc_name", ""),
                "process_code": proc.get("proc_code", ""),
                "seq": seq,
                "dependency_type": dep_type,
                "cycle_time": pp_params.get("cycle_time", 0),
                "prep_time": pp_params.get("prep_time", 0),
                "wait_time": pp_params.get("wait_time", 0),
                "wait_includes_offhours": pp_params.get("wait_includes_offhours", False),
                "auto_type": pp_params.get("auto_type", "非自动"),
                "max_units_per_beat": pp_params.get("max_units_per_beat", 1),
                "line_id": source.get("line_id", ""),
                "plan_qty": 0,
                "actual_qty": 0,
                "first_plan_date": None,
                "last_plan_date": None,
                "is_parallel": proc_id in self.parallel_process_ids,
                "_pso_ids": set(),  # 内部字段：已处理的pso_id集合
                "_rwo_ids": set(),  # 内部字段：已处理的rwo_id集合
            }

    async def snapshot_day(self, sim_date_str: str) -> None:
        """在每天报工完成后、日清前调用：快照当天数据。

        数据来源说明：
        - plan_qty: 取自 demand_plan.quantity（需求总量，每道工序相同）
        - actual_qty: 从报工单 rw_actual_qty 累加（用rwo_id去重，通过SR映射到demand_id）
        - 日期范围: 从工序排产单 pso_date 聚合
        """
        self.dates.append(sim_date_str)

        # 1. 获取需求计划（用于plan_qty和进度快照）
        demands = await get_demand_plans()
        for dp in demands:
            dp_id = dp["id"]
            # quantity 是原始需求总量（不会随报工变化）
            self._demand_qty_map[dp_id] = dp.get("quantity", 0) or 0
            # dp_code 映射（RWO/PSO 不一定带 dp_code，需从需求计划查）
            if dp.get("dp_code"):
                self._demand_dp_code_map[dp_id] = dp["dp_code"]

        # 2. 获取所有排产结果，更新 dispatch_id -> demand_id 映射
        # （SR可能被日清删除，但映射保留以供后续RWO查找）
        from app.database import async_session
        from app.models.entities import ScheduleResult as ORMSR
        from sqlalchemy import select
        async with async_session() as session:
            sr_result = await session.execute(select(ORMSR))
            for sr in sr_result.scalars().all():
                if sr.demand_id:
                    self._dispatch_demand_map[sr.id] = sr.demand_id

        # 3. 从报工单聚合当天数据 + 累积甘特图 actual_qty
        rwos = await get_report_work_orders()
        day_process: dict[str, dict[str, int]] = {}
        day_total_plan = 0
        day_total_actual = 0
        for rwo in rwos:
            rw_date = rwo.get("rw_date", "")
            proc_id = rwo.get("process_id", "")
            dispatch_id = rwo.get("dispatch_id", "")
            rwo_id = rwo.get("id", "")
            actual_qty = rwo.get("rw_actual_qty", 0) or 0
            plan_qty = rwo.get("rw_plan_qty", 0) or 0

            # 当天数据聚合（用于每日曲线图）
            if rw_date and rw_date[:10] == sim_date_str and proc_id:
                if proc_id not in day_process:
                    day_process[proc_id] = {"plan": 0, "actual": 0}
                day_process[proc_id]["plan"] += plan_qty
                day_process[proc_id]["actual"] += actual_qty
                day_total_plan += plan_qty
                day_total_actual += actual_qty

            # 累积甘特图 actual_qty（用 rwo_id 去重，跨天累加）
            demand_id = self._dispatch_demand_map.get(dispatch_id, "")
            if demand_id and proc_id and rwo_id:
                self._init_gantt_entry(demand_id, proc_id, rwo)
                item = self.gantt_data[demand_id]["processes"][proc_id]
                if rwo_id not in item["_rwo_ids"]:
                    item["_rwo_ids"].add(rwo_id)
                    item["actual_qty"] += actual_qty

        self.daily_process_data[sim_date_str] = day_process
        self.daily_summary[sim_date_str] = {
            "total_plan": day_total_plan,
            "total_actual": day_total_actual,
        }

        # 4. 从工序排产单更新甘特图日期范围和 plan_qty
        # （plan_qty 使用 demand_plan.quantity，不用 pso_quantity，因为后者是日级计划量）
        psos = await get_all_process_schedule_orders()
        for pso in psos:
            pso_id = pso.get("id", "")
            demand_id = pso.get("demand_id", "")
            proc_id = pso.get("process_id", "")
            if not demand_id or not proc_id or not pso_id:
                continue

            self._init_gantt_entry(demand_id, proc_id, pso)
            item = self.gantt_data[demand_id]["processes"][proc_id]

            # 更新日期范围（每次都更新，因为pso_date可能扩展范围）
            pso_date = pso.get("pso_date", "")
            if pso_date:
                pso_date_str = pso_date[:10] if isinstance(pso_date, str) else str(pso_date)[:10]
                if item["first_plan_date"] is None or pso_date_str < item["first_plan_date"]:
                    item["first_plan_date"] = pso_date_str
                if item["last_plan_date"] is None or pso_date_str > item["last_plan_date"]:
                    item["last_plan_date"] = pso_date_str

            # plan_qty: 使用需求总量（同一需求的所有工序plan相同）
            if demand_id in self._demand_qty_map:
                item["plan_qty"] = self._demand_qty_map[demand_id]

        # 5. 需求进度快照
        progress_list = []
        for dp in demands:
            product = self.products_map.get(dp.get("product_id", ""), {})
            progress_list.append({
                "dp_code": dp.get("dp_code", ""),
                "product_name": product.get("prod_name", ""),
                "total": dp.get("quantity", 0) or 0,
                "completed": dp.get("completed_qty", 0) or 0,
            })
        self.daily_demand_progress[sim_date_str] = progress_list

    def export_to_dict(self, config: dict) -> dict:
        """导出为可序列化的字典。"""
        return {
            "config": config,
            "dates": self.dates,
            "processes": [
                {"id": pid, "name": p.get("proc_name", ""), "code": p.get("proc_code", "")}
                for pid, p in self.processes_map.items()
            ],
            "products": [
                {"id": pid, "name": p.get("prod_name", ""), "code": p.get("prod_code", "")}
                for pid, p in self.products_map.items()
            ],
            "daily_process_data": self.daily_process_data,
            "daily_summary": self.daily_summary,
            "gantt_data": self._clean_gantt_data_for_export(),
            "daily_demand_progress": self.daily_demand_progress,
        }

    def _clean_gantt_data_for_export(self) -> dict:
        """导出前清理gantt_data中的内部字段（如_pso_ids），避免JSON序列化失败。

        同时将 actual_qty 上限截断为 plan_qty：
        中间工序在多日排产中可能被重复调度，导致累计报工数超过需求总量，
        但甘特图"实际完成比例"不应超过100%，故按 plan_qty 截断显示。
        """
        cleaned = {}
        for demand_id, gd in self.gantt_data.items():
            clean_gd = {k: v for k, v in gd.items() if k != "processes"}
            clean_processes = {}
            for proc_id, proc in gd.get("processes", {}).items():
                clean_proc = {k: v for k, v in proc.items() if not k.startswith("_")}
                # 截断 actual_qty 不超过 plan_qty（避免中间工序过度累计导致显示异常）
                plan_qty = clean_proc.get("plan_qty", 0) or 0
                if plan_qty > 0 and clean_proc.get("actual_qty", 0) > plan_qty:
                    clean_proc["actual_qty"] = plan_qty
                clean_processes[proc_id] = clean_proc
            clean_gd["processes"] = clean_processes
            cleaned[demand_id] = clean_gd
        return cleaned