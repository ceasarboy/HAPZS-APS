"""排产业务逻辑服务，负责任务的创建、数据拉取、求解、结果推送等操作。

V3: 数据读取从 HAP API 切换到本地 PostgreSQL，结果写入本地 DB 后触发同步。
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Any

from loguru import logger
from fastapi import HTTPException
from sqlalchemy import select, delete, update, func, text
from sqlalchemy.ext.asyncio import AsyncSession
from collections import defaultdict

from app.database import async_session
from app.engine.models import (
    Buffer,
    BufferType,
    ChangeoverMatrix,
    DemandPlan,
    HardRule,
    LineProcessConfig,
    MaterialKitting,
    MaterialMaster,
    OrderItem,
    OrderItemStatus,
    OrderPriority,
    ProcessBOM,
    ProcessInfo,
    ProcessRoute,
    ProcessStep,
    Product,
    ProductProcess,
    ProductionLine,
    SchedulingProblem,
    ScheduledTask,
    SoftRule,
    SolveResult,
    TimeSlot,
    WorkCenter,
    WorkCenterStatus,
    WorkCenterType,
)
from app.engine.solver_ortools import ORToolsSolver
from app.hap.client import HAPClient
from app.models.base import SyncStatus
from app.models.entities import (
    Product as ORMProduct,
    ProcessInfo as ORMProcessInfo,
    ProductionLine as ORMProductionLine,
    ProductProcess as ORMProductProcess,
    LineProcessConfig as ORMLineProcessConfig,
    MaterialMaster as ORMMaterialMaster,
    ProcessBOM as ORMProcessBOM,
    MaterialKitting as ORMMaterialKitting,
    DemandPlan as ORMDemandPlan,
    ScheduleResult as ORMScheduleResult,
    ResourceCalendar as ORMResourceCalendar,
    ChangeoverMatrix as ORMChangeoverMatrix,
    BufferConfig as ORMBufferConfig,
    SchedulePlan as ORMSchedulePlan,
    ReportWorkOrder as ORMReportWorkOrder,
    ProcessScheduleOrder as ORMProcessScheduleOrder,
    ProcessDeliveryPlan as ORMProcessDeliveryPlan,
    WorkTimePattern as ORMWorkTimePattern,
)


# ── 工作表 ID 映射 ────────────────────────────────────────────────────────

_WORKSHEET_IDS_FILE = Path(__file__).resolve().parents[3] / "deploy" / "worksheet_ids_v2.json"


def _load_worksheet_ids() -> dict[str, str]:
    """从 deploy/worksheet_ids.json 加载工作表 ID 映射。"""
    if _WORKSHEET_IDS_FILE.exists():
        with open(_WORKSHEET_IDS_FILE, encoding="utf-8") as f:
            return json.load(f)
    logger.warning("工作表 ID 映射文件不存在: {}", _WORKSHEET_IDS_FILE)
    return {}


WORKSHEET_IDS: dict[str, str] = _load_worksheet_ids()


# ── HAP 数据转换工具（保留，其他模块可能引用）──────────────────────────────


def _opt_value(raw: Any) -> str:
    """HAP 选项字段取 value（显示值）。"""
    if isinstance(raw, list) and raw:
        return str(raw[0].get("value", ""))
    if isinstance(raw, dict):
        return str(raw.get("value", ""))
    return str(raw) if raw else ""


def _opt_key(raw: Any) -> str:
    """HAP 选项字段取 key（匹配值）。"""
    if isinstance(raw, list) and raw:
        return str(raw[0].get("key", ""))
    if isinstance(raw, dict):
        return str(raw.get("key", ""))
    return str(raw) if raw else ""


def _relation_id(raw: Any) -> str:
    """HAP 关联字段取 rowId（sid）。"""
    # M4修复: 统一异常处理，避免非预期类型导致解析异常
    try:
        if isinstance(raw, list) and raw:
            return str(raw[0].get("sid", ""))
        if isinstance(raw, dict):
            return str(raw.get("sid", ""))
    except (AttributeError, IndexError, TypeError):
        pass
    return ""


def _relation_name(raw: Any) -> str:
    """HAP 关联字段取显示名称。"""
    # M4修复: 统一异常处理，避免非预期类型导致解析异常
    try:
        if isinstance(raw, list) and raw:
            return str(raw[0].get("name", ""))
        if isinstance(raw, dict):
            return str(raw.get("name", ""))
    except (AttributeError, IndexError, TypeError):
        pass
    return ""


def _float_val(raw: Any, default: float = 0.0) -> float:
    """HAP 数值字段转 float。"""
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _int_val(raw: Any, default: int = 0) -> int:
    """HAP 数值字段转 int。"""
    if raw is None:
        return default
    try:
        return int(float(raw))
    except (ValueError, TypeError):
        return default


def _str_val(raw: Any) -> str:
    """HAP 字符串字段取值。"""
    if isinstance(raw, dict):
        return str(raw.get("value", raw.get("key", "")))
    return str(raw) if raw else ""


def _datetime_val(raw: Any) -> datetime | None:
    """HAP 日期字段转 datetime。"""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


# ── 排产服务 ──────────────────────────────────────────────────────────────


class ScheduleService:
    """排产任务业务逻辑服务（单例，通过 FastAPI Depends 注入）。

    V3: 数据读取从本地 PostgreSQL，结果写入本地 DB 后触发 HAP 同步。
    """

    def __init__(self) -> None:
        self._hap = HAPClient()
        # 内存缓存：task_id -> 任务状态信息
        self._tasks: dict[str, dict[str, Any]] = {}
        # 排产锁：同一时间只允许一个排产任务
        self._scheduling_lock: bool = False

    # ── 数据拉取（V3: 从本地 PostgreSQL 读取）──────────────────────────────

    async def fetch_scheduling_data(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        scheduling_mode: str = "capacity",
    ) -> SchedulingProblem:
        """从本地 PostgreSQL 读取数据并构建 SchedulingProblem（V3）。

        Args:
            start_date: 排产开始日期，格式 YYYY-MM-DD
            end_date: 排产结束日期，格式 YYYY-MM-DD
            scheduling_mode: 求解模式 ("capacity" 或 "time_exclusive")
                影响时间槽粒度：capacity=日级聚合，time_exclusive=小时级保留

        Returns:
            SchedulingProblem: 求解问题实例
        """
        logger.info(
            "开始从本地 DB 读取排产数据(V3), 日期范围: {} ~ {}, 求解模式: {}",
            start_date, end_date, scheduling_mode,
        )

        # 并行读取所有表数据
        results = await asyncio.gather(
            self._fetch_products(),
            self._fetch_production_lines(),
            self._fetch_demand_plans(),
            self._fetch_time_slots(start_date, end_date, scheduling_mode),
            self._fetch_changeover_matrix(),
            self._fetch_buffers(),
            self._fetch_process_info(),
            self._fetch_product_processes(),
            self._fetch_line_process_configs(),
            self._fetch_process_bom(),
            self._fetch_material_kitting(),
        )

        products, production_lines, demand_plans, time_slots, changeover, buffers, \
            process_info, product_processes, line_process_configs, process_boms, material_kittings = results

        # 填充 demand_plan 的兼容字段
        product_map = {p.id: p for p in products}
        for dp in demand_plans:
            p = product_map.get(dp.product_id)
            if p:
                dp.product_code = p.code
                dp.product_name = p.name

        # 填充 production_line 的 compatible_products
        for line in production_lines:
            line_configs = [lpc for lpc in line_process_configs if lpc.line_id == line.id]
            line_process_ids = {lpc.process_id for lpc in line_configs}
            for pp in product_processes:
                if pp.process_id in line_process_ids:
                    if pp.product_id not in line.compatible_products:
                        line.compatible_products.append(pp.product_id)

        # 填充 demand_plan 的 compatible_workcenters 和 process_route
        for dp in demand_plans:
            dp.process_route = [pp for pp in product_processes if pp.product_id == dp.product_id]
            dp.process_route.sort(key=lambda x: x.seq)
            process_ids = {pp.process_id for pp in dp.process_route}
            for lpc in line_process_configs:
                if lpc.process_id in process_ids:
                    if lpc.line_id not in dp.compatible_workcenters:
                        dp.compatible_workcenters.append(lpc.line_id)

        problem = SchedulingProblem(
            production_lines=production_lines,
            products=products,
            demand_plans=demand_plans,
            time_slots=time_slots,
            changeover_matrix=changeover,
            buffers=buffers,
            process_info=process_info,
            product_processes=product_processes,
            line_process_configs=line_process_configs,
            process_boms=process_boms,
            material_kittings=material_kittings,
            hard_rules=[
                HardRule.FINITE_CAPACITY,
                HardRule.PROCESS_ORDER,
                HardRule.SINGLE_PRODUCT_PER_SLOT,
            ],
            soft_rules=[
                SoftRule.OTD_PRIORITY,
                SoftRule.MINIMIZE_CHANGEOVER,
                SoftRule.BALANCE_LOAD,
            ],
        )

        logger.info(
            "本地 DB 数据读取完成(V3): 产品={} 产线={} 需求计划={} 时间槽={} 换线={} 缓冲={} "
            "工序信息={} 产品工艺={} 产线工艺配置={} 工序BOM={} 物料齐套={}",
            len(products), len(production_lines), len(demand_plans),
            len(time_slots), len(changeover), len(buffers),
            len(process_info), len(product_processes), len(line_process_configs),
            len(process_boms), len(material_kittings),
        )
        return problem

    async def _fetch_products(self) -> list[Product]:
        """从本地 products 表读取产品列表。"""
        async with async_session() as session:
            result = await session.execute(select(ORMProduct))
            rows = result.scalars().all()
        products: list[Product] = []
        for r in rows:
            products.append(Product(
                id=r.id,
                code=r.prod_code or "",
                name=r.prod_name or "",
                changeover_attr=r.changeover_attr or "",
                output_rate=float(r.output_rate) if r.output_rate is not None else 1.0,
                batch_size=int(r.batch_size) if r.batch_size is not None else 1,
                processing_batch=1,
                transfer_batch=1,
                compatible_workcenters=[],
            ))
        return products

    async def _fetch_production_lines(self) -> list[ProductionLine]:
        """从本地 production_lines 表读取产线列表。"""
        async with async_session() as session:
            result = await session.execute(select(ORMProductionLine))
            rows = result.scalars().all()
        result_list: list[ProductionLine] = []
        for r in rows:
            line = ProductionLine(
                id=r.id,
                line_code=r.line_code or "",
                line_name=r.line_name or "",
                line_type=r.line_type or "主产线",
                line_load=0.0,
                location=r.location or "",
                status=r.status or "运行中",
            )
            result_list.append(line)
        return result_list

    async def _fetch_demand_plans(self) -> list[DemandPlan]:
        """从本地 demand_plans 表读取需求计划列表。

        V3.8: 工序交付计划（PDP）作为 completed_qty 的唯一数据源。
        - quantity: 排产全部数量（不减 completed_qty），由 constraint_builder 各工序独立扣减
        - seq_completed_map: 各 seq 的已完成数量（基于 PDP.completed_qty）
        - completed_qty: 需求计划级别的完成数量（仅用于显示）
        """
        async with async_session() as session:
            result = await session.execute(select(ORMDemandPlan))
            rows = result.scalars().all()
            # V3.9.3: 从工序排产单（PSO）按 demand_id+seq 汇总 pso_completed_qty
            # 不再用PDP（PDP可能因多次排产/清理产生多份，导致completed_qty不准）
            pso_rows = (await session.execute(
                select(
                    ORMProcessScheduleOrder.demand_id,
                    ORMProcessScheduleOrder.seq,
                    func.sum(ORMProcessScheduleOrder.pso_completed_qty),
                ).group_by(
                    ORMProcessScheduleOrder.demand_id,
                    ORMProcessScheduleOrder.seq,
                )
            )).all()
        # 构建 demand_id -> {seq: completed_qty} 映射
        seq_map_by_demand: dict[str, dict[int, int]] = {}
        for row in pso_rows:
            did = row[0]
            seq = row[1]
            completed = int(row[2] or 0)
            if completed > 0:
                seq_map_by_demand.setdefault(did, {})[seq] = completed

        result_list: list[DemandPlan] = []
        for r in rows:
            due_date_str = ""
            if r.due_date is not None:
                due_date_str = r.due_date.strftime("%Y-%m-%d") if isinstance(r.due_date, date) else str(r.due_date)
            raw_qty = int(r.quantity) if r.quantity is not None else 0
            completed = int(r.completed_qty) if r.completed_qty is not None else 0
            seq_completed_map = seq_map_by_demand.get(r.id, {})
            dp = DemandPlan(
                id=r.id,
                dp_code=r.dp_code or "",
                product_id=r.product_id or "",
                quantity=raw_qty,  # V3.6: 排产全部数量，各工序独立扣减
                unit=r.unit or "台",
                due_date=due_date_str,
                priority=r.priority or "中",
                status=r.status or "待排",
                remark=r.remark or "",
                scheduled_qty=completed,  # 传给排产器作为已排数量（仅显示）
                seq_completed_map=seq_completed_map,
            )
            # 只要有任一工序未完成，就需要排产
            if raw_qty > 0:
                result_list.append(dp)

        # V3.8: 结转需求逻辑已移除
        # PDP（工序交付计划）是持久化的，未完成数量直接存储在 PDP.unfinished_qty
        # 排产时通过 seq_completed_map 读取已完成数量，各工序独立扣减剩余需求
        # 不需要创建结转需求到 demand_plans 表

        return result_list

    # V3: 时间槽粒度（分钟），日级=720（12小时工作日 8:00-20:00）
    SLOT_DURATION_MINUTES = 720

    async def _fetch_work_time_patterns(self) -> dict[str, dict]:
        """从本地 work_time_patterns 表读取工作时间模式。

        Returns:
            {"weekday_normal": {...}, "weekday_overtime": {...}, "weekend": {...}}
        """
        async with async_session() as session:
            result = await session.execute(
                select(ORMWorkTimePattern).where(ORMWorkTimePattern.is_active == True)
            )
            rows = result.scalars().all()

        patterns: dict[str, dict] = {}
        for r in rows:
            day_type = r.day_type or "weekday_normal"
            work_periods = json.loads(r.work_periods) if r.work_periods else []
            break_periods = json.loads(r.break_periods) if r.break_periods else []
            patterns[day_type] = {
                "pattern_code": r.pattern_code,
                "pattern_name": r.pattern_name,
                "work_hours": r.work_hours or 8.0,
                "slot_duration": r.slot_duration_minutes or 15,
                "work_periods": work_periods,
                "break_periods": break_periods,
            }
        return patterns

    def _generate_global_time_slots(
        self, start_date: str, end_date: str,
        patterns: dict[str, dict],
    ) -> list[TimeSlot]:
        """V3.9: 基于 WorkTimePattern 生成全局15分钟时间槽。

        生成全局时间槽（不区分 line_id 和 process_id），只包含工作时段。
        - 周一到周五：weekday_normal 模式（8小时）
        - 周六周日：weekend 模式（7小时）

        时间槽粒度：15分钟（对齐11:45休息时间）
        休息时段不生成时间槽。

        Args:
            start_date: 开始日期 YYYY-MM-DD
            end_date: 结束日期 YYYY-MM-DD
            patterns: WorkTimePattern 配置字典

        Returns:
            全局时间槽列表
        """
        result_list: list[TimeSlot] = []

        try:
            sd = datetime.strptime(start_date[:10], "%Y-%m-%d").date()
            ed = datetime.strptime(end_date[:10], "%Y-%m-%d").date()
        except (ValueError, IndexError):
            logger.warning("V3.9 生成时间槽: 日期格式错误 start={}, end={}", start_date, end_date)
            return result_list

        # 默认模式
        weekday_normal = patterns.get("weekday_normal", {
            "work_periods": [{"start": "08:00", "end": "11:45"}, {"start": "12:45", "end": "17:15"}],
            "slot_duration": 15,
        })
        weekend_pattern = patterns.get("weekend", {
            "work_periods": [{"start": "08:00", "end": "11:45"}, {"start": "12:45", "end": "15:45"}],
            "slot_duration": 15,
        })

        slot_duration = weekday_normal.get("slot_duration", 15)
        global_idx = 0

        current = sd
        while current <= ed:
            date_str = current.strftime("%Y-%m-%d")
            # 判断周末（周六=5, 周日=6）
            is_weekend = current.weekday() >= 5
            pattern = weekend_pattern if is_weekend else weekday_normal
            work_periods = pattern.get("work_periods", [])

            # 为每个工作时段生成15分钟时间槽
            for period in work_periods:
                start_str = period.get("start", "08:00")
                end_str = period.get("end", "17:00")
                try:
                    sh, sm = map(int, start_str.split(":"))
                    eh, em = map(int, end_str.split(":"))
                except (ValueError, AttributeError):
                    continue

                period_start_min = sh * 60 + sm
                period_end_min = eh * 60 + em

                # 按 slot_duration 分钟切分
                cur_min = period_start_min
                while cur_min + slot_duration <= period_end_min:
                    start_time = f"{cur_min // 60:02d}:{cur_min % 60:02d}"
                    end_min = cur_min + slot_duration
                    end_time = f"{end_min // 60:02d}:{end_min % 60:02d}"

                    ts = TimeSlot(
                        date=date_str,
                        hour=cur_min // 60,
                        available_capacity=0.0,  # 全局时间槽不绑定产能
                        workcenter_id="GLOBAL",
                        process_id="GLOBAL",
                        index=global_idx,
                        slot_id=global_idx,
                        start_time=start_time,
                        end_time=end_time,
                        is_frozen=False,
                    )
                    ts.capacity = {"minute": 0, "slot_duration": slot_duration}
                    result_list.append(ts)
                    global_idx += 1
                    cur_min += slot_duration

            current += timedelta(days=1)

        logger.info(
            "V3.9 时间槽(time_exclusive): {} 个全局15分钟时间槽 ({} ~ {}, 周末{}模式)",
            len(result_list), start_date, end_date,
            "启用" if weekend_pattern else "默认",
        )
        return result_list

    async def _fetch_time_slots(
        self, start_date: str | None, end_date: str | None,
        scheduling_mode: str = "capacity",
    ) -> list[TimeSlot]:
        """从本地 resource_calendars 表读取时间槽数据。

        Args:
            start_date: 排产开始日期 YYYY-MM-DD
            end_date: 排产结束日期 YYYY-MM-DD
            scheduling_mode: 求解模式
                - "capacity"（默认）: 聚合为日级时间槽（720 分钟/槽），适合产能累加模式
                - "time_exclusive": V3.9 基于 WorkTimePattern 生成15分钟全局时间槽

        V3: capacity 模式将小时级时间槽聚合为日级，避免搜索空间爆炸。
        V3.9: time_exclusive 模式改为基于 WorkTimePattern 生成15分钟全局时间槽，
              排除休息时间（11:45-12:45午休, 14:30-15:00晚饭），
              周末使用7小时模式。
        """
        # V3.9: time_exclusive 模式使用 WorkTimePattern 生成全局时间槽
        if scheduling_mode == "time_exclusive":
            if not start_date or not end_date:
                logger.warning("V3.9 time_exclusive 模式需要 start_date 和 end_date")
                return []
            patterns = await self._fetch_work_time_patterns()
            return self._generate_global_time_slots(start_date, end_date, patterns)

        # capacity 模式：从 resource_calendars 读取并聚合为日级
        async with async_session() as session:
            stmt = select(ORMResourceCalendar)
            if start_date:
                sd = start_date[:10] if len(start_date) >= 10 else start_date
                try:
                    sd_date = datetime.strptime(sd, "%Y-%m-%d").date()
                    stmt = stmt.where(ORMResourceCalendar.rc_date >= sd_date)
                except ValueError:
                    pass
            if end_date:
                ed = end_date[:10] if len(end_date) >= 10 else end_date
                try:
                    ed_date = datetime.strptime(ed, "%Y-%m-%d").date()
                    stmt = stmt.where(ORMResourceCalendar.rc_date <= ed_date)
                except ValueError:
                    pass
            result = await session.execute(stmt)
            rows = result.scalars().all()

        result_list: list[TimeSlot] = []

        # capacity 模式：按 (date, line_id, process_id) 聚合为日级时间槽
        daily_slots: dict[tuple[str, str, str], dict] = {}
        for r in rows:
            date_str = ""
            if r.rc_date is not None:
                date_str = r.rc_date.strftime("%Y-%m-%d") if isinstance(r.rc_date, date) else str(r.rc_date)
            if not date_str:
                continue
            is_working = r.is_working if r.is_working is not None else True
            if not is_working:
                continue

            line_id = r.line_id or ""
            process_id = r.process_id or ""
            key = (date_str, line_id, process_id)

            if key not in daily_slots:
                daily_slots[key] = {
                    "date": date_str,
                    "line_id": line_id,
                    "process_id": process_id,
                    "total_capacity": 0.0,
                    "slot_count": 0,
                }
            # 聚合每日总产能（各小时产能之和）
            cap = r.available_capacity or 0.0
            daily_slots[key]["total_capacity"] += cap
            daily_slots[key]["slot_count"] += 1

        for slot_data in daily_slots.values():
            total_cap = slot_data["total_capacity"]
            ts = TimeSlot(
                date=slot_data["date"],
                hour=0,  # 日级时间槽 hour=0
                available_capacity=total_cap,  # 使用聚合后的日总产能
                workcenter_id=slot_data["line_id"],
                process_id=slot_data["process_id"],
                index=0,
                slot_id=0,
                start_time="全天",
                end_time="全天",
                is_frozen=False,
            )
            ts.capacity = {"minute": 0, "slot_duration": 720}  # 日级 720 分钟
            result_list.append(ts)

        # 按日期排序
        result_list.sort(key=lambda ts: ts.date)
        for i, ts in enumerate(result_list):
            ts.index = i
            ts.slot_id = i

        logger.info(
            "时间槽(capacity): {} 个日级时间槽 (从 {} 行小时级数据聚合)",
            len(result_list), len(rows),
        )
        return result_list

    async def _fetch_process_info(self) -> list[ProcessInfo]:
        """从本地 process_info 表读取工序信息。"""
        async with async_session() as session:
            result = await session.execute(select(ORMProcessInfo))
            rows = result.scalars().all()
        result_list: list[ProcessInfo] = []
        for r in rows:
            pi = ProcessInfo(
                id=r.id,
                proc_code=r.proc_code or "",
                proc_name=r.proc_name or "",
                proc_type=r.proc_type or "",
                constraint_type=r.constraint_type or "机时约束",
                is_qc_point=bool(r.is_qc_point) if r.is_qc_point is not None else False,
                status=r.status or "启用",
            )
            result_list.append(pi)
        return result_list

    async def _fetch_product_processes(self) -> list[ProductProcess]:
        """从本地 product_processes 表读取产品工艺。"""
        async with async_session() as session:
            result = await session.execute(select(ORMProductProcess))
            rows = result.scalars().all()
        result_list: list[ProductProcess] = []
        for r in rows:
            pp = ProductProcess(
                id=r.id,
                product_id=r.product_id or "",
                process_id=r.process_id or "",
                seq=int(r.seq) if r.seq is not None else 0,
                auto_type=r.auto_type or "非自动",
                cycle_time=float(r.cycle_time) if r.cycle_time is not None else 0.0,
                max_units_per_beat=int(r.max_units_per_beat) if r.max_units_per_beat is not None else 1,
                prep_time=float(r.prep_time) if r.prep_time is not None else 0.0,
                wait_time=float(r.wait_time) if r.wait_time is not None else 0.0,
                dependency_type=r.dependency_type or "FS",
                wait_includes_offhours=bool(r.wait_includes_offhours) if r.wait_includes_offhours is not None else False,
                is_key=bool(r.is_key) if r.is_key is not None else False,
                remark=r.remark or "",
            )
            result_list.append(pp)
        return result_list

    async def _fetch_line_process_configs(self) -> list[LineProcessConfig]:
        """从本地 line_process_configs 表读取产线工艺配置。"""
        async with async_session() as session:
            result = await session.execute(select(ORMLineProcessConfig))
            rows = result.scalars().all()
        result_list: list[LineProcessConfig] = []
        for r in rows:
            lpc = LineProcessConfig(
                id=r.id,
                lpc_code=r.lpc_code or "",
                line_id=r.line_id or "",
                process_id=r.process_id or "",
                auto_type=r.auto_type or "非自动",
                is_bottleneck=bool(r.is_bottleneck) if r.is_bottleneck is not None else False,
                equipment_count=int(r.equipment_count) if r.equipment_count is not None else 0,
                worker_count=int(r.worker_count) if r.worker_count is not None else 0,
                status=r.status or "启用",
            )
            result_list.append(lpc)
        return result_list

    async def _fetch_process_bom(self) -> list[ProcessBOM]:
        """从本地 process_boms 表读取工序 BOM。"""
        async with async_session() as session:
            result = await session.execute(select(ORMProcessBOM))
            rows = result.scalars().all()
        result_list: list[ProcessBOM] = []
        for r in rows:
            pb = ProcessBOM(
                id=r.id,
                product_id=r.product_id or "",
                process_id=r.process_id or "",
                material_id=r.material_id or "",
                unit_qty=float(r.unit_qty) if r.unit_qty is not None else 0.0,
                reusable=bool(r.reusable) if r.reusable is not None else False,
                remark=r.remark or "",
            )
            result_list.append(pb)
        return result_list

    async def _fetch_material_kitting(self) -> list[MaterialKitting]:
        """从本地 material_kittings 表读取物料齐套。"""
        async with async_session() as session:
            result = await session.execute(select(ORMMaterialKitting))
            rows = result.scalars().all()
        result_list: list[MaterialKitting] = []
        for r in rows:
            kitting_date_str = ""
            if r.kitting_date is not None:
                kitting_date_str = r.kitting_date.strftime("%Y-%m-%d") if isinstance(r.kitting_date, date) else str(r.kitting_date)

            mk = MaterialKitting(
                id=r.id,
                demand_id=r.demand_id or "",
                product_id=r.product_id or "",
                process_id=r.process_id or "",
                material_id=r.material_id or "",
                required_qty=int(r.required_qty) if r.required_qty is not None else 0,
                available_qty=int(r.available_qty) if r.available_qty is not None else 0,
                shortage_qty=int(r.shortage_qty) if r.shortage_qty is not None else 0,
                kitting_date=kitting_date_str,
                kitting_status=r.kitting_status or "待确认",
            )
            result_list.append(mk)
        return result_list

    async def _fetch_changeover_matrix(self) -> list[ChangeoverMatrix]:
        """从本地 changeover_matrices 表读取换线矩阵。

        V3: 同时读取产品维度和 LPC 维度的换线数据。
        """
        async with async_session() as session:
            result = await session.execute(select(ORMChangeoverMatrix))
            rows = result.scalars().all()
        matrix: list[ChangeoverMatrix] = []
        for r in rows:
            setup_time = float(r.setup_time) if r.setup_time is not None else 0.0
            matrix.append(ChangeoverMatrix(
                from_product_id=r.from_product_id or "",
                to_product_id=r.to_product_id or "",
                from_lpc_id=r.from_lpc_id or "",
                to_lpc_id=r.to_lpc_id or "",
                changeover_type=r.changeover_type or "产品换线",
                setup_time=setup_time,
                changeover_time=setup_time,  # 兼容别名
                changeover_cost=0.0,
                similarity_score=1.0,
            ))
        return matrix

    async def _fetch_buffers(self) -> list[Buffer]:
        """从本地 buffer_configs 表读取缓冲配置。"""
        async with async_session() as session:
            result = await session.execute(select(ORMBufferConfig))
            rows = result.scalars().all()
        bufs: list[Buffer] = []
        for r in rows:
            bufs.append(Buffer(
                id=r.id,
                from_workcenter_id="",
                to_workcenter_id="",
                buffer_type=BufferType.TIME,
                duration_hours=float(r.buffer_time) / 60.0 if r.buffer_time is not None else 0.0,
                green_zone=0.0,
                yellow_zone=0.0,
                red_zone=0.0,
                workcenter_id=r.process_id or "",
            ))
        return bufs

    # ── V1 兼容方法（deprecated，保留避免其他模块报错）──────────────────────

    async def _fetch_all_rows(self, worksheet_id: str) -> list[dict[str, Any]]:
        """分页拉取工作表全部行数据。"""
        all_rows: list[dict[str, Any]] = []
        page_index = 1
        while True:
            resp = await self._hap.get_rows(
                worksheet_id=worksheet_id,
                page_index=page_index,
                page_size=1000,
            )
            rows = resp.get("data", {}).get("rows", [])
            all_rows.extend(rows)
            total = int(resp.get("data", {}).get("total", 0))
            if len(all_rows) >= total or not rows:
                break
            page_index += 1
        return all_rows

    def _parse_option(self, value: Any, default: str = "") -> str:
        """解析 HAP 选项字段值。"""
        if isinstance(value, list) and value:
            return value[0].get("value", default)
        if isinstance(value, str):
            return value
        return default

    async def _fetch_work_centers(self) -> list[WorkCenter]:
        """从 HAP work_center 表读取工作中心列表（deprecated，请使用 _fetch_production_lines）。"""
        ws_id = WORKSHEET_IDS.get("work_center", "")
        if not ws_id:
            logger.warning("work_center 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        centers: list[WorkCenter] = []
        type_map = {v.value: v for v in WorkCenterType}
        status_map = {v.value: v for v in WorkCenterStatus}
        for r in rows:
            type_val = _opt_value(r.get("wc_type", ""))
            status_val = _opt_value(r.get("wc_status", ""))
            oee_pct = _float_val(r.get("oee", 100))
            daily_cap = _float_val(r.get("daily_capacity", 0))
            centers.append(WorkCenter(
                id=r.get("rowId", r.get("rowid", "")),
                code=_str_val(r.get("wc_code", "")),
                name=_str_val(r.get("wc_name", "")),
                type=type_map.get(type_val, WorkCenterType.PRODUCTION_LINE),
                oee=oee_pct / 100.0 if oee_pct > 1 else oee_pct,
                daily_capacity=daily_cap,
                hourly_capacity=daily_cap / 12.0 if daily_cap > 0 else 0.0,
                status=status_map.get(status_val, WorkCenterStatus.AVAILABLE),
                is_bottleneck=bool(_int_val(r.get("is_bottleneck", 0))),
                compatible_products=_str_val(r.get("compatible_products", "")).split(",") if r.get("compatible_products") else [],
            ))
        return centers

    async def _fetch_order_items(self) -> list[OrderItem]:
        """从 HAP order_item 表读取订单明细列表（deprecated，请使用 _fetch_demand_plans）。"""
        ws_id = WORKSHEET_IDS.get("order_item", "")
        if not ws_id:
            logger.warning("order_item 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        order_priority = await self._fetch_order_priorities()
        items: list[OrderItem] = []
        for r in rows:
            product_id = _relation_id(r.get("related_product", ""))
            product_name = _relation_name(r.get("related_product", ""))
            order_id = _relation_id(r.get("related_order", ""))
            order_name = _relation_name(r.get("related_order", ""))
            status_val = _opt_value(r.get("item_status", ""))
            priority = order_priority.get(order_id, "P2")
            items.append(OrderItem(
                id=r.get("rowId", r.get("rowid", "")),
                order_id=order_id,
                product_id=product_id,
                demand_qty=_float_val(r.get("demand_qty", 0.0)),
                scheduled_qty=_float_val(r.get("scheduled_qty", 0.0)),
                delivery_date=_datetime_val(r.get("item_delivery_date")),
                status=OrderItemStatus.PENDING,
                order_no=order_name,
                product=product_name,
                quantity=_float_val(r.get("demand_qty", 0.0)),
                priority=priority,
                changeover_group=_str_val(r.get("changeover_group", "")),
            ))
        return items

    async def _fetch_order_priorities(self) -> dict[str, str]:
        """从 production_order 表获取订单优先级映射（deprecated，V2 优先级已合并到 demand_plan）。"""
        ws_id = WORKSHEET_IDS.get("production_order", "")
        if not ws_id:
            return {}
        rows = await self._fetch_all_rows(ws_id)
        result: dict[str, str] = {}
        for r in rows:
            rid = r.get("rowId", r.get("rowid", ""))
            priority_val = _opt_value(r.get("priority", "P2"))
            result[rid] = priority_val
        return result

    async def _fetch_process_routes(self) -> list[ProcessRoute]:
        """从 HAP process_route 表读取工艺路径（deprecated，请使用 _fetch_product_processes + _fetch_line_process_configs）。"""
        ws_id = WORKSHEET_IDS.get("process_route", "")
        if not ws_id:
            logger.warning("process_route 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        route_map: dict[str, list[ProcessStep]] = {}
        route_id_map: dict[str, str] = {}
        for r in rows:
            pid = _str_val(r.get("product_id", ""))
            step = ProcessStep(
                step_order=_int_val(r.get("step_order", 0)),
                step_name=_str_val(r.get("step_name", "")),
                workcenter_id=_str_val(r.get("workcenter_id", "")),
                standard_hours=_float_val(r.get("standard_hours", 0.0)),
                is_drum=bool(_int_val(r.get("is_drum", 0))),
                curing_time=_float_val(r.get("curing_time", 0.0)),
                transfer_time=_float_val(r.get("transfer_time", 0.0)),
            )
            if pid not in route_map:
                route_map[pid] = []
                route_id_map[pid] = r.get("rowId", r.get("rowid", ""))
            route_map[pid].append(step)

        routes: list[ProcessRoute] = []
        for pid, steps in route_map.items():
            steps.sort(key=lambda s: s.step_order)
            routes.append(ProcessRoute(
                id=route_id_map.get(pid, ""),
                product_id=pid,
                steps=steps,
            ))
        return routes

    # ── 求解 ──────────────────────────────────────────────────────────────

    async def run_scheduling(
        self,
        problem: SchedulingProblem,
        solver_type: str = "ortools",
        config: dict[str, Any] | None = None,
    ) -> SolveResult:
        """调用排产引擎求解。

        Args:
            problem: 排产问题实例
            solver_type: 求解器类型，"ortools" 或 "ga"
            config: 约束开关、目标权重等参数

        Returns:
            SolveResult: 求解结果
        """
        config = config or {}

        # 将 config 中的约束/权重注入 problem
        if "hard_rules" in config:
            problem.hard_rules = [HardRule(r) for r in config["hard_rules"]]
        if "soft_rules" in config:
            problem.soft_rules = [SoftRule(r) for r in config["soft_rules"]]
        if "objective_weights" in config:
            problem.objective_weights = {
                SoftRule(k): float(v) for k, v in config["objective_weights"].items()
            }
        if "freeze_horizon" in config:
            problem.freeze_horizon = int(config["freeze_horizon"])
        if "drum_workcenter_ids" in config:
            problem.drum_workcenter_ids = config["drum_workcenter_ids"]
        if "solver_params" in config:
            problem.solver_params = config["solver_params"]

        # 选择求解器
        if solver_type == "ga":
            from app.engine.solver_ga_deap import DEAPGASolver
            solver = DEAPGASolver()
            logger.info("使用 DEAP GA 求解器")
        else:
            solver = ORToolsSolver()
            logger.info("使用 ORTools CP-SAT 求解器")

        # 同步求解器在独立线程中运行，不阻塞事件循环
        result = await asyncio.to_thread(solver.solve, problem)

        logger.info(
            "求解完成: status={} tasks={} time={:.2f}s",
            result.status.value, len(result.tasks), result.solve_time_seconds,
        )
        # V3.9.3 debug: 打印每个任务的分配情况
        from collections import defaultdict
        debug_map = defaultdict(lambda: {"count": 0, "qty": 0})
        for t in result.tasks:
            key = f"seq={t.seq} {t.process_name}"
            debug_map[key]["count"] += 1
            debug_map[key]["qty"] += t.quantity
        for key, d in sorted(debug_map.items()):
            logger.info("  DEBUG task: {} tasks={} total_qty={}", key, d["count"], d["qty"])
        return result

    # ── 结果推送（V3: 写入本地 DB + 触发同步）──────────────────────────────

    async def push_results(
        self,
        result: SolveResult,
        plan_id: str,
        problem: SchedulingProblem | None = None,
        clear_old: bool = True,
    ) -> None:
        """将排产结果写入本地 DB，然后触发同步到 HAP（V3）。

        Args:
            result: 求解结果
            plan_id: 方案 ID
            clear_old: 是否清空旧数据
        """
        # 1. 写入 schedule_results 表
        if result.tasks:
            await self._batch_write_tasks(result.tasks, plan_id, problem)

        # 2. 更新 demand_plans 表的已排数量
        if result.tasks:
            await self._update_scheduled_quantities(result.tasks)

        # 3. 写入 schedule_plans 表的方案信息
        await self._write_plan_info(result, plan_id)

        # 4. 触发同步到 HAP（异步，不阻塞排产结果返回）
        try:
            from app.services.sync_service import SyncService
            sync_svc = SyncService()
            asyncio.create_task(sync_svc.push_to_hap("schedule_results"))
            asyncio.create_task(sync_svc.push_to_hap("schedule_plans"))
            asyncio.create_task(sync_svc.push_to_hap("demand_plans"))
            asyncio.create_task(sync_svc.push_to_hap("process_schedule_orders"))
            logger.info("HAP 同步已提交后台异步执行")
        except Exception as e:
            logger.warning("触发 HAP 同步失败（结果已写入本地 DB）: {}", e)

        logger.info("排产结果写入完成(V3), plan_id={}", plan_id)

    async def _generate_process_schedule_orders(
        self,
        plan_id: str,
        tasks: list[ScheduledTask],
    ) -> None:
        """按需求×工序分组排产任务，生成/更新工序计划单（ProcessScheduleOrder，工序级唯一）。

        V3.9.3: 工序级唯一（每需求×工序一条PSO），与派工单（SR）一对多。
        - 新工序：新建PSO，planned_qty=需求计划需求数量
        - 已有工序（报工中/已完成）：upsert，保留pso_completed_qty，更新pso_quantity=SUM(关联SR)
        - pso_unfinished_qty = planned_qty - pso_completed_qty
        同时更新对应 ScheduleResult 的 pso_id 字段。
        """
        # 按 demand_id + product_id 分组
        group_map: dict[tuple[str, str], list[ScheduledTask]] = defaultdict(list)
        for t in tasks:
            demand_id = t.order_item_id or t.item_id or ""
            product_id = t.product_id or ""
            if demand_id and product_id:
                group_map[(demand_id, product_id)].append(t)

        if not group_map:
            logger.warning("无有效排产任务可生成工序计划单")
            return

        # 查询需求计划，构建 demand_id -> quantity 映射（用于 planned_qty）
        demand_ids = {key[0] for key in group_map.keys()}
        demand_qty_map: dict[str, int] = {}
        if demand_ids:
            dp_result = await async_session().execute(
                select(ORMDemandPlan.id, ORMDemandPlan.quantity).where(ORMDemandPlan.id.in_(demand_ids))
            )
            for row in dp_result.all():
                demand_qty_map[row[0]] = int(row[1] or 0)

        today_str = datetime.now().strftime("%Y%m%d%H%M%S")
        seq_counter = 0

        # 构建任务到 pso_id 的映射（工序级，去掉 line_id）
        task_pso_map: dict[tuple[str, str, str], str] = {}  # (demand_id, product_id, process_id) -> pso_id
        # 记录新建/更新的PSO，用于后续更新 pso_quantity
        affected_pso_ids: set[str] = set()

        async with async_session() as session:
            # 查询现有PSO（报工中/已完成），构建 (demand_id, product_id, process_id) -> PSO 映射
            existing_pso_map: dict[tuple[str, str, str], ORMProcessScheduleOrder] = {}
            all_demand_ids = {key[0] for key in group_map.keys()}
            if all_demand_ids:
                existing_result = await session.execute(
                    select(ORMProcessScheduleOrder).where(
                        ORMProcessScheduleOrder.demand_id.in_(all_demand_ids),
                        ORMProcessScheduleOrder.pso_status.in_(["报工中", "已完成"]),
                    )
                )
                for pso in existing_result.scalars().all():
                    key = (pso.demand_id or "", pso.product_id or "", pso.process_id or "")
                    if key not in existing_pso_map or (pso.pso_completed_qty or 0) > (existing_pso_map[key].pso_completed_qty or 0):
                        existing_pso_map[key] = pso

            for (demand_id, product_id), group_tasks in group_map.items():
                # 按 process_id 分组（工序级唯一）
                process_groups: dict[str, list[ScheduledTask]] = defaultdict(list)
                for t in group_tasks:
                    process_id = t.process_id or ""
                    if process_id:
                        process_groups[process_id].append(t)

                # 按 seq 排序
                sorted_processes = sorted(
                    process_groups.items(),
                    key=lambda x: x[1][0].seq or x[1][0].step_order or x[1][0].step_no or 0
                )

                prev_pso_id = None
                prev_seq = None
                prev_seq_last_pso_id = None  # 上一个 seq 的最后 PSO
                current_seq_last_pso_id = None  # 当前 seq 的最后 PSO

                for process_id, process_tasks in sorted_processes:
                    key = (demand_id, product_id, process_id)
                    first_task = process_tasks[0]
                    seq_val = first_task.seq or first_task.step_order or first_task.step_no or 0
                    planned_qty_val = demand_qty_map.get(demand_id, 0)

                    # 同 seq 的并行工序共享前置：都指向上一 seq 的最后 PSO
                    if prev_seq is not None and seq_val != prev_seq:
                        # seq 变化：当前 seq 的最后 PSO 成为"上一 seq 的最后 PSO"
                        prev_seq_last_pso_id = current_seq_last_pso_id
                        current_seq_last_pso_id = None
                    current_prev_pso_id = prev_seq_last_pso_id

                    existing_pso = existing_pso_map.get(key)
                    if existing_pso:
                        # upsert：已有PSO（报工中/已完成），复用，保留completed_qty
                        pso_id = existing_pso.id
                        # 更新工序顺序和前道工序链
                        existing_pso.seq = seq_val
                        existing_pso.prev_pso_id = current_prev_pso_id
                        existing_pso.plan_id = plan_id
                        existing_pso.dependency_type = first_task.dependency_type or existing_pso.dependency_type
                        existing_pso.wait_time = first_task.wait_time or existing_pso.wait_time
                        existing_pso.planned_qty = planned_qty_val  # 确保planned_qty正确
                        existing_pso.sync_status = SyncStatus.PENDING_UPDATE
                    else:
                        # 新建PSO
                        seq_counter += 1
                        pso_code = f"PSO-{today_str}-{seq_counter:03d}"
                        pso_id = str(uuid.uuid4())

                        pso = ORMProcessScheduleOrder(
                            id=pso_id,
                            pso_code=pso_code,
                            demand_id=demand_id,
                            product_id=product_id,
                            process_id=process_id,
                            seq=seq_val,
                            line_id=None,  # 工序级，不绑定产线
                            prev_pso_id=current_prev_pso_id,
                            plan_id=plan_id,
                            pso_date=None,
                            pso_time_slot=None,
                            planned_qty=planned_qty_val,
                            pso_quantity=0,  # 后面用 SUM(SR) 更新
                            pso_completed_qty=0,
                            pso_unfinished_qty=planned_qty_val,
                            pso_status="已排产",
                            dependency_type=first_task.dependency_type or None,
                            wait_time=first_task.wait_time or None,
                            sync_status=SyncStatus.PENDING_CREATE,
                        )
                        session.add(pso)
                        existing_pso_map[key] = pso

                    task_pso_map[key] = pso_id
                    affected_pso_ids.add(pso_id)
                    current_seq_last_pso_id = pso_id
                    prev_seq = seq_val

            # 更新 ScheduleResult 的 pso_id（按工序级匹配）
            sr_result = await session.execute(
                select(ORMScheduleResult).where(ORMScheduleResult.plan_id == plan_id)
            )
            sr_rows = sr_result.scalars().all()
            updated_count = 0
            for sr in sr_rows:
                sr_key = (sr.demand_id or "", sr.product_id or "", sr.process_id or "")
                pso_id = task_pso_map.get(sr_key)
                if pso_id:
                    sr.pso_id = pso_id
                    updated_count += 1
            logger.info("更新派工单SR的pso_id: {} 条", updated_count)

            # V3.9.3: 更新所有受影响PSO的 pso_quantity = SUM(关联SR.sr_quantity)
            for pso_id in affected_pso_ids:
                sum_qty_result = await session.execute(
                    select(func.sum(ORMScheduleResult.sr_quantity))
                    .where(ORMScheduleResult.pso_id == pso_id)
                )
                total_qty = int(sum_qty_result.scalar() or 0)

                sum_completed_result = await session.execute(
                    select(func.sum(ORMScheduleResult.sr_completed_qty))
                    .where(ORMScheduleResult.pso_id == pso_id)
                )
                total_completed = int(sum_completed_result.scalar() or 0)

                # V3.9.4: 从SR同步 line_id、pso_date、pso_time_slot
                sr_info_result = await session.execute(
                    select(
                        ORMScheduleResult.line_id,
                        ORMScheduleResult.sr_date,
                        ORMScheduleResult.sr_time_slot,
                    ).where(
                        ORMScheduleResult.pso_id == pso_id,
                        ORMScheduleResult.sr_status.in_(["已排产", "待确认", "待生产", "报工中", "已完成"]),
                    ).order_by(ORMScheduleResult.sr_date)
                )
                sr_info_rows = sr_info_result.all()

                # 查询PSO对象（可能在session中，也可能在existing_pso_map中）
                pso_obj = None
                for key, p in existing_pso_map.items():
                    if p.id == pso_id:
                        pso_obj = p
                        break

                if pso_obj:
                    pso_obj.pso_quantity = total_qty
                    # 只更新completed_qty如果PSO是新建的（"已排产"状态无历史报工）
                    if pso_obj.pso_status == "已排产":
                        pso_obj.pso_completed_qty = total_completed
                    # 重新计算未完成
                    pso_obj.pso_unfinished_qty = max(0, (pso_obj.planned_qty or 0) - (pso_obj.pso_completed_qty or 0))
                    # V3.9.4: 同步产线、日期、时段（取最早SR的值）
                    if sr_info_rows:
                        first_sr = sr_info_rows[0]
                        if first_sr[0]:
                            pso_obj.line_id = first_sr[0]
                        if first_sr[1]:
                            pso_obj.pso_date = first_sr[1]
                        if first_sr[2]:
                            pso_obj.pso_time_slot = first_sr[2]
                    # 更新状态
                    if (pso_obj.pso_completed_qty or 0) >= (pso_obj.planned_qty or 0) and (pso_obj.planned_qty or 0) > 0:
                        pso_obj.pso_status = "已完成"
                    elif (pso_obj.pso_completed_qty or 0) > 0:
                        pso_obj.pso_status = "报工中"

            await session.commit()

        logger.info(
            "生成工序排产单 {} 条, 更新 ScheduleResult.pso_id {} 条",
            seq_counter, updated_count,
        )

    async def _generate_or_update_delivery_plans(
        self,
        plan_id: str,
        tasks: list[ScheduledTask],
        problem: SchedulingProblem | None = None,
    ) -> None:
        """V3.8: 生成或更新工序交付计划（ProcessDeliveryPlan）。

        - 首次排产时生成 PDP，planned_qty=需求数量
        - 后续排产时更新 planned_start_time（第一次派工的那天）
        - schedule_results 关联到 pdp_id
        - PDP 是持久化的，日终不清理

        数据来源：当前 plan_id 下的 schedule_results（已写入）
        """
        from collections import defaultdict
        from datetime import date as date_cls

        # 查询当前 plan_id 下的所有 SR，按 (demand_id, product_id, process_id, seq) 分组
        async with async_session() as session:
            sr_result = await session.execute(
                select(ORMScheduleResult).where(ORMScheduleResult.plan_id == plan_id)
            )
            sr_rows = sr_result.scalars().all()

            if not sr_rows:
                logger.warning("无排产结果，跳过工序交付计划生成")
                return

            # 按 (demand_id, product_id, process_id, seq) 分组
            # 同一工序可能有多条 SR（多天排产）
            group_map: dict[tuple, list] = defaultdict(list)
            for sr in sr_rows:
                key = (
                    sr.demand_id or "",
                    sr.product_id or "",
                    sr.process_id or "",
                    sr.seq or 0,
                )
                group_map[key].append(sr)

            # 查询需求计划，获取 quantity
            demand_ids = {k[0] for k in group_map.keys() if k[0]}
            demand_map: dict[str, ORMDemandPlan] = {}
            if demand_ids:
                dp_result = await session.execute(
                    select(ORMDemandPlan).where(ORMDemandPlan.id.in_(list(demand_ids)))
                )
                for dp in dp_result.scalars().all():
                    demand_map[dp.id] = dp

            # 查询已有的 PDP（按 demand_id + process_id + seq 查找）
            existing_pdp_map: dict[tuple, ORMProcessDeliveryPlan] = {}
            if demand_ids:
                pdp_result = await session.execute(
                    select(ORMProcessDeliveryPlan).where(
                        ORMProcessDeliveryPlan.demand_id.in_(list(demand_ids))
                    )
                )
                for pdp in pdp_result.scalars().all():
                    key = (pdp.demand_id or "", pdp.process_id or "", pdp.seq or 0)
                    existing_pdp_map[key] = pdp

            today_str = datetime.now().strftime("%Y%m%d%H%M%S")
            pdp_counter = 0
            updated_sr_count = 0
            created_count = 0
            updated_count = 0

            # 按 (demand_id, product_id) 分组，构建 prev_pdp_id 链
            demand_process_groups: dict[tuple[str, str], list[tuple]] = defaultdict(list)
            for key in group_map.keys():
                demand_id, product_id, process_id, seq = key
                demand_process_groups[(demand_id, product_id)].append(key)

            # 为每个 (demand_id, product_id) 按 seq 排序，构建链式关系
            pdp_id_map: dict[tuple, str] = {}  # (demand_id, process_id, seq) -> pdp_id
            for (demand_id, product_id), keys in demand_process_groups.items():
                # 按 seq 排序
                sorted_keys = sorted(keys, key=lambda k: k[3])
                prev_pdp_id = None
                for key in sorted_keys:
                    demand_id_k, product_id_k, process_id_k, seq_k = key
                    pdp_key = (demand_id_k, process_id_k, seq_k)

                    # 查找已有 PDP
                    existing_pdp = existing_pdp_map.get(pdp_key)

                    # 获取需求计划数量
                    dp = demand_map.get(demand_id_k)
                    planned_qty = int(dp.quantity) if dp and dp.quantity else 0

                    # 获取当前 plan 下该工序的最早排产日期
                    sr_list = group_map[key]
                    sr_dates = [sr.sr_date for sr in sr_list if sr.sr_date]
                    first_date = min(sr_dates) if sr_dates else None

                    if existing_pdp:
                        # 更新已有 PDP
                        # planned_qty 取 max（避免需求减少时覆盖）
                        if planned_qty > (existing_pdp.planned_qty or 0):
                            existing_pdp.planned_qty = planned_qty
                        existing_pdp.unfinished_qty = (existing_pdp.planned_qty or 0) - (existing_pdp.completed_qty or 0)
                        # 更新 planned_start_time（如果为空或比当前更早）
                        if first_date:
                            if not existing_pdp.planned_start_time or first_date < existing_pdp.planned_start_time:
                                existing_pdp.planned_start_time = first_date
                        # 更新状态
                        if (existing_pdp.completed_qty or 0) >= (existing_pdp.planned_qty or 0) and planned_qty > 0:
                            existing_pdp.pdp_status = "已完成"
                            if not existing_pdp.planned_finish_time:
                                existing_pdp.planned_finish_time = date_cls.today()
                        else:
                            existing_pdp.pdp_status = "排产中"
                        existing_pdp.prev_pdp_id = prev_pdp_id
                        existing_pdp.plan_id = plan_id
                        existing_pdp.sync_status = SyncStatus.PENDING_UPDATE
                        pdp_id = existing_pdp.id
                        updated_count += 1
                    else:
                        # 创建新 PDP
                        pdp_counter += 1
                        pdp_code = f"PDP-{today_str}-{pdp_counter:03d}"
                        pdp_id = str(uuid.uuid4())

                        new_pdp = ORMProcessDeliveryPlan(
                            id=pdp_id,
                            pdp_code=pdp_code,
                            demand_id=demand_id_k,
                            product_id=product_id_k,
                            process_id=process_id_k,
                            seq=seq_k,
                            line_id=sr_list[0].line_id if sr_list else None,
                            prev_pdp_id=prev_pdp_id,
                            plan_id=plan_id,
                            planned_qty=planned_qty,
                            completed_qty=0,
                            unfinished_qty=planned_qty,
                            planned_start_time=first_date,
                            planned_finish_time=None,
                            pdp_status="排产中",
                            dependency_type=sr_list[0].dependency_type if sr_list else None,
                            wait_time=sr_list[0].wait_time if sr_list else None,
                            sync_status=SyncStatus.PENDING_CREATE,
                        )
                        session.add(new_pdp)
                        created_count += 1

                    pdp_id_map[pdp_key] = pdp_id
                    prev_pdp_id = pdp_id

            # 更新 ScheduleResult 的 pdp_id
            for sr in sr_rows:
                pdp_key = (sr.demand_id or "", sr.process_id or "", sr.seq or 0)
                pdp_id = pdp_id_map.get(pdp_key)
                if pdp_id:
                    sr.pdp_id = pdp_id
                    updated_sr_count += 1

            await session.commit()

        logger.info(
            "V3.8 工序交付计划: 新建 {} 条, 更新 {} 条, 更新 SR.pdp_id {} 条",
            created_count, updated_count, updated_sr_count,
        )

    async def _batch_write_tasks(
        self,
        tasks: list[ScheduledTask],
        plan_id: str,
        problem: SchedulingProblem | None = None,
    ) -> None:
        """批量写入排产结果到本地 schedule_results 表。"""
        # 构建时间槽索引映射
        slot_map: dict[int, TimeSlot] = {}
        if problem and problem.time_slots:
            for ts in problem.time_slots:
                idx = ts.index if ts.index is not None else (ts.slot_id if ts.slot_id is not None else 0)
                slot_map[idx] = ts

        # 构建产线工艺配置索引：(line_id, process_id) → LineProcessConfig
        lpc_map: dict[tuple[str, str], LineProcessConfig] = {}
        if problem and problem.line_process_configs:
            for lpc in problem.line_process_configs:
                lpc_map[(lpc.line_id, lpc.process_id)] = lpc

        # 构建产品工艺索引：(product_id, process_id) → ProductProcess
        pp_map: dict[tuple[str, str], ProductProcess] = {}
        if problem and problem.product_processes:
            for pp in problem.product_processes:
                pp_map[(pp.product_id, pp.process_id)] = pp

        # 节拍计算过程变量日志
        beat_logs: list[str] = []

        async with async_session() as session:
            # 清空旧数据
            await session.execute(delete(ORMScheduleResult).where(ORMScheduleResult.plan_id == plan_id))

            for t in tasks:
                # 映射时间槽索引到实际时间
                slot_idx = t.time_slot if t.time_slot is not None else (t.slot_id if t.slot_id is not None else 0)
                ts = slot_map.get(slot_idx)

                # 构建时间槽显示文本
                # V3: 5分钟级时间槽，显示 "YYYY-MM-DD HH:MM-HH:MM"
                time_slot_text = ""
                if ts and ts.date:
                    # 优先从 TimeSlot 的 start_time/end_time 获取5分钟级时段
                    st = ts.start_time if ts.start_time else ""
                    et = ts.end_time if ts.end_time else ""
                    if st and et:
                        time_slot_text = f"{ts.date} {st}-{et}"
                    elif ts.hour == 0:
                        # 回退: 日级时间槽
                        time_slot_text = f"{ts.date} 全天"
                    else:
                        # 回退: 小时级时间槽
                        time_slot_text = f"{ts.date} {ts.hour:02d}:00-{ts.hour + 1:02d}:00"
                elif t.start_time and t.end_time:
                    # V3: 兼容字符串和日期对象
                    st_str = t.start_time.strftime('%H:%M') if hasattr(t.start_time, 'strftime') else str(t.start_time)
                    et_str = t.end_time.strftime('%H:%M') if hasattr(t.end_time, 'strftime') else str(t.end_time)
                    time_slot_text = f"{st_str}-{et_str}"

                # 构建日期
                sr_date_val = None
                if t.start_time:
                    # V3: start_time 可能是字符串（如 "2026-07-11"）或 date/datetime 对象
                    if isinstance(t.start_time, str):
                        try:
                            sr_date_val = datetime.strptime(t.start_time[:10], "%Y-%m-%d").date()
                        except ValueError:
                            pass
                    elif hasattr(t.start_time, 'date'):
                        sr_date_val = t.start_time.date()
                elif ts and ts.date:
                    try:
                        sr_date_val = datetime.strptime(ts.date, "%Y-%m-%d").date()
                    except ValueError:
                        pass

                # ── 节拍计算过程变量 ──
                line_id = t.workcenter_id or ""
                process_id = t.process_id or ""
                product_id = t.product_id or ""
                qty = int(round(t.quantity))

                lpc = lpc_map.get((line_id, process_id))
                pp = pp_map.get((product_id, process_id))

                # V3修复: 获取设备数（与 solver_ortools.py:1016/1724 保持一致）
                # 非自动工艺的 beat_count 应考虑设备并行度，避免与求解器算的 duration 不一致
                equipment_count = (
                    lpc.equipment_count if lpc and lpc.equipment_count and lpc.equipment_count > 0 else 1
                )

                # V3: auto_type 优先从 ProductProcess 获取（跟产品走），其次从 LineProcessConfig 获取
                # 如果 pp 查找失败，回退到 ScheduledTask 对象上的属性（由 solver 计算）
                auto_type = (
                    (pp.auto_type if pp and pp.auto_type else "")
                    or (lpc.auto_type if lpc and lpc.auto_type else "")
                    or t.auto_type
                    or "非自动"
                )
                max_units = (pp.max_units_per_beat if pp and pp.max_units_per_beat else 0) or t.max_units_per_beat or 1
                cycle_time = (pp.cycle_time if pp and pp.cycle_time else 0.0) or t.cycle_time or 0.0
                # V3修复: pp 查找失败时回退到 t.prep_time（由 solver_ortools.py V3 路径正确赋值）
                prep_time = (pp.prep_time if pp and pp.prep_time else 0.0) or t.prep_time or 0.0

                if auto_type == "自动":
                    # 自动：节拍数 = ceil(qty / max_units_per_beat)
                    beat_count = -(-qty // max_units) if max_units > 0 else qty  # 向上取整
                    # 每轮 = cycle_time + prep_time(换治具, 分钟转秒)
                    total_time = beat_count * (cycle_time + prep_time * 60)
                else:
                    # 非自动：节拍数 = ceil(qty / equipment_count)（与 solver_ortools.py:1023 一致）
                    beat_count = -(-qty // equipment_count) if equipment_count > 0 else qty  # 向上取整
                    # 总时间 = beat_count * cycle_time + prep_time(一次性准备, 分钟转秒)
                    total_time = beat_count * cycle_time + prep_time * 60

                # 填充到 task 对象
                t.auto_type = auto_type
                t.cycle_time = cycle_time
                t.max_units_per_beat = max_units
                t.beat_count = beat_count
                t.total_time = total_time

                # V3.9.2 计算任务实际起止时间（开始时间槽 + total_time 秒）
                # 优先于单个时间槽范围，避免740件只显示15分钟的"棍子"问题
                if ts and ts.date and ts.start_time and total_time > 0:
                    try:
                        task_start_dt = datetime.strptime(f"{ts.date} {ts.start_time}", "%Y-%m-%d %H:%M")
                        task_end_dt = task_start_dt + timedelta(seconds=total_time)
                        start_str = task_start_dt.strftime('%Y-%m-%d %H:%M')
                        end_str = task_end_dt.strftime('%Y-%m-%d %H:%M')
                        time_slot_text = f"{start_str} ~ {end_str}"
                        # 同步更新 task 对象，供 result.py SolveResult 路径使用
                        t.start_time = start_str
                        t.end_time = end_str
                    except ValueError:
                        pass  # 保留原 time_slot_text

                # 记录日志（只记前10条避免刷屏）
                if len(beat_logs) < 10:
                    beat_logs.append(
                        f"  {product_id[:8]}... | {process_id[:8]}... | {auto_type} | "
                        f"qty={qty} | max_units={max_units} | cycle={cycle_time}s | "
                        f"beats={beat_count} | total={total_time}s"
                    )

                sr = ORMScheduleResult(
                    plan_id=plan_id,
                    product_id=t.product_id or "",
                    process_id=t.process_id or "",
                    line_id=t.workcenter_id or "",
                    demand_id=t.order_item_id or t.item_id or None,
                    sr_date=sr_date_val,
                    sr_time_slot=time_slot_text or None,
                    sr_quantity=qty,
                    sr_status="待确认",
                    sr_completed_qty=0,
                    sr_unfinished_qty=qty,
                    process_code=t.process_code or None,
                    constraint_type=t.constraint_type or None,
                    seq=t.step_order or t.step_no or t.seq or None,
                    dependency_type=t.dependency_type or None,
                    wait_time=t.wait_time or None,
                    prep_time=t.prep_time or None,
                    sync_status=SyncStatus.PENDING_CREATE,
                )
                session.add(sr)

            await session.commit()

        # 输出节拍计算过程变量
        if beat_logs:
            logger.info("=== 节拍计算过程变量（前10条）===")
            for log_line in beat_logs:
                logger.info(log_line)
            if len(tasks) > 10:
                logger.info("  ... 共 {} 条任务", len(tasks))

        logger.info("写入排产结果 {} 条", len(tasks))

    async def _update_scheduled_quantities(
        self,
        tasks: list[ScheduledTask],
    ) -> None:
        """更新本地 demand_plans 表的已排数量。

        V3.1: scheduled_qty 不再累加，改为从当前批次的首道工序数量设置。
        排产数量控制完全由 completed_qty + remaining_qty 决定。
        scheduled_qty 仅用于显示"本次排产数量"。
        """
        # 按 demand_plan_id 分组，取首道工序数量（同一需求所有工序数量相同）
        from app.engine.models import ProcessStep
        qty_map: dict[str, float] = {}
        for t in tasks:
            oid = t.order_item_id or t.item_id
            if oid:
                # 取首道工序（seq最小）的数量
                current = qty_map.get(oid, 0.0)
                if current == 0.0:
                    qty_map[oid] = t.quantity

        async with async_session() as session:
            for oid, qty in qty_map.items():
                dp = await session.get(ORMDemandPlan, oid)
                if dp:
                    # 不再累加，直接设为本批次排产数量
                    dp.scheduled_qty = int(round(qty))
                    dp.sync_status = SyncStatus.PENDING_UPDATE
            await session.commit()
        logger.info("更新 {} 个需求计划的排产数量（scheduled_qty）", len(qty_map))

    async def _write_plan_info(
        self,
        result: SolveResult,
        plan_id: str,
    ) -> None:
        """写入本地 schedule_plans 表的方案信息。"""
        async with async_session() as session:
            sp = ORMSchedulePlan(
                sp_name=plan_id,
                sp_status=result.status.value,
                sp_solve_status=result.status.value,
                sp_solve_time=result.solve_time_seconds,
                sp_task_count=len(result.tasks),
                sp_total_output=len(result.tasks),
                sync_status=SyncStatus.PENDING_CREATE,
            )
            if result.objective_values:
                obj = result.objective_values
                if "otd_rate" in obj:
                    try:
                        sp.sp_total_output = int(round(float(obj.get("otd_rate", 0)) * 100))
                    except (ValueError, TypeError):
                        pass
            session.add(sp)
            await session.commit()
        logger.info("写入方案信息: plan_id={}", plan_id)

    # ── HAP 写入辅助方法（保留，V1 兼容）──────────────────────────────────

    async def _get_field_id_map(self, worksheet_id: str) -> dict[str, str]:
        """获取工作表 alias→fieldId 映射。"""
        struct = await self._hap.get_worksheet_structure(worksheet_id)
        fields = struct.get("data", {}).get("fields", [])
        return {f.get("alias", ""): f.get("fieldId") or f.get("id", "") for f in fields if f.get("alias")}

    def _build_fields_array(
        self, field_map: dict[str, str], data: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """将 alias→value 字典转为 HAP 要求的 [{"id": fieldId, "value": ...}] 数组。"""
        result = []
        for alias, value in data.items():
            fid = field_map.get(alias)
            if fid and value is not None and value != "":
                result.append({"id": fid, "value": value})
        return result

    async def _clear_worksheet(self, worksheet_id: str) -> None:
        """清空工作表所有行数据（批量删除）。"""
        rows = await self._fetch_all_rows(worksheet_id)
        row_ids = [r.get("rowId", "") for r in rows if r.get("rowId")]
        if not row_ids:
            logger.info("清空工作表 {} 完成，无需删除", worksheet_id)
            return
        for i in range(0, len(row_ids), 100):
            batch = row_ids[i : i + 100]
            try:
                await self._hap.batch_delete_rows(worksheet_id, batch)
            except Exception as e:
                logger.warning("批量删除失败，回退逐行删除: {}", e)
                for rid in batch:
                    try:
                        await self._hap.delete_row(worksheet_id, rid)
                    except Exception as e2:
                        logger.warning("删除行 {} 失败: {}", rid, e2)
        logger.info("清空工作表 {} 完成，共删除 {} 行", worksheet_id, len(row_ids))

    # ── 任务管理 ──────────────────────────────────────────────────────────

    async def insert_urgent_order(
        self, product_id: str, quantity: int, due_date: str, remark: str = "",
    ) -> dict[str, Any]:
        """紧急插单：新增紧急需求 → 删除次日及以后的排产结果 → 重新排产。

        流程：
        1. 新增紧急需求（priority="紧急"）到 demand_plans
        2. 删除明天及以后的排产结果(SR)/工序排产单(PSO)/报工单(RWO)
        3. 删除当天"待确认"的排产结果（保留当天"已确认"的，实现最小调整）
        4. 触发重新排产（紧急需求优先级最高，当天已确认排产通过冻结窗口保护）

        整个操作在数据库事务中执行，失败时全部回滚。

        Args:
            product_id: 产品 ID（本地 DB UUID）
            quantity: 需求数量
            due_date: 交期日期 YYYY-MM-DD
            remark: 备注

        Returns:
            dict: 包含 id、dp_code 和 task_id 的响应
        """
        # 排产锁检查并获取（防止事务执行期间其他排产请求介入）
        if self._scheduling_lock:
            raise HTTPException(
                status_code=409,
                detail="排产任务正在执行中，请等待当前排产完成后再试",
            )
        self._scheduling_lock = True

        now = datetime.now()
        today = now.date()
        tomorrow = today + timedelta(days=1)
        dp_code = f"URGENT-{now.strftime('%Y%m%d%H%M%S')}"

        try:
            due_date_val = datetime.strptime(due_date, "%Y-%m-%d").date()
        except ValueError:
            due_date_val = None

        try:
            # 事务1：新增紧急需求 + 清理旧排产数据
            async with async_session() as session:
                # 1. 新增紧急需求
                dp = ORMDemandPlan(
                    dp_code=dp_code,
                    product_id=product_id,
                    quantity=quantity,
                    priority="紧急",
                    status="待排",
                    due_date=due_date_val,
                    remark=remark or "紧急插单",
                    sync_status=SyncStatus.PENDING_CREATE,
                )
                session.add(dp)

                # 2. 删除明天及以后的排产结果(SR)
                future_srs = await session.execute(
                    select(ORMScheduleResult).where(ORMScheduleResult.sr_date >= tomorrow)
                )
                future_sr_ids = [sr.id for sr in future_srs.scalars()]
                if future_sr_ids:
                    # 先删报工单（外键引用 SR）
                    await session.execute(
                        delete(ORMReportWorkOrder).where(ORMReportWorkOrder.dispatch_id.in_(future_sr_ids))
                    )
                    # 再删排产结果
                    await session.execute(
                        delete(ORMScheduleResult).where(ORMScheduleResult.id.in_(future_sr_ids))
                    )
                    logger.info("紧急插单: 删除明天及以后的排产结果 {} 条", len(future_sr_ids))

                # 3. 删除当天"待确认"的排产结果（保留"已确认"的）
                today_pending = await session.execute(
                    select(ORMScheduleResult).where(
                        ORMScheduleResult.sr_date == today,
                        ORMScheduleResult.sr_status == "待确认",
                    )
                )
                today_pending_ids = [sr.id for sr in today_pending.scalars()]
                if today_pending_ids:
                    await session.execute(
                        delete(ORMReportWorkOrder).where(ORMReportWorkOrder.dispatch_id.in_(today_pending_ids))
                    )
                    await session.execute(
                        delete(ORMScheduleResult).where(ORMScheduleResult.id.in_(today_pending_ids))
                    )
                    logger.info("紧急插单: 删除当天待确认排产结果 {} 条", len(today_pending_ids))

                # 4. 删除明天及以后的工序排产单(PSO)
                await session.execute(
                    delete(ORMProcessScheduleOrder).where(
                        ORMProcessScheduleOrder.pso_date >= tomorrow
                    )
                )

                await session.commit()
                dp_id = dp.id
        except Exception:
            self._scheduling_lock = False
            raise

        logger.info("紧急插单: 新增紧急需求 dp_code={}, 清理旧排产完成", dp_code)

        # 5. 触发重新排产（当天冻结，紧急需求优先）
        # 锁已持有，直接创建 task 和后台排产（绕过 create_schedule 的锁检查）
        from app.schemas.schedule import ScheduleCreateRequest
        schedule_request = ScheduleCreateRequest(
            start_time=today.isoformat(),
            end_time=(today + timedelta(days=21)).isoformat(),
            freeze_horizon=1,  # 冻结当天（已确认的排产不动）
            solver_params={"scheduling_mode": "capacity"},
        )
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = {
            "task_id": task_id,
            "status": "RUNNING",
            "progress": 0,
            "created_at": datetime.now(),
            "started_at": datetime.now(),
            "result_summary": None,
        }
        asyncio.create_task(self._run_schedule(task_id, schedule_request))

        logger.info("紧急插单: 重新排产已启动 task_id={}", task_id)
        return {"row_id": dp_id, "dp_code": dp_code, "task_id": task_id}

    async def create_schedule(self, request: Any) -> str:
        """创建排产任务，异步执行完整流程：拉取数据 → 求解 → 推送结果。

        同一时间只允许一个排产任务运行（排产锁）。

        Args:
            request: 排产任务创建请求（ScheduleCreateRequest）

        Returns:
            str: 任务 ID

        Raises:
            HTTPException: 已有排产任务正在运行时返回 409
        """
        if self._scheduling_lock:
            raise HTTPException(
                status_code=409,
                detail="排产任务正在执行中，请等待当前排产完成后再试",
            )

        task_id = str(uuid.uuid4())
        self._scheduling_lock = True
        self._tasks[task_id] = {
            "task_id": task_id,
            "status": "RUNNING",
            "progress": 0,
            "created_at": datetime.now(),
            "started_at": datetime.now(),
            "result_summary": None,
        }

        # 在后台任务中执行排产，立即返回 task_id
        asyncio.create_task(self._run_schedule(task_id, request))
        return task_id

    async def _run_schedule(self, task_id: str, request: Any) -> None:
        """后台执行排产任务。"""
        try:
            # 0. 清理旧的排产结果和工序计划单（上一次排产数据）
            # V3.9.3: 只删除"已排产"/"待确认"的SR，保留"报工中"/"已完成"的SR（含报工数据）
            # V3.9.3: 不再清理PSO（工序级唯一，需要保留）；排产后更新 pso_quantity = SUM(关联SR)
            async with async_session() as clean_session:
                # 解除待删除SR关联的RWO的dispatch_id（避免外键约束冲突）
                await clean_session.execute(
                    text("""
                        UPDATE report_work_orders SET dispatch_id = NULL
                        WHERE dispatch_id IN (
                            SELECT id FROM schedule_results
                            WHERE sr_status IN ('已排产', '待确认')
                        )
                    """)
                )
                # V3.9.3: 只删除"已排产"/"待确认"的SR，保留"报工中"/"已完成"的SR
                old_sr_result = await clean_session.execute(
                    delete(ORMScheduleResult).where(
                        ORMScheduleResult.sr_status.in_(["已排产", "待确认"])
                    )
                )
                old_sr_count = old_sr_result.rowcount or 0
                if old_sr_count > 0:
                    logger.info("清理旧排产结果SR（已排产/待确认）: {} 条", old_sr_count)

                # V3.9.3: 清理"已排产"PSO（未报工的工序计划单）
                old_pso_result = await clean_session.execute(
                    delete(ORMProcessScheduleOrder).where(
                        ORMProcessScheduleOrder.pso_status == "已排产"
                    )
                )
                old_pso_count = old_pso_result.rowcount or 0
                if old_pso_count > 0:
                    logger.info("清理旧已排产工序计划单: {} 条", old_pso_count)

                # V3.9.3: 合并同工序的"报工中"/"已完成"PSO为工序级唯一
                pso_merge_result = await clean_session.execute(
                    select(ORMProcessScheduleOrder).where(
                        ORMProcessScheduleOrder.pso_status.in_(["报工中", "已完成"])
                    )
                )
                all_psos = pso_merge_result.scalars().all()
                pso_groups: dict[tuple, list] = defaultdict(list)
                for pso in all_psos:
                    key = (pso.demand_id, pso.product_id, pso.process_id)
                    pso_groups[key].append(pso)

                merge_count = 0
                for key, group in pso_groups.items():
                    if len(group) <= 1:
                        continue
                    # 按 completed_qty 降序，取第一条作为主PSO
                    group.sort(key=lambda x: x.pso_completed_qty or 0, reverse=True)
                    main_pso = group[0]
                    # 合并 completed_qty
                    total_completed = sum(p.pso_completed_qty or 0 for p in group)
                    main_pso.pso_completed_qty = total_completed
                    main_pso.pso_unfinished_qty = max(0, (main_pso.planned_qty or 0) - total_completed)
                    if total_completed >= (main_pso.planned_qty or 0) and (main_pso.planned_qty or 0) > 0:
                        main_pso.pso_status = "已完成"
                    # 更新其余PSO的SR关联到主PSO，然后删除非主PSO
                    for p in group[1:]:
                        await clean_session.execute(
                            update(ORMScheduleResult)
                            .where(ORMScheduleResult.pso_id == p.id)
                            .values(pso_id=main_pso.id)
                        )
                        await clean_session.execute(
                            delete(ORMProcessScheduleOrder).where(
                                ORMProcessScheduleOrder.id == p.id
                            )
                        )
                        merge_count += 1
                if merge_count > 0:
                    logger.info("合并同工序PSO为工序级唯一: {} 条被合并删除", merge_count)

                # 重置 demand_plans.scheduled_qty（旧数据已失效）
                await clean_session.execute(
                    text("UPDATE demand_plans SET scheduled_qty = 0")
                )

                await clean_session.commit()

            # 1. 拉取数据（V3.3: 提前读取 scheduling_mode，影响时间槽粒度）
            self._tasks[task_id]["progress"] = 10
            solver_params_preview = getattr(request, "solver_params", {}) or {}
            scheduling_mode_preview = solver_params_preview.get("scheduling_mode", "capacity")
            problem = await self.fetch_scheduling_data(
                start_date=getattr(request, "start_time", None),
                end_date=getattr(request, "end_time", None),
                scheduling_mode=scheduling_mode_preview,
            )

            # 2. 求解
            self._tasks[task_id]["progress"] = 50
            solver_type = getattr(request, "solver_type", None) or "ortools"

            # 从系统配置读取硬规则/软规则/权重（前端排产请求不传这些字段）
            from app.core.app_config import get_solver_config
            sys_config = get_solver_config()
            config: dict[str, Any] = {
                "hard_rules": sys_config.get("hard_rules", []),
                "soft_rules": sys_config.get("soft_rules", []),
            }
            # soft_rule_weights → objective_weights（字段名统一）
            soft_weights = sys_config.get("soft_rule_weights", {})
            if soft_weights:
                config["objective_weights"] = dict(soft_weights)

            # request 中的值覆盖系统配置（如果前端传了的话）
            if hasattr(request, "constraints") and request.constraints:
                if request.constraints.get("hard_rules"):
                    config["hard_rules"] = request.constraints["hard_rules"]
                if request.constraints.get("soft_rules"):
                    config["soft_rules"] = request.constraints["soft_rules"]
            if hasattr(request, "objective_weights") and request.objective_weights:
                config["objective_weights"] = request.objective_weights

            logger.info(
                "排产配置: solver={}, hard_rules={}, soft_rules={}, objective_weights={}",
                solver_type, config.get("hard_rules"), config.get("soft_rules"),
                config.get("objective_weights"),
            )

            # 冻结窗口：前 N 天的时间槽被锁定
            freeze_horizon = getattr(request, "freeze_horizon", 0) or 0
            if freeze_horizon > 0:
                config["freeze_horizon"] = freeze_horizon
                if "hard_rules" not in config:
                    config["hard_rules"] = []
                if "FREEZE_WINDOW" not in config["hard_rules"]:
                    config["hard_rules"].append("FREEZE_WINDOW")

            # 求解器参数
            # V3.6 修复: 前端未传 solver_params 时，使用与 fetch_scheduling_data 一致的默认模式
            # 避免 fetch 用 capacity(日级时间槽) 但 solver 用 time_exclusive(小时级) 的不匹配
            if hasattr(request, "solver_params") and request.solver_params:
                config["solver_params"] = request.solver_params
                logger.info("V3.6 使用前端传入的 solver_params: {}", request.solver_params)
            else:
                config["solver_params"] = {
                    "scheduling_mode": scheduling_mode_preview,
                    "max_time_in_seconds": 60,
                    "num_workers": 4,
                }
                logger.info("V3.6 前端未传 solver_params，使用默认模式: {}", scheduling_mode_preview)

            result = await self.run_scheduling(problem, solver_type, config)

            # 3. 推送结果
            self._tasks[task_id]["progress"] = 80
            plan_id = f"PLAN-{task_id[:8]}"
            await self.push_results(result, plan_id, problem)

            # 4. 生成工序排产单
            if result.tasks:
                await self._generate_process_schedule_orders(plan_id, result.tasks)

            # 4.1 V3.8: 生成或更新工序交付计划（持久化，日终不清理）
            if result.tasks:
                await self._generate_or_update_delivery_plans(plan_id, result.tasks, problem)

            # 5. 更新任务状态
            self._tasks[task_id].update({
                "status": "SUCCESS",
                "progress": 100,
                "completed_at": datetime.now(),
                "result": result,
                "problem": problem,
                "result_summary": {
                    "plan_id": plan_id,
                    "solve_status": result.status.value,
                    "task_count": len(result.tasks),
                    "solve_time_seconds": round(result.solve_time_seconds, 2),
                    "solver_name": result.solver_name,
                },
            })
        except Exception as e:
            logger.exception("排产任务 {} 执行失败", task_id)
            self._tasks[task_id].update({
                "status": "FAILURE",
                "progress": 0,
                "completed_at": datetime.now(),
                "result_summary": {"error": str(e)},
            })
        finally:
            self._scheduling_lock = False

        return task_id

    async def get_status(self, task_id: str) -> dict[str, Any]:
        """查询排产任务状态。

        Args:
            task_id: 任务 ID

        Returns:
            dict: 任务状态信息
        """
        task = self._tasks.get(task_id)
        if not task:
            return {
                "task_id": task_id,
                "status": "NOT_FOUND",
                "progress": 0,
            }
        return task

    async def cancel_schedule(self, task_id: str) -> None:
        """撤销排产任务。

        Args:
            task_id: 任务 ID
        """
        task = self._tasks.get(task_id)
        if task and task["status"] == "RUNNING":
            task["status"] = "CANCELLED"
            task["completed_at"] = datetime.now()
            logger.info("排产任务 {} 已取消", task_id)

    async def confirm_schedule(self, task_id: str) -> dict:
        """确认排产结果：状态改为待生产，并自动生成报工单。

        同时更新工序排产单状态（已排产→待生产）和需求计划状态（待确认→待生产）。
        """
        plan_id = f"PLAN-{task_id[:8]}" if not task_id.startswith("PLAN-") else task_id
        async with async_session() as session:
            result = await session.execute(
                select(ORMScheduleResult).where(ORMScheduleResult.plan_id == plan_id)
            )
            results = result.scalars().all()
            if not results:
                return {"confirmed": 0, "report_orders": 0}

            report_count = 0
            pso_updated = 0
            demand_updated = 0
            for sr in results:
                if sr.sr_status in ("待确认", None):
                    sr.sr_status = "待生产"
                    sr.sync_status = SyncStatus.PENDING_UPDATE

                # 更新关联的工序排产单状态
                if sr.pso_id:
                    pso = await session.get(ORMProcessScheduleOrder, sr.pso_id)
                    if pso and pso.pso_status in ("已排产",):
                        pso.pso_status = "待生产"
                        pso.sync_status = SyncStatus.PENDING_UPDATE
                        pso_updated += 1

                # 更新关联的需求计划状态
                if sr.demand_id:
                    dp = await session.get(ORMDemandPlan, sr.demand_id)
                    if dp and dp.status in ("待排", "待确认"):
                        dp.status = "待生产"
                        dp.sync_status = SyncStatus.PENDING_UPDATE
                        demand_updated += 1

                # 生成报工单（仅当无已有报工单时）
                existing = await session.execute(
                    select(ORMReportWorkOrder).where(ORMReportWorkOrder.dispatch_id == sr.id)
                )
                if not existing.scalars().first():
                    # 生成报工单编号 RW-YYYYMMDD-序号
                    from datetime import date as _date
                    rw_code = f"RW-{_date.today().strftime('%Y%m%d')}-{sr.id[:8].upper()}"
                    rwo = ORMReportWorkOrder(
                        rw_code=rw_code,
                        dispatch_id=sr.id,
                        product_id=sr.product_id,
                        process_id=sr.process_id,
                        line_id=sr.line_id,
                        rw_date=sr.sr_date,
                        rw_time_slot=sr.sr_time_slot,
                        rw_plan_qty=sr.sr_quantity,
                        rw_actual_qty=0,
                        rw_defect_qty=0,
                        rw_status="待报工",
                        sync_status=SyncStatus.PENDING_CREATE,
                    )
                    session.add(rwo)
                    report_count += 1

            await session.commit()

        # 触发同步到 HAP
        try:
            from app.services.sync_service import SyncService
            sync_svc = SyncService()
            asyncio.create_task(sync_svc.push_to_hap("schedule_results"))
            asyncio.create_task(sync_svc.push_to_hap("process_schedule_orders"))
            asyncio.create_task(sync_svc.push_to_hap("demand_plans"))
            asyncio.create_task(sync_svc.push_to_hap("report_work_orders"))
        except Exception as e:
            logger.warning("确认排产 HAP 同步触发失败: {}", e)

        logger.info(
            "确认排产: task_id={}, 确认{}条, 生成报工单{}条, 更新工序排产单{}条, 更新需求计划{}条",
            task_id, len(results), report_count, pso_updated, demand_updated,
        )
        return {"confirmed": len(results), "report_orders": report_count, "pso_updated": pso_updated, "demand_updated": demand_updated}

    async def list_schedules(
        self,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """查询排产任务列表（分页）。

        优先从内存读取，内存为空时从本地 schedule_plans 表读取。

        Args:
            page: 页码，从 1 开始
            size: 每页条数

        Returns:
            dict: 包含 items 和 total 的字典
        """
        all_items = list(self._tasks.values())

        # 内存为空时从本地 DB 排产方案表读取
        if not all_items:
            try:
                async with async_session() as session:
                    result = await session.execute(select(ORMSchedulePlan))
                    plans = result.scalars().all()
                    for r in plans:
                        plan_code = r.sp_name or ""
                        task_id = plan_code.replace("PLAN-", "") if plan_code else r.id
                        all_items.append({
                            "task_id": task_id,
                            "status": "SUCCESS",
                            "progress": 100,
                            "created_at": r.created_at,
                            "started_at": r.created_at,
                            "completed_at": r.updated_at,
                            "result_summary": {
                                "plan_id": plan_code,
                                "solve_status": r.sp_solve_status or "OPTIMAL",
                                "task_count": r.sp_task_count or 0,
                                "solve_time_seconds": r.sp_solve_time or 0,
                                "solver_name": r.sp_solver or "ortools-cp-sat",
                            },
                        })
            except Exception as e:
                logger.warning("从本地 DB 读取排产方案失败: {}", e)

        total = len(all_items)
        start = (page - 1) * size
        end = start + size
        return {
            "items": all_items[start:end],
            "total": total,
        }


# ── 单例实例 ──────────────────────────────────────────────────────────────

schedule_service = ScheduleService()
