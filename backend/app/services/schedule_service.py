"""排产业务逻辑服务，负责任务的创建、数据拉取、求解、结果推送等操作。"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

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


# ── HAP 数据转换工具 ─────────────────────────────────────────────────────


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
    if isinstance(raw, list) and raw:
        return str(raw[0].get("sid", ""))
    if isinstance(raw, dict):
        return str(raw.get("sid", ""))
    return ""


def _relation_name(raw: Any) -> str:
    """HAP 关联字段取显示名称。"""
    if isinstance(raw, list) and raw:
        return str(raw[0].get("name", ""))
    if isinstance(raw, dict):
        return str(raw.get("name", ""))
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
    """排产任务业务逻辑服务（单例，通过 FastAPI Depends 注入）。"""

    def __init__(self) -> None:
        self._hap = HAPClient()
        # 内存缓存：task_id -> 任务状态信息
        self._tasks: dict[str, dict[str, Any]] = {}

    def _parse_option(self, value: Any, default: str = "") -> str:
        """解析 HAP 选项字段值。"""
        if isinstance(value, list) and value:
            return value[0].get("value", default)
        if isinstance(value, str):
            return value
        return default

    # ── 数据拉取 ──────────────────────────────────────────────────────────

    async def fetch_scheduling_data(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> SchedulingProblem:
        """从 HAP 拉取数据并构建 SchedulingProblem（V2）。

        Args:
            start_date: 排产开始日期，格式 YYYY-MM-DD
            end_date: 排产结束日期，格式 YYYY-MM-DD

        Returns:
            SchedulingProblem: 求解问题实例
        """
        logger.info("开始从 HAP 拉取排产数据(V2), 日期范围: {} ~ {}", start_date, end_date)

        # 并行拉取所有工作表数据
        results = await asyncio.gather(
            self._fetch_products(),
            self._fetch_production_lines(),
            self._fetch_demand_plans(),
            self._fetch_time_slots(start_date, end_date),
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
            "HAP 数据拉取完成(V2): 产品={} 产线={} 需求计划={} 时间槽={} 换线={} 缓冲={} "
            "工序信息={} 产品工艺={} 产线工艺配置={} 工序BOM={} 物料齐套={}",
            len(products), len(production_lines), len(demand_plans),
            len(time_slots), len(changeover), len(buffers),
            len(process_info), len(product_processes), len(line_process_configs),
            len(process_boms), len(material_kittings),
        )
        return problem

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

    async def _fetch_products(self) -> list[Product]:
        """从 HAP product 表读取产品列表。"""
        ws_id = WORKSHEET_IDS.get("product", "")
        if not ws_id:
            logger.warning("product 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        products: list[Product] = []
        for r in rows:
            products.append(Product(
                id=r.get("rowId", r.get("rowid", "")),
                code=_str_val(r.get("product_code", "")),
                name=_str_val(r.get("product_name", "")),
                changeover_attr=_opt_value(r.get("changeover_attr", "")),
                output_rate=_float_val(r.get("output_rate", 1.0)),
                batch_size=_int_val(r.get("batch_size", 1)),
                processing_batch=_int_val(r.get("processing_batch", 1)),
                transfer_batch=_int_val(r.get("transfer_batch", 1)),
                compatible_workcenters=_str_val(r.get("compatible_workcenters", "")).split(",") if r.get("compatible_workcenters") else [],
            ))
        return products

    # ── V2 数据拉取方法 ──────────────────────────────────────────────────

    async def _fetch_production_lines(self) -> list[ProductionLine]:
        """从 HAP production_line 表读取产线列表（V2，替代 _fetch_work_centers）。"""
        ws_id = WORKSHEET_IDS.get("production_line", "")
        if not ws_id:
            logger.warning("production_line 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        result: list[ProductionLine] = []
        for r in rows:
            line = ProductionLine(
                id=r.get("rowId", r.get("rowid", "")),
                line_code=_str_val(r.get("line_code", "")),
                line_name=_str_val(r.get("line_name", "")),
                line_type=self._parse_option(r.get("line_type"), "主产线"),
                daily_capacity=_int_val(r.get("line_capacity", 0)),
                line_load=_float_val(r.get("line_load", 0)),
                efficiency=_float_val(r.get("line_efficiency", 100)),
                location=_str_val(r.get("line_location", "")),
                status=self._parse_option(r.get("line_status"), "运行中"),
            )
            result.append(line)
        return result

    async def _fetch_demand_plans(self) -> list[DemandPlan]:
        """从 HAP demand_plan 表读取需求计划列表（V2，替代 _fetch_order_items）。"""
        ws_id = WORKSHEET_IDS.get("demand_plan", "")
        if not ws_id:
            logger.warning("demand_plan 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        result: list[DemandPlan] = []
        for r in rows:
            product_ref = r.get("dp_product", [])
            product_id = product_ref[0].get("sid", "") if product_ref and isinstance(product_ref, list) else ""
            dp = DemandPlan(
                id=r.get("rowId", r.get("rowid", "")),
                dp_code=_str_val(r.get("dp_code", "")),
                product_id=product_id,
                quantity=_int_val(r.get("dp_quantity", 0)),
                unit=_str_val(r.get("dp_unit", "台")),
                due_date=_str_val(r.get("dp_due_date", "")),
                priority=self._parse_option(r.get("dp_priority"), "中"),
                status=self._parse_option(r.get("dp_status"), "待确认"),
                remark=_str_val(r.get("dp_remark", "")),
            )
            result.append(dp)
        return result

    async def _fetch_time_slots(
        self, start_date: str | None, end_date: str | None,
    ) -> list[TimeSlot]:
        """从 HAP resource_calendar 表读取小时时段数据（V2）。

        注意：HAP API 日期筛选不生效，改为读取全部数据后在代码中手动过滤。
        """
        ws_id = WORKSHEET_IDS.get("resource_calendar", "")
        if not ws_id:
            logger.warning("resource_calendar 工作表 ID 未配置，跳过")
            return []

        rows = await self._fetch_all_rows(ws_id)

        result: list[TimeSlot] = []
        for r in rows:
            line_ref = r.get("rc_line", [])
            line_id = line_ref[0].get("sid", "") if line_ref and isinstance(line_ref, list) else ""

            # 解析工序关联
            process_ref = r.get("rc_process", [])
            process_id = process_ref[0].get("sid", "") if process_ref and isinstance(process_ref, list) else ""

            # 从 rc_code 解析时段信息（如 RC-LINE-SMT-A-PROC-SMT-01-2026-06-14-H08）
            rc_code = _str_val(r.get("rc_code", ""))
            hour_part = ""
            if "-H" in rc_code:
                hour_part = rc_code.split("-H")[-1]

            is_workday = self._parse_option(r.get("rc_is_workday"), "工作日") == "工作日"

            ts = TimeSlot(
                date=_str_val(r.get("rc_date", "")),
                hour=int(hour_part) if hour_part.isdigit() else 0,
                available_capacity=_float_val(r.get("rc_effective_capacity", 0)),
                workcenter_id=line_id,  # 复用旧字段名
                process_id=process_id,  # V2: 工序级时段
                index=0,  # 排序后重新分配
                slot_id=0,
                is_frozen=not is_workday,
            )
            # 只保留有产能的时段（跳过周末/节假日产能为0的记录）
            if ts.available_capacity > 0:
                # 手动按日期范围过滤（HAP API 日期筛选不生效）
                # 注意：start_date/end_date 可能含时间部分（如 YYYY-MM-DDTHH:mm:ss），
                # 需截取前10字符与 ts.date（YYYY-MM-DD）对齐比较
                sd = start_date[:10] if start_date and len(start_date) >= 10 else start_date
                ed = end_date[:10] if end_date and len(end_date) >= 10 else end_date
                if sd and ts.date < sd:
                    continue
                if ed and ts.date > ed:
                    continue
                result.append(ts)

        # 按 (date, hour) 排序，确保累积产量约束的时间顺序正确
        result.sort(key=lambda ts: (ts.date, ts.hour))
        for i, ts in enumerate(result):
            ts.index = i
            ts.slot_id = i
        return result

    async def _fetch_process_info(self) -> list[ProcessInfo]:
        """从 HAP process_info 表读取工序信息（V2 新增）。"""
        ws_id = WORKSHEET_IDS.get("process_info", "")
        if not ws_id:
            logger.warning("process_info 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        result: list[ProcessInfo] = []
        for r in rows:
            pi = ProcessInfo(
                id=r.get("rowId", r.get("rowid", "")),
                proc_code=_str_val(r.get("proc_code", "")),
                proc_name=_str_val(r.get("proc_name", "")),
                proc_type=self._parse_option(r.get("proc_type"), ""),
                constraint_type=self._parse_option(r.get("constraint_type"), "机时约束"),
                cycle_time=_float_val(r.get("cycle_time", 0)),
                setup_time=_float_val(r.get("setup_time", 0)),
                wait_time=_float_val(r.get("wait_time", 0)),
                # wait_includes_offhours: HAP 字段可能为空，wait_time>0 时默认 True（计入下班时间）
                wait_includes_offhours=bool(r.get("wait_includes_offhours")) if r.get("wait_includes_offhours") else True,
                prep_time=_float_val(r.get("prep_time", 0)),
                is_qc_point=bool(r.get("is_qc_point", False)),
                status=self._parse_option(r.get("proc_status"), "启用"),
            )
            result.append(pi)
        return result

    async def _fetch_product_processes(self) -> list[ProductProcess]:
        """从 HAP product_process 表读取产品工艺（V2，替代 _fetch_process_routes 的产品维度）。"""
        ws_id = WORKSHEET_IDS.get("product_process", "")
        if not ws_id:
            logger.warning("product_process 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        result: list[ProductProcess] = []
        for r in rows:
            product_ref = r.get("pp_product", [])
            process_ref = r.get("pp_process", [])
            product_id = product_ref[0].get("sid", "") if product_ref and isinstance(product_ref, list) else ""
            process_id = process_ref[0].get("sid", "") if process_ref and isinstance(process_ref, list) else ""

            pp = ProductProcess(
                id=r.get("rowId", r.get("rowid", "")),
                product_id=product_id,
                process_id=process_id,
                seq=_int_val(r.get("pp_seq", 0)),
                std_time=_float_val(r.get("pp_std_time", 0)),
                dependency_type=self._parse_option(r.get("dependency_type"), "FS"),
                is_key=bool(r.get("pp_is_key", False)),
                remark=_str_val(r.get("pp_remark", "")),
            )
            result.append(pp)
        return result

    async def _fetch_line_process_configs(self) -> list[LineProcessConfig]:
        """从 HAP line_process_config 表读取产线工艺配置（V2 新增）。"""
        ws_id = WORKSHEET_IDS.get("line_process_config", "")
        if not ws_id:
            logger.warning("line_process_config 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        result: list[LineProcessConfig] = []
        for r in rows:
            line_ref = r.get("lpc_line", [])
            process_ref = r.get("lpc_process", [])
            line_id = line_ref[0].get("sid", "") if line_ref and isinstance(line_ref, list) else ""
            process_id = process_ref[0].get("sid", "") if process_ref and isinstance(process_ref, list) else ""

            lpc = LineProcessConfig(
                id=r.get("rowId", r.get("rowid", "")),
                line_id=line_id,
                process_id=process_id,
                daily_capacity=_int_val(r.get("lpc_daily_capacity", 0)),
                efficiency=_float_val(r.get("lpc_efficiency", 100)),
                min_batch=_int_val(r.get("lpc_min_batch", 0)),
                is_bottleneck=bool(r.get("lpc_is_bottleneck", False)),
                equipment_count=_int_val(r.get("lpc_equipment_count", 0)),
                worker_count=_int_val(r.get("lpc_worker_count", 0)),
                status=self._parse_option(r.get("lpc_status"), "启用"),
            )
            result.append(lpc)
        return result

    async def _fetch_process_bom(self) -> list[ProcessBOM]:
        """从 HAP process_bom 表读取工序 BOM（V2 新增）。"""
        ws_id = WORKSHEET_IDS.get("process_bom", "")
        if not ws_id:
            logger.warning("process_bom 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        result: list[ProcessBOM] = []
        for r in rows:
            product_ref = r.get("pb_product", [])
            process_ref = r.get("pb_process", [])
            material_ref = r.get("pb_material", [])
            product_id = product_ref[0].get("sid", "") if product_ref and isinstance(product_ref, list) else ""
            process_id = process_ref[0].get("sid", "") if process_ref and isinstance(process_ref, list) else ""
            material_id = material_ref[0].get("sid", "") if material_ref and isinstance(material_ref, list) else ""

            pb = ProcessBOM(
                id=r.get("rowId", r.get("rowid", "")),
                product_id=product_id,
                process_id=process_id,
                material_id=material_id,
                unit_qty=_float_val(r.get("pb_unit_qty", 0)),
                reusable=bool(r.get("pb_reusable", False)),
                remark=_str_val(r.get("pb_remark", "")),
            )
            result.append(pb)
        return result

    async def _fetch_material_kitting(self) -> list[MaterialKitting]:
        """从 HAP material_kitting 表读取物料齐套（V2，替代 _fetch_buffers 中的 kitting 部分）。"""
        ws_id = WORKSHEET_IDS.get("material_kitting", "")
        if not ws_id:
            logger.warning("material_kitting 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        result: list[MaterialKitting] = []
        for r in rows:
            demand_ref = r.get("mk_demand", [])
            product_ref = r.get("mk_product", [])
            process_ref = r.get("mk_process", [])
            material_ref = r.get("mk_material", [])

            mk = MaterialKitting(
                id=r.get("rowId", r.get("rowid", "")),
                demand_id=demand_ref[0].get("sid", "") if demand_ref and isinstance(demand_ref, list) else "",
                product_id=product_ref[0].get("sid", "") if product_ref and isinstance(product_ref, list) else "",
                process_id=process_ref[0].get("sid", "") if process_ref and isinstance(process_ref, list) else "",
                material_id=material_ref[0].get("sid", "") if material_ref and isinstance(material_ref, list) else "",
                required_qty=_int_val(r.get("mk_required_qty", 0)),
                available_qty=_int_val(r.get("mk_available_qty", 0)),
                shortage_qty=_int_val(r.get("mk_shortage_qty", 0)),
                kitting_date=_str_val(r.get("mk_kitting_date", "")),
                kitting_status=self._parse_option(r.get("mk_kitting_status"), "待确认"),
            )
            result.append(mk)
        return result

    # ── V1 兼容方法（deprecated，保留避免其他模块报错）──────────────────────

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
        # 从 production_order 表获取优先级映射
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
                status=status_map.get(status_val, OrderItemStatus.PENDING) if 'status_map' in dir() else OrderItemStatus.PENDING,
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

    async def _fetch_changeover_matrix(self) -> list[ChangeoverMatrix]:
        """从 HAP changeover_matrix 表读取换线矩阵。"""
        ws_id = WORKSHEET_IDS.get("changeover_matrix", "")
        if not ws_id:
            logger.warning("changeover_matrix 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        matrix: list[ChangeoverMatrix] = []
        for r in rows:
            from_prod = _relation_name(r.get("from_product", ""))
            to_prod = _relation_name(r.get("to_product", ""))
            matrix.append(ChangeoverMatrix(
                from_product_id=from_prod,
                to_product_id=to_prod,
                changeover_time=_float_val(r.get("changeover_time", 0.0)),
                changeover_cost=_float_val(r.get("changeover_cost", 0.0)),
                similarity_score=_float_val(r.get("process_similarity", 1.0)),
            ))
        return matrix

    async def _fetch_buffers(self) -> list[Buffer]:
        """从 HAP buffer_config 表读取缓冲配置。"""
        ws_id = WORKSHEET_IDS.get("buffer_config", "")
        if not ws_id:
            logger.warning("buffer_config 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        type_map = {v.value: v for v in BufferType}
        bufs: list[Buffer] = []
        for r in rows:
            buf_type_key = _opt_key(r.get("buffer_type", ""))
            bufs.append(Buffer(
                id=r.get("rowId", r.get("rowid", "")),
                from_workcenter_id=_str_val(r.get("from_workcenter", "")),
                to_workcenter_id=_str_val(r.get("to_workcenter", "")),
                buffer_type=type_map.get(buf_type_key, BufferType.TIME),
                duration_hours=_float_val(r.get("duration_hours", 0.0)),
                green_zone=_float_val(r.get("green_zone", 0.0)),
                yellow_zone=_float_val(r.get("yellow_zone", 0.0)),
                red_zone=_float_val(r.get("red_zone", 0.0)),
            ))
        return bufs

    async def _fetch_process_routes(self) -> list[ProcessRoute]:
        """从 HAP process_route 表读取工艺路径（deprecated，请使用 _fetch_product_processes + _fetch_line_process_configs）。"""
        ws_id = WORKSHEET_IDS.get("process_route", "")
        if not ws_id:
            logger.warning("process_route 工作表 ID 未配置，跳过")
            return []
        rows = await self._fetch_all_rows(ws_id)
        # 工艺路径可能有多行对应同一 product_id，需按 product_id 聚合步骤
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
        return result

    # ── 结果推送 ──────────────────────────────────────────────────────────

    async def push_results(
        self,
        result: SolveResult,
        plan_id: str,
        problem: SchedulingProblem | None = None,
        clear_old: bool = True,
    ) -> None:
        """将排产结果推送到 HAP（V2）。

        Args:
            result: 求解结果
            plan_id: 方案 ID
            clear_old: 是否清空旧数据
        """
        ws_result = WORKSHEET_IDS.get("schedule_result", "")
        ws_plan = WORKSHEET_IDS.get("schedule_plan", "")
        ws_demand_plan = WORKSHEET_IDS.get("demand_plan", "")

        # 1. 清空 schedule_result 表旧数据（可选）
        if clear_old and ws_result:
            await self._clear_worksheet(ws_result)

        # 2. 批量写入 ScheduledTask 到 schedule_result 表
        if ws_result and result.tasks:
            await self._batch_write_tasks(ws_result, result.tasks, plan_id, problem)

        # 3. 更新 demand_plan 表的已排数量
        if ws_demand_plan and result.tasks:
            await self._update_scheduled_quantities(ws_demand_plan, result.tasks)

        # 4. 写入 schedule_plan 表的方案信息
        if ws_plan:
            await self._write_plan_info(ws_plan, result, plan_id)

        logger.info("排产结果推送完成(V2), plan_id={}", plan_id)

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
        # HAP 批量删除每次最多 100 条
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

    async def _batch_write_tasks(
        self,
        worksheet_id: str,
        tasks: list[ScheduledTask],
        plan_id: str,
        problem: SchedulingProblem | None = None,
    ) -> None:
        """批量写入排产结果到 HAP（V2 格式）。"""
        # 获取字段 ID 映射
        field_map = await self._get_field_id_map(worksheet_id)

        # 构建时间槽索引映射
        slot_map: dict[int, TimeSlot] = {}
        if problem and problem.time_slots:
            for ts in problem.time_slots:
                idx = ts.index if ts.index is not None else (ts.slot_id if ts.slot_id is not None else 0)
                slot_map[idx] = ts

        batch_size = 100
        for i in range(0, len(tasks), batch_size):
            batch = tasks[i : i + batch_size]
            rows = []
            for t in batch:
                # 映射时间槽索引到实际时间
                slot_idx = t.time_slot if t.time_slot is not None else (t.slot_id if t.slot_id is not None else 0)
                ts = slot_map.get(slot_idx)

                # 构建时间槽显示文本
                time_slot_text = ""
                if t.start_time and t.end_time:
                    time_slot_text = f"{t.start_time.strftime('%H:%M')}-{t.end_time.strftime('%H:%M')}"
                elif ts and ts.date:
                    time_slot_text = f"{ts.date} {ts.hour:02d}:00-{ts.hour + 1:02d}:00"

                # 构建日期文本
                date_text = ""
                if t.start_time:
                    date_text = t.start_time.strftime("%Y-%m-%d")
                elif ts and ts.date:
                    date_text = ts.date

                # V2 字段别名
                data: dict[str, Any] = {
                    "sr_code": plan_id,
                    "sr_seq": str(t.step_order or t.step_no or t.seq or 1),
                    "sr_qty": str(int(round(t.quantity))),
                    "sr_date": date_text,
                    "sr_time_slot": time_slot_text,
                    "sr_status": ["b3112bdf-b964-4c38-a906-cf986edef4d3"],  # 待生产
                }
                # 关联字段需要传 rowId
                if t.order_item_id or t.item_id:
                    data["sr_demand_plan"] = t.order_item_id or t.item_id
                if t.product_id:
                    data["sr_product"] = t.product_id
                if t.workcenter_id:
                    data["sr_line"] = t.workcenter_id
                if t.process_id:
                    data["sr_process"] = t.process_id

                rows.append({"fields": self._build_fields_array(field_map, data)})
            try:
                await self._hap.batch_create_rows(worksheet_id, rows)
            except Exception as e:
                logger.error("批量写入排产结果失败 (batch {}): {}", i // batch_size, e)
                raise
        logger.info("写入排产结果 {} 条", len(tasks))

    async def _update_scheduled_quantities(
        self,
        worksheet_id: str,
        tasks: list[ScheduledTask],
    ) -> None:
        """更新 demand_plan 表的已排数量（V2）。"""
        field_map = await self._get_field_id_map(worksheet_id)
        # 按 demand_plan_id 聚合已排数量
        qty_map: dict[str, float] = {}
        for t in tasks:
            oid = t.order_item_id or t.item_id
            qty_map[oid] = qty_map.get(oid, 0.0) + t.quantity

        # 逐行更新（HAP 不支持按条件批量更新不同值）
        for oid, qty in qty_map.items():
            try:
                fields = self._build_fields_array(field_map, {"scheduled_qty": str(int(round(qty)))})
                await self._hap.update_row(worksheet_id, oid, fields)
            except Exception as e:
                logger.warning("更新 demand_plan {} 已排数量失败: {}", oid, e)
        logger.info("更新 {} 个需求计划的已排数量", len(qty_map))

    async def _write_plan_info(
        self,
        worksheet_id: str,
        result: SolveResult,
        plan_id: str,
    ) -> None:
        """写入 schedule_plan 表的方案信息。"""
        field_map = await self._get_field_id_map(worksheet_id)
        data: dict[str, Any] = {
            "plan_code": plan_id,
            "plan_status": result.status.value,
            "total_output": str(len(result.tasks)),
            "create_time": datetime.now().strftime("%Y-%m-%d"),
        }
        if result.objective_values:
            obj = result.objective_values
            if "otd_rate" in obj:
                data["otd_rate"] = str(round(float(obj["otd_rate"]), 2))
            if "changeover_count" in obj:
                data["changeover_count"] = str(int(float(obj["changeover_count"])))
            if "balance_rate" in obj:
                data["balance_rate"] = str(round(float(obj["balance_rate"]), 2))
        fields = self._build_fields_array(field_map, data)
        try:
            await self._hap.create_row(worksheet_id, fields)
        except Exception as e:
            logger.error("写入方案信息失败: {}", e)
            raise

    # ── 任务管理 ──────────────────────────────────────────────────────────

    async def insert_urgent_order(
        self, product_id: str, quantity: int, due_date: str, remark: str = "",
    ) -> dict[str, Any]:
        """紧急插单：向 HAP 需求计划表写入一条紧急需求。

        Args:
            product_id: 产品 ID（HAP 产品主数据 rowId）
            quantity: 需求数量
            due_date: 交期日期 YYYY-MM-DD
            remark: 备注

        Returns:
            dict: 包含 row_id 和 dp_code 的响应
        """
        ws_id = WORKSHEET_IDS.get("demand_plan", "")
        if not ws_id:
            raise ValueError("demand_plan 工作表 ID 未配置")

        # 获取字段映射和结构
        field_map = await self._get_field_id_map(ws_id)
        struct = await self._hap.get_worksheet_structure(ws_id)
        fields_def = struct.get("data", {}).get("fields", [])

        # 查找选项字段的 key 值
        def _find_option_key(alias: str, target_value: str) -> str:
            for f in fields_def:
                if f.get("alias") == alias:
                    for opt in f.get("options", []) or []:
                        if opt.get("value") == target_value:
                            return opt.get("key", "")
            return ""

        priority_key = _find_option_key("dp_priority", "紧急")
        status_key = _find_option_key("dp_status", "待确认")

        # 生成需求编码
        now = datetime.now()
        dp_code = f"URGENT-{now.strftime('%Y%m%d%H%M%S')}"

        # 构建字段数据
        data: dict[str, Any] = {
            "dp_code": dp_code,
            "dp_product": [product_id],  # 关联字段传 [rowId]
            "dp_quantity": str(quantity),
            "dp_due_date": due_date,
            "dp_remark": remark or "紧急插单",
        }
        if priority_key:
            data["dp_priority"] = [priority_key]
        if status_key:
            data["dp_status"] = [status_key]

        fields_array = self._build_fields_array(field_map, data)
        result = await self._hap.create_row(ws_id, fields_array)
        row_id = result.get("data", {}).get("id", "") if isinstance(result.get("data"), dict) else ""
        logger.info("紧急插单成功: dp_code={}, row_id={}", dp_code, row_id)
        return {"row_id": row_id, "dp_code": dp_code}

    async def create_schedule(self, request: Any) -> str:
        """创建排产任务，异步执行完整流程：拉取数据 → 求解 → 推送结果。

        Args:
            request: 排产任务创建请求（ScheduleCreateRequest）

        Returns:
            str: 任务 ID
        """
        task_id = str(uuid.uuid4())
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
            # 1. 拉取数据
            self._tasks[task_id]["progress"] = 10
            problem = await self.fetch_scheduling_data(
                start_date=getattr(request, "start_time", None),
                end_date=getattr(request, "end_time", None),
            )

            # 2. 求解
            self._tasks[task_id]["progress"] = 50
            solver_type = getattr(request, "solver_type", None) or "ortools"
            config = {}
            if hasattr(request, "constraints") and request.constraints:
                config["hard_rules"] = request.constraints.get("hard_rules", [])
                config["soft_rules"] = request.constraints.get("soft_rules", [])
            if hasattr(request, "objective_weights") and request.objective_weights:
                config["objective_weights"] = request.objective_weights

            # 冻结窗口：前 N 天的时间槽被锁定
            freeze_horizon = getattr(request, "freeze_horizon", 0) or 0
            if freeze_horizon > 0:
                config["freeze_horizon"] = freeze_horizon
                # 启用 FREEZE_WINDOW 硬规则
                if "hard_rules" not in config:
                    config["hard_rules"] = []
                if "FREEZE_WINDOW" not in config["hard_rules"]:
                    config["hard_rules"].append("FREEZE_WINDOW")

            # 求解器参数
            if hasattr(request, "solver_params") and request.solver_params:
                config["solver_params"] = request.solver_params

            result = await self.run_scheduling(problem, solver_type, config)

            # 3. 推送结果
            self._tasks[task_id]["progress"] = 80
            plan_id = f"PLAN-{task_id[:8]}"
            await self.push_results(result, plan_id, problem)

            # 4. 更新任务状态
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

    async def list_schedules(
        self,
        page: int = 1,
        size: int = 20,
    ) -> dict[str, Any]:
        """查询排产任务列表（分页）。

        优先从内存读取，内存为空时从 HAP 排产方案表读取。

        Args:
            page: 页码，从 1 开始
            size: 每页条数

        Returns:
            dict: 包含 items 和 total 的字典
        """
        all_items = list(self._tasks.values())

        # 内存为空时从 HAP 排产方案表读取
        if not all_items:
            ws_plan = WORKSHEET_IDS.get("schedule_plan", "")
            if ws_plan:
                try:
                    rows = await self._fetch_all_rows(ws_plan)
                    for r in rows:
                        plan_code = _str_val(r.get("plan_code", ""))
                        # 从 plan_code 解析 task_id (如 PLAN-4a0ac8b1 → 4a0ac8b1)
                        task_id = plan_code.replace("PLAN-", "") if plan_code else r.get("rowId", "")
                        all_items.append({
                            "task_id": task_id,
                            "status": "SUCCESS",
                            "progress": 100,
                            "created_at": r.get("_createdAt", "") or _str_val(r.get("create_time", "")),
                            "started_at": r.get("_createdAt", "") or _str_val(r.get("create_time", "")),
                            "completed_at": r.get("_updatedAt", "") or _str_val(r.get("create_time", "")),
                            "result_summary": {
                                "plan_id": plan_code,
                                "solve_status": "OPTIMAL",
                                "task_count": int(_float_val(r.get("total_output", 0))),
                                "solve_time_seconds": 0,
                                "solver_name": "ortools-cp-sat",
                            },
                        })
                except Exception as e:
                    logger.warning("从 HAP 读取排产方案失败: {}", e)

        total = len(all_items)
        start = (page - 1) * size
        end = start + size
        return {
            "items": all_items[start:end],
            "total": total,
        }


# ── 单例实例 ──────────────────────────────────────────────────────────────

schedule_service = ScheduleService()
