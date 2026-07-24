"""APS-HAP 双向同步服务，处理本地 PostgreSQL 与 HAP（明道云）之间的数据同步。

核心功能：
- pull_from_hap: 从 HAP 拉取数据写入本地 DB（全量覆盖策略）
- push_to_hap: 将本地变更推送到 HAP（增量同步）
- get_sync_status: 获取各表同步状态统计
- pull_all / push_all_pending: 批量同步操作
"""

from datetime import datetime, date
from typing import Any

from loguru import logger
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session
from app.hap.client import HAPClient
from app.models.base import SyncStatus
from app.models.entities import (
    Product,
    ProcessInfo,
    ProductionLine,
    ProductProcess,
    LineProcessConfig,
    MaterialMaster,
    ProcessBOM,
    MaterialKitting,
    DemandPlan,
    ScheduleResult,
    ResourceCalendar,
    ChangeoverMatrix,
    BufferConfig,
    SchedulePlan,
    ReportWorkOrder,
    ProcessScheduleOrder,
)

# ── 常量 ──────────────────────────────────────────────────────────────────

HAP_PAGE_SIZE = 1000  # HAP 单次请求最大行数


# ── 表→HAP 映射配置 ──────────────────────────────────────────────────────

TABLE_HAP_MAP: dict[str, dict[str, Any]] = {
    "products": {
        "ws_id": "6a2bf816c839766934ee62e8",
        "model": Product,
        "hap_to_local": {
            "product_code": "prod_code",
            "product_name": "prod_name",
            "product_type": "prod_category",
            "product_spec": "prod_spec",
            "line_compat_code": "changeover_attr",
        },
        "local_to_hap": {
            "prod_code": "product_code",
            "prod_name": "product_name",
            "prod_category": "product_type",
            "prod_spec": "product_spec",
            "changeover_attr": "line_compat_code",
            "output_rate": "output_rate",
            "batch_size": "batch_size",
        },
        "field_types": {
            "prod_code": "str",
            "prod_name": "str",
            "prod_category": "option",
            "prod_spec": "str",
            "changeover_attr": "option",
            "output_rate": "float",
            "batch_size": "int",
        },
        "relation_fields": {},
    },
    "process_info": {
        "ws_id": "6a2ded6888359ed358a4facd",
        "model": ProcessInfo,
        "hap_to_local": {
            "proc_code": "proc_code",
            "proc_name": "proc_name",
            "proc_type": "proc_type",
            "constraint_type": "constraint_type",
            "is_qc_point": "is_qc_point",
            "proc_status": "status",
        },
        "local_to_hap": {
            "proc_code": "proc_code",
            "proc_name": "proc_name",
            "proc_type": "proc_type",
            "constraint_type": "constraint_type",
            "is_qc_point": "is_qc_point",
            "status": "proc_status",
        },
        "field_types": {
            "proc_code": "str",
            "proc_name": "str",
            "proc_type": "option",
            "constraint_type": "option",
            "is_qc_point": "bool",
            "status": "option",
        },
        "relation_fields": {},
    },
    "production_lines": {
        "ws_id": "6a2ded6b9702ee83243c2e1a",
        "model": ProductionLine,
        "hap_to_local": {
            "line_code": "line_code",
            "line_name": "line_name",
            "line_type": "line_type",
            "line_location": "location",
            "line_status": "status",
        },
        "local_to_hap": {
            "line_code": "line_code",
            "line_name": "line_name",
            "line_type": "line_type",
            "location": "line_location",
            "status": "line_status",
        },
        "field_types": {
            "line_code": "str",
            "line_name": "str",
            "line_type": "option",
            "location": "str",
            "status": "option",
        },
        "relation_fields": {},
    },
    "product_processes": {
        "ws_id": "6a2ded6d3005b538f6a54ef1",
        "model": ProductProcess,
        "hap_to_local": {
            "pp_product": "product_id",
            "pp_process": "process_id",
            "pp_seq": "seq",
            "pp_auto_type": "auto_type",
            "pp_cycle_time": "cycle_time",
            "pp_max_units_per_beat": "max_units_per_beat",
            "pp_prep_time": "prep_time",
            "pp_wait_time": "wait_time",
            "pp_dependency_type": "dependency_type",
            "pp_wait_includes_offhours": "wait_includes_offhours",
            "pp_is_key": "is_key",
            "pp_remark": "remark",
        },
        "local_to_hap": {
            "product_id": "pp_product",
            "process_id": "pp_process",
            "seq": "pp_seq",
            "auto_type": "pp_auto_type",
            "cycle_time": "pp_cycle_time",
            "max_units_per_beat": "pp_max_units_per_beat",
            "prep_time": "pp_prep_time",
            "wait_time": "pp_wait_time",
            "dependency_type": "pp_dependency_type",
            "wait_includes_offhours": "pp_wait_includes_offhours",
            "is_key": "pp_is_key",
            "remark": "pp_remark",
        },
        "field_types": {
            "product_id": "relation",
            "process_id": "relation",
            "seq": "int",
            "auto_type": "option",
            "cycle_time": "float",
            "max_units_per_beat": "int",
            "prep_time": "float",
            "wait_time": "float",
            "dependency_type": "option",
            "wait_includes_offhours": "bool",
            "is_key": "bool",
            "remark": "str",
        },
        "relation_fields": {
            "product_id": "products",
            "process_id": "process_info",
        },
    },
    "line_process_configs": {
        "ws_id": "6a2ded6f7a04850bc8397ba6",
        "model": LineProcessConfig,
        "hap_to_local": {
            "lpc_code": "lpc_code",
            "lpc_line": "line_id",
            "lpc_process": "process_id",
            "lpc_auto_type": "auto_type",
            "lpc_is_bottleneck": "is_bottleneck",
            "lpc_equipment_count": "equipment_count",
            "lpc_worker_count": "worker_count",
            "lpc_status": "status",
        },
        "local_to_hap": {
            "lpc_code": "lpc_code",
            "line_id": "lpc_line",
            "process_id": "lpc_process",
            "auto_type": "lpc_auto_type",
            "is_bottleneck": "lpc_is_bottleneck",
            "equipment_count": "lpc_equipment_count",
            "worker_count": "lpc_worker_count",
            "status": "lpc_status",
        },
        "field_types": {
            "lpc_code": "str",
            "line_id": "relation",
            "process_id": "relation",
            "auto_type": "option",
            "is_bottleneck": "bool",
            "equipment_count": "int",
            "worker_count": "int",
            "status": "option",
        },
        "relation_fields": {
            "line_id": "production_lines",
            "process_id": "process_info",
        },
    },
    "material_masters": {
        "ws_id": "6a2ded70b650d46f3d27acf1",
        "model": MaterialMaster,
        "hap_to_local": {
            "mat_code": "mat_code",
            "mat_name": "mat_name",
            "mat_type": "mat_type",
            "mat_unit": "unit",
            "mat_safety_stock": "safety_stock",
            "mat_stock_qty": "stock_qty",
            "mat_in_transit": "in_transit",
            "mat_status": "status",
        },
        "local_to_hap": {
            "mat_code": "mat_code",
            "mat_name": "mat_name",
            "mat_type": "mat_type",
            "unit": "mat_unit",
            "safety_stock": "mat_safety_stock",
            "stock_qty": "mat_stock_qty",
            "in_transit": "mat_in_transit",
            "status": "mat_status",
        },
        "field_types": {
            "mat_code": "str",
            "mat_name": "str",
            "mat_type": "option",
            "unit": "option",
            "safety_stock": "int",
            "stock_qty": "int",
            "in_transit": "int",
            "status": "option",
        },
        "relation_fields": {},
    },
    "process_boms": {
        "ws_id": "6a2ded70d541405963b3b308",
        "model": ProcessBOM,
        "hap_to_local": {
            "pb_product": "product_id",
            "pb_process": "process_id",
            "pb_material": "material_id",
            "pb_unit_qty": "unit_qty",
            "pb_reusable": "reusable",
            "pb_remark": "remark",
        },
        "local_to_hap": {
            "product_id": "pb_product",
            "process_id": "pb_process",
            "material_id": "pb_material",
            "unit_qty": "pb_unit_qty",
            "reusable": "pb_reusable",
            "remark": "pb_remark",
        },
        "field_types": {
            "product_id": "relation",
            "process_id": "relation",
            "material_id": "relation",
            "unit_qty": "float",
            "reusable": "bool",
            "remark": "str",
        },
        "relation_fields": {
            "product_id": "products",
            "process_id": "process_info",
            "material_id": "material_masters",
        },
    },
    "material_kittings": {
        "ws_id": "6a2ded72ee5a696a850ad8b0",
        "model": MaterialKitting,
        "hap_to_local": {
            "mk_demand_plan": "demand_id",
            "mk_product": "product_id",
            "mk_process": "process_id",
            "mk_material": "material_id",
            "mk_required_qty": "required_qty",
            "mk_available_qty": "available_qty",
            "mk_shortage_qty": "shortage_qty",
            "mk_kitting_date": "kitting_date",
            "mk_kitting_status": "kitting_status",
        },
        "local_to_hap": {
            "demand_id": "mk_demand_plan",
            "product_id": "mk_product",
            "process_id": "mk_process",
            "material_id": "mk_material",
            "required_qty": "mk_required_qty",
            "available_qty": "mk_available_qty",
            "shortage_qty": "mk_shortage_qty",
            "kitting_date": "mk_kitting_date",
            "kitting_status": "mk_kitting_status",
        },
        "field_types": {
            "demand_id": "relation",
            "product_id": "relation",
            "process_id": "relation",
            "material_id": "relation",
            "required_qty": "int",
            "available_qty": "int",
            "shortage_qty": "int",
            "kitting_date": "date",
            "kitting_status": "option",
        },
        "relation_fields": {
            "demand_id": "demand_plans",
            "product_id": "products",
            "process_id": "process_info",
            "material_id": "material_masters",
        },
    },
    "demand_plans": {
        "ws_id": "6a2ded7488359ed358a4faf4",
        "model": DemandPlan,
        "hap_to_local": {
            "dp_code": "dp_code",
            "dp_product": "product_id",
            "dp_quantity": "quantity",
            "dp_unit": "unit",
            "dp_due_date": "due_date",
            "dp_priority": "priority",
            "dp_status": "status",
            "dp_scheduled_qty": "scheduled_qty",
            "dp_completed_qty": "completed_qty",
            "dp_remark": "remark",
        },
        "local_to_hap": {
            "dp_code": "dp_code",
            "product_id": "dp_product",
            "quantity": "dp_quantity",
            "unit": "dp_unit",
            "due_date": "dp_due_date",
            "priority": "dp_priority",
            "status": "dp_status",
            "scheduled_qty": "dp_scheduled_qty",
            "completed_qty": "dp_completed_qty",
            "remark": "dp_remark",
        },
        "field_types": {
            "dp_code": "str",
            "product_id": "relation",
            "quantity": "int",
            "unit": "option",
            "due_date": "date",
            "priority": "option",
            "status": "option",
            "scheduled_qty": "int",
            "completed_qty": "int",
            "remark": "str",
        },
        "relation_fields": {
            "product_id": "products",
        },
    },
    "schedule_results": {
        "ws_id": "6a2ded74be69b5a61480b3ac",
        "model": ScheduleResult,
        "hap_to_local": {
            "sr_code": "plan_id",
            "sr_product": "product_id",
            "sr_process": "process_id",
            "sr_line": "line_id",
            "sr_demand_plan": "demand_id",
            "sr_date": "sr_date",
            "sr_time_slot": "sr_time_slot",
            "sr_qty": "sr_quantity",
            "sr_status": "sr_status",
            "sr_seq": "seq",
        },
        "local_to_hap": {
            "plan_id": "sr_code",
            "product_id": "sr_product",
            "process_id": "sr_process",
            "line_id": "sr_line",
            "demand_id": "sr_demand_plan",
            "sr_date": "sr_date",
            "sr_time_slot": "sr_time_slot",
            "sr_quantity": "sr_qty",
            "sr_status": "sr_status",
            "seq": "sr_seq",
        },
        "field_types": {
            "plan_id": "str",
            "product_id": "relation",
            "process_id": "relation",
            "line_id": "relation",
            "demand_id": "relation",
            "sr_date": "date",
            "sr_time_slot": "str",
            "sr_quantity": "int",
            "sr_status": "option",
            "process_code": "str",
            "constraint_type": "option",
            "seq": "int",
            "dependency_type": "option",
            "wait_time": "float",
            "prep_time": "float",
        },
        "relation_fields": {
            "product_id": "products",
            "process_id": "process_info",
            "line_id": "production_lines",
            "demand_id": "demand_plans",
        },
    },
    "resource_calendars": {
        "ws_id": "6a2ded756856d88fae530516",
        "model": ResourceCalendar,
        "hap_to_local": {
            "rc_code": "rc_code",
            "rc_date": "rc_date",
            "rc_is_workday": "is_working",
            "rc_line": "line_id",
            "rc_effective_capacity": "available_capacity",
        },
        "local_to_hap": {
            "rc_code": "rc_code",
            "rc_date": "rc_date",
            "is_working": "rc_is_workday",
            "line_id": "rc_line",
            "available_capacity": "rc_effective_capacity",
        },
        "field_types": {
            "rc_code": "str",
            "rc_date": "date",
            "rc_hour": "int",
            "line_id": "relation",
            "process_id": "relation",
            "available_capacity": "float",
            "is_working": "bool",
        },
        "relation_fields": {
            "line_id": "production_lines",
            "process_id": "process_info",
        },
    },
    "changeover_matrices": {
        "ws_id": "6a2bf82eb650d46f3d1a4f70",
        "model": ChangeoverMatrix,
        "hap_to_local": {
            "from_product": "from_product_id",
            "to_product": "to_product_id",
            "changeover_time": "setup_time",
        },
        "local_to_hap": {
            "from_product_id": "from_product",
            "to_product_id": "to_product",
            "setup_time": "changeover_time",
        },
        "field_types": {
            "from_product_id": "relation",
            "to_product_id": "relation",
            "setup_time": "float",
        },
        "relation_fields": {
            "from_product_id": "products",
            "to_product_id": "products",
        },
    },
    "buffer_configs": {
        "ws_id": "6a2d46fe9e6cd05a84c0ce55",
        "model": BufferConfig,
        "hap_to_local": {
            "bc_process": "process_id",
            "bc_buffer_time": "buffer_time",
        },
        "local_to_hap": {
            "process_id": "bc_process",
            "buffer_time": "bc_buffer_time",
        },
        "field_types": {
            "process_id": "relation",
            "buffer_time": "int",
        },
        "relation_fields": {
            "process_id": "process_info",
        },
    },
    "schedule_plans": {
        "ws_id": "6a2d477a3005b538f6a15913",
        "model": SchedulePlan,
        "hap_to_local": {
            "plan_code": "sp_name",
            "plan_status": "sp_status",
            "total_output": "sp_total_output",
        },
        "local_to_hap": {
            "sp_name": "plan_code",
            "sp_status": "plan_status",
            "sp_total_output": "total_output",
        },
        "field_types": {
            "sp_name": "str",
            "sp_status": "option",
            "sp_start_date": "date",
            "sp_end_date": "date",
            "sp_solver": "option",
            "sp_solve_status": "option",
            "sp_solve_time": "float",
            "sp_task_count": "int",
            "sp_total_output": "int",
        },
        "relation_fields": {},
    },
    "report_work_orders": {
        "ws_id": "6a5a2c9d4c4bdc3b0afb3903",
        "model": ReportWorkOrder,
        "hap_to_local": {
            "rw_code": "rw_code",
            "rw_dispatch": "dispatch_id",
            "rw_product": "product_id",
            "rw_process": "process_id",
            "rw_line": "line_id",
            "rw_date": "rw_date",
            "rw_time_slot": "rw_time_slot",
            "rw_plan_qty": "rw_plan_qty",
            "rw_actual_qty": "rw_actual_qty",
            "rw_defect_qty": "rw_defect_qty",
            "rw_status": "rw_status",
            "rw_remark": "rw_remark",
        },
        "local_to_hap": {
            "rw_code": "rw_code",
            "dispatch_id": "rw_dispatch",
            "product_id": "rw_product",
            "process_id": "rw_process",
            "line_id": "rw_line",
            "rw_date": "rw_date",
            "rw_time_slot": "rw_time_slot",
            "rw_plan_qty": "rw_plan_qty",
            "rw_actual_qty": "rw_actual_qty",
            "rw_defect_qty": "rw_defect_qty",
            "rw_status": "rw_status",
            "rw_remark": "rw_remark",
        },
        "field_types": {
            "rw_code": "str",
            "dispatch_id": "relation",
            "product_id": "relation",
            "process_id": "relation",
            "line_id": "relation",
            "rw_date": "date",
            "rw_time_slot": "str",
            "rw_plan_qty": "int",
            "rw_actual_qty": "int",
            "rw_defect_qty": "int",
            "rw_status": "option",
            "rw_remark": "str",
        },
        "relation_fields": {
            "dispatch_id": "schedule_results",
            "product_id": "products",
            "process_id": "process_info",
            "line_id": "production_lines",
        },
    },
    "process_schedule_orders": {
        "ws_id": "6a58dec5b04c56179567347b",
        "model": ProcessScheduleOrder,
        "hap_to_local": {
            "pso_code": "pso_code",
            "pso_demand_plan": "demand_id",
            "pso_product": "product_id",
            "pso_process": "process_id",
            "pso_seq": "seq",
            "pso_line": "line_id",
            "pso_date": "pso_date",
            "pso_time_slot": "pso_time_slot",
            "pso_quantity": "pso_quantity",
            "pso_completed_qty": "pso_completed_qty",
            "pso_unfinished_qty": "pso_unfinished_qty",
            "pso_status": "pso_status",
            "pso_dependency_type": "dependency_type",
            "pso_wait_time": "wait_time",
        },
        "local_to_hap": {
            "pso_code": "pso_code",
            "demand_id": "pso_demand_plan",
            "product_id": "pso_product",
            "process_id": "pso_process",
            "seq": "pso_seq",
            "line_id": "pso_line",
            "pso_date": "pso_date",
            "pso_time_slot": "pso_time_slot",
            "pso_quantity": "pso_quantity",
            "pso_completed_qty": "pso_completed_qty",
            "pso_unfinished_qty": "pso_unfinished_qty",
            "pso_status": "pso_status",
            "dependency_type": "pso_dependency_type",
            "wait_time": "pso_wait_time",
        },
        "field_types": {
            "pso_code": "str",
            "demand_id": "relation",
            "product_id": "relation",
            "process_id": "relation",
            "seq": "int",
            "line_id": "relation",
            "pso_date": "date",
            "pso_time_slot": "str",
            "pso_quantity": "int",
            "pso_completed_qty": "int",
            "pso_unfinished_qty": "int",
            "pso_status": "option",
            "dependency_type": "option",
            "wait_time": "float",
        },
        "relation_fields": {
            "demand_id": "demand_plans",
            "product_id": "products",
            "process_id": "process_info",
            "line_id": "production_lines",
        },
    },
}

# 同步顺序：先同步基础表，再同步依赖表
SYNC_ORDER = [
    "products",
    "process_info",
    "production_lines",
    "material_masters",
    "changeover_matrices",
    "buffer_configs",
    "schedule_plans",
    "product_processes",
    "line_process_configs",
    "process_boms",
    "demand_plans",
    "material_kittings",
    "resource_calendars",
    "schedule_results",
    "report_work_orders",
    "process_schedule_orders",
]


class SyncService:
    """APS-HAP 双向同步服务，处理本地 PostgreSQL 与 HAP 之间的数据同步。"""

    def __init__(self) -> None:
        self.hap = HAPClient()
        self._ws_structure_cache: dict[str, dict] = {}

    # ── 内部工具方法 ──────────────────────────────────────────────────

    async def _get_ws_structure(self, ws_id: str) -> dict:
        """获取并缓存工作表结构信息。"""
        if ws_id not in self._ws_structure_cache:
            try:
                structure = await self.hap.get_worksheet_structure(ws_id)
                self._ws_structure_cache[ws_id] = structure
            except Exception as e:
                logger.error("获取工作表结构失败，ws_id: {}, 错误: {}", ws_id, e)
                self._ws_structure_cache[ws_id] = {}
        return self._ws_structure_cache[ws_id]

    async def _get_alias_to_control_id(self, ws_id: str) -> dict[str, str]:
        """构建 HAP 字段 alias → controlId 映射。"""
        structure = await self._get_ws_structure(ws_id)
        # HAP V3 返回字段在 data.fields（部分私有部署在 data.controls）
        controls = structure.get("data", {}).get("fields", []) or structure.get("data", {}).get("controls", [])
        return {
            c.get("alias", ""): (c.get("controlId") or c.get("id") or "")
            for c in controls
            if c.get("alias")
        }

    async def _get_option_key_map(self, ws_id: str, alias: str) -> dict[str, str]:
        """获取选项字段的 value→key 映射（用于 push 时将显示值转为 key）。"""
        structure = await self._get_ws_structure(ws_id)
        controls = structure.get("data", {}).get("fields", []) or structure.get("data", {}).get("controls", [])
        # HAP V3 返回 type 为字符串（如 "MultipleSelect"/"SingleSelect"），
        # 也兼容数字类型代码 10/11
        option_type_codes = {10, 11, "MultipleSelect", "SingleSelect", 30, "MultiSelect"}
        for control in controls:
            if control.get("alias") == alias and control.get("type") in option_type_codes:
                options = control.get("options", [])
                return {
                    opt.get("value", ""): opt.get("key", "")
                    for opt in options
                    if opt.get("key") and opt.get("value")
                }
        return {}

    async def _fetch_all_hap_rows(self, ws_id: str) -> list[dict]:
        """从 HAP 分页读取所有行数据。"""
        all_rows: list[dict] = []
        page_index = 1
        while True:
            response = await self.hap.get_rows(
                worksheet_id=ws_id,
                page_index=page_index,
                page_size=HAP_PAGE_SIZE,
            )
            rows = response.get("data", {}).get("rows", [])
            all_rows.extend(rows)
            total = int(response.get("data", {}).get("total", 0))
            if len(all_rows) >= total or not rows:
                break
            page_index += 1
        return all_rows

    @staticmethod
    def _parse_hap_value(value: Any, field_type: str) -> Any:
        """将 HAP 字段值转换为本地 Python 类型。

        HAP 特殊格式：
        - 数值字段返回字符串，需手动转换
        - 选项字段返回 [{"key": "...", "value": "..."}]
        - 关联字段返回 [{"sid": "...", "name": "..."}]
        """
        if value is None:
            return None

        if field_type == "str":
            return str(value) if value else None

        if field_type == "int":
            if isinstance(value, (int, float)):
                return int(value)
            if isinstance(value, str):
                try:
                    return int(float(value.replace(",", "")))
                except (ValueError, TypeError):
                    return None
            return None

        if field_type == "float":
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                try:
                    return float(value.replace(",", ""))
                except (ValueError, TypeError):
                    return None
            return None

        if field_type == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, (int, float)):
                return bool(value)
            if isinstance(value, str):
                return value.lower() in ("true", "1", "是", "yes")
            if isinstance(value, dict):
                return str(value.get("key", value.get("value", ""))).lower() in (
                    "true",
                    "1",
                    "是",
                    "yes",
                )
            return None

        if field_type == "date":
            if isinstance(value, date):
                return value
            if isinstance(value, str) and value:
                try:
                    return datetime.strptime(value[:10], "%Y-%m-%d").date()
                except ValueError:
                    return None
            return None

        if field_type == "option":
            # HAP 选项字段：[{"key": "...", "value": "..."}] 或 {"key": "...", "value": "..."}
            if isinstance(value, list) and value:
                first = value[0]
                if isinstance(first, dict):
                    return first.get("value", first.get("key", ""))
                return str(first)
            if isinstance(value, dict):
                return value.get("value", value.get("key", ""))
            return str(value) if value else None

        if field_type == "relation":
            # HAP 关联字段：[{"sid": "...", "name": "..."}] → 提取 sid（HAP 行 ID）
            if isinstance(value, list) and value:
                first = value[0]
                if isinstance(first, dict):
                    return first.get("sid", "")
                return str(first)
            if isinstance(value, dict):
                return value.get("sid", "")
            return str(value) if value else None

        return str(value) if value else None

    @staticmethod
    def _convert_local_to_hap_value(value: Any, field_type: str) -> Any:
        """将本地 Python 值转换为 HAP 写入格式。"""
        if value is None:
            return None

        if field_type in ("str", "option"):
            return str(value)

        if field_type == "int":
            return str(int(value))

        if field_type == "float":
            return str(float(value))

        if field_type == "bool":
            return str(value).lower()

        if field_type == "date":
            if isinstance(value, date):
                return value.strftime("%Y-%m-%d")
            return str(value)

        if field_type == "relation":
            # 关联字段写入时使用 HAP 行 ID 列表
            if isinstance(value, str) and value:
                return [value]
            return None

        return str(value)

    async def _build_hap_to_local_id_map(
        self, session: AsyncSession, table_name: str
    ) -> dict[str, str]:
        """构建 hap_row_id → local_id 映射（用于 pull 时匹配已有记录）。"""
        mapping = TABLE_HAP_MAP.get(table_name)
        if not mapping:
            return {}
        model = mapping["model"]
        result = await session.execute(
            select(model.hap_row_id, model.id).where(model.hap_row_id.isnot(None))
        )
        return dict(result.all())

    async def _build_local_to_hap_id_map(
        self, session: AsyncSession, table_name: str
    ) -> dict[str, str]:
        """构建 local_id → hap_row_id 映射（用于 push 时查找关联记录的 HAP 行 ID）。"""
        mapping = TABLE_HAP_MAP.get(table_name)
        if not mapping:
            return {}
        model = mapping["model"]
        result = await session.execute(
            select(model.id, model.hap_row_id).where(model.hap_row_id.isnot(None))
        )
        return dict(result.all())

    async def _build_hap_fields_for_push(
        self,
        record: Any,
        local_to_hap: dict[str, str],
        field_types: dict[str, str],
        relation_fields: dict[str, str],
        relation_hap_id_maps: dict[str, dict[str, str]],
        option_key_maps: dict[str, dict[str, str]],
        alias_to_cid: dict[str, str],
    ) -> dict[str, Any]:
        """从本地记录构建 HAP 写入字段字典（使用 controlId 作为 key）。"""
        hap_fields: dict[str, Any] = {}

        for local_col, hap_alias in local_to_hap.items():
            value = getattr(record, local_col, None)
            ftype = field_types.get(local_col, "str")

            # 关联字段：将本地 UUID 转换为 HAP 行 ID
            if ftype == "relation" and value:
                id_map = relation_hap_id_maps.get(local_col, {})
                hap_row_id = id_map.get(str(value))
                if hap_row_id:
                    value = hap_row_id
                else:
                    logger.warning(
                        "关联字段 {} 的本地 ID {} 未找到对应 HAP 行 ID，跳过",
                        local_col,
                        value,
                    )
                    continue

            # 选项字段：将显示值转换为 key
            if ftype == "option" and value is not None:
                key_map = option_key_maps.get(local_col, {})
                key = key_map.get(str(value))
                if key:
                    value = key
                else:
                    logger.debug(
                        "选项字段 {} 的值 '{}' 未找到对应 key，使用原始值",
                        local_col,
                        value,
                    )

            # 转换为 HAP 格式
            hap_value = self._convert_local_to_hap_value(value, ftype)
            if hap_value is not None:
                cid = alias_to_cid.get(hap_alias, hap_alias)
                hap_fields[cid] = hap_value

        return hap_fields

    # ── 公共 API ──────────────────────────────────────────────────────

    async def pull_from_hap(self, table_name: str) -> dict:
        """从 HAP 拉取指定表数据写入本地 DB（全量覆盖策略）。

        1. 从 HAP 分页读取所有行
        2. 对每行数据：
           a. 如果 hap_row_id 匹配到本地记录 → 更新
           b. 如果 hap_row_id 不存在 → 新增
        3. 本地有但 HAP 没有的记录 → 不删除（保留本地数据）
        4. 所有同步记录标记为 synced
        """
        mapping = TABLE_HAP_MAP.get(table_name)
        if not mapping:
            logger.error("未知的表名: {}", table_name)
            return {"table": table_name, "error": "未知表名"}

        ws_id = mapping["ws_id"]
        model = mapping["model"]
        hap_to_local = mapping["hap_to_local"]
        field_types = mapping["field_types"]
        relation_fields = mapping["relation_fields"]

        # 1. 从 HAP 分页读取所有行
        logger.info("开始从 HAP 拉取表 {} 数据", table_name)
        try:
            hap_rows = await self._fetch_all_hap_rows(ws_id)
        except Exception as e:
            logger.error("从 HAP 拉取表 {} 数据失败: {}", table_name, e)
            return {"table": table_name, "error": str(e)}

        logger.info("从 HAP 获取表 {} 共 {} 行", table_name, len(hap_rows))

        # 2. 在 DB 会话中处理数据
        created = 0
        updated = 0
        errors = 0

        async with async_session() as session:
            try:
                # 构建关联表的 hap_row_id → local_id 映射
                relation_id_maps: dict[str, dict[str, str]] = {}
                for local_field, related_table in relation_fields.items():
                    relation_id_maps[local_field] = (
                        await self._build_hap_to_local_id_map(session, related_table)
                    )

                # 构建当前表的 hap_row_id → local_id 映射
                hap_to_local_id_map = await self._build_hap_to_local_id_map(
                    session, table_name
                )

                now = datetime.now()

                for hap_row in hap_rows:
                    # HAP 返回行 ID 的键名是 "rowId"（大写 I）
                    row_id = hap_row.get("rowId") or hap_row.get("rowid", "")
                    if not row_id:
                        logger.warning("HAP 行缺少 rowId，跳过，表: {}", table_name)
                        errors += 1
                        continue

                    fields_data = hap_row

                    try:
                        # 转换字段值
                        local_fields: dict[str, Any] = {}
                        for hap_alias, local_col in hap_to_local.items():
                            raw_value = fields_data.get(hap_alias)
                            ftype = field_types.get(local_col, "str")
                            parsed = self._parse_hap_value(raw_value, ftype)

                            # 关联字段：将 HAP 行 ID 转换为本地 UUID
                            if ftype == "relation" and parsed:
                                id_map = relation_id_maps.get(local_col, {})
                                local_uuid = id_map.get(str(parsed))
                                if local_uuid:
                                    parsed = local_uuid
                                else:
                                    logger.debug(
                                        "关联字段 {} 的 HAP 行 ID {} 未找到本地记录，保留原值",
                                        local_col,
                                        parsed,
                                    )

                            local_fields[local_col] = parsed

                        # 匹配现有记录
                        existing_id = hap_to_local_id_map.get(row_id)

                        if existing_id:
                            # 更新现有记录
                            obj = await session.get(model, existing_id)
                            if obj:
                                for col, val in local_fields.items():
                                    setattr(obj, col, val)
                                obj.hap_row_id = row_id
                                obj.sync_status = SyncStatus.SYNCED
                                obj.synced_at = now
                                updated += 1
                        else:
                            # 新增记录
                            obj = model(
                                **local_fields,
                                hap_row_id=row_id,
                                sync_status=SyncStatus.SYNCED,
                                synced_at=now,
                            )
                            session.add(obj)
                            created += 1

                    except Exception as e:
                        logger.warning(
                            "处理 HAP 行数据失败，表: {}, rowid: {}, 错误: {}",
                            table_name,
                            row_id,
                            e,
                        )
                        errors += 1
                        # 清理事务状态，避免 autoflush 失败影响后续行处理
                        await session.rollback()
                        continue

                await session.commit()

            except Exception as e:
                await session.rollback()
                logger.error("拉取表 {} 数据库操作失败: {}", table_name, e)
                return {"table": table_name, "error": str(e)}

        result = {
            "table": table_name,
            "pulled": len(hap_rows),
            "created": created,
            "updated": updated,
            "errors": errors,
        }
        logger.info("从 HAP 拉取表 {} 完成: {}", table_name, result)
        return result

    async def push_to_hap(self, table_name: str) -> dict:
        """将本地变更推送到 HAP（增量同步）。

        扫描 sync_status != synced 的记录：
        - pending_create → HAP create_row → 更新 hap_row_id → synced
        - pending_update → HAP update_row → synced
        - pending_delete → HAP delete_row → 从本地 DB 删除
        """
        # 仿真模式：通过环境变量 DISABLE_HAP_SYNC=1 禁用HAP同步
        import os
        if os.environ.get("DISABLE_HAP_SYNC", "0") == "1":
            logger.info("HAP同步已禁用（DISABLE_HAP_SYNC=1），跳过表: {}", table_name)
            return {"table": table_name, "skipped": True, "reason": "DISABLE_HAP_SYNC=1"}

        mapping = TABLE_HAP_MAP.get(table_name)
        if not mapping:
            logger.error("未知的表名: {}", table_name)
            return {"table": table_name, "error": "未知表名"}

        ws_id = mapping["ws_id"]
        model = mapping["model"]
        local_to_hap = mapping["local_to_hap"]
        field_types = mapping["field_types"]
        relation_fields = mapping["relation_fields"]

        # 获取 alias → controlId 映射
        alias_to_cid = await self._get_alias_to_control_id(ws_id)

        # 预加载选项字段的 value→key 映射
        option_key_maps: dict[str, dict[str, str]] = {}
        for local_col, ftype in field_types.items():
            if ftype == "option":
                hap_alias = local_to_hap.get(local_col, local_col)
                option_key_maps[local_col] = await self._get_option_key_map(
                    ws_id, hap_alias
                )

        created_count = 0
        updated_count = 0
        deleted_count = 0
        errors = 0

        async with async_session() as session:
            try:
                # 构建关联表的 local_id → hap_row_id 映射
                relation_hap_id_maps: dict[str, dict[str, str]] = {}
                for local_field, related_table in relation_fields.items():
                    relation_hap_id_maps[local_field] = (
                        await self._build_local_to_hap_id_map(session, related_table)
                    )

                # 查询待同步记录
                result = await session.execute(
                    select(model).where(model.sync_status != SyncStatus.SYNCED)
                )
                pending_records = result.scalars().all()

                if not pending_records:
                    await session.commit()
                    return {
                        "table": table_name,
                        "pushed": 0,
                        "created": 0,
                        "updated": 0,
                        "deleted": 0,
                        "errors": 0,
                    }

                logger.info(
                    "表 {} 有 {} 条待同步记录", table_name, len(pending_records)
                )

                for record in pending_records:
                    try:
                        if record.sync_status == SyncStatus.PENDING_CREATE:
                            hap_fields = await self._build_hap_fields_for_push(
                                record,
                                local_to_hap,
                                field_types,
                                relation_fields,
                                relation_hap_id_maps,
                                option_key_maps,
                                alias_to_cid,
                            )
                            response = await self.hap.create_row(
                                worksheet_id=ws_id,
                                fields=hap_fields,
                            )
                            # 保存 HAP 返回的行 ID
                            new_row_id = response.get("data", {})
                            if isinstance(new_row_id, dict):
                                new_row_id = new_row_id.get("id", "")
                            record.hap_row_id = str(new_row_id)
                            record.sync_status = SyncStatus.SYNCED
                            record.synced_at = datetime.now()
                            created_count += 1

                        elif record.sync_status == SyncStatus.PENDING_UPDATE:
                            hap_fields = await self._build_hap_fields_for_push(
                                record,
                                local_to_hap,
                                field_types,
                                relation_fields,
                                relation_hap_id_maps,
                                option_key_maps,
                                alias_to_cid,
                            )
                            if not record.hap_row_id:
                                # hap_row_id 为空时改为创建操作
                                logger.info(
                                    "PENDING_UPDATE 缺少 hap_row_id，改为创建，表: {}, id: {}",
                                    table_name,
                                    record.id,
                                )
                                response = await self.hap.create_row(
                                    worksheet_id=ws_id,
                                    fields=hap_fields,
                                )
                                new_row_id = response.get("data", {})
                                if isinstance(new_row_id, dict):
                                    new_row_id = new_row_id.get("id", "")
                                record.hap_row_id = str(new_row_id) if new_row_id else None
                                record.sync_status = SyncStatus.SYNCED
                                record.synced_at = datetime.now()
                                created_count += 1
                            else:
                                await self.hap.update_row(
                                    worksheet_id=ws_id,
                                    row_id=record.hap_row_id,
                                    fields=hap_fields,
                                )
                                record.sync_status = SyncStatus.SYNCED
                                record.synced_at = datetime.now()
                                updated_count += 1

                        elif record.sync_status == SyncStatus.PENDING_DELETE:
                            if record.hap_row_id:
                                await self.hap.delete_row(
                                    worksheet_id=ws_id,
                                    row_id=record.hap_row_id,
                                )
                            # 删除前先清理关联的 schedule_results 外键引用
                            if table_name == "demand_plans":
                                sr_result = await session.execute(
                                    select(ScheduleResult).where(
                                        ScheduleResult.demand_id == record.id
                                    )
                                )
                                sr_records = sr_result.scalars().all()
                                for sr in sr_records:
                                    await session.delete(sr)
                                if sr_records:
                                    await session.flush()
                                    logger.info(
                                        "级联删除 schedule_results {} 条（demand_id={}）",
                                        len(sr_records), record.id,
                                    )
                            await session.delete(record)
                            deleted_count += 1

                    except Exception as e:
                        logger.warning(
                            "推送记录失败，表: {}, id: {}, status: {}, 错误: {}",
                            table_name,
                            record.id,
                            record.sync_status.value,
                            e,
                        )
                        errors += 1
                        continue

                await session.commit()

            except Exception as e:
                await session.rollback()
                logger.error("推送表 {} 数据库操作失败: {}", table_name, e)
                return {"table": table_name, "error": str(e)}

        result = {
            "table": table_name,
            "pushed": created_count + updated_count + deleted_count,
            "created": created_count,
            "updated": updated_count,
            "deleted": deleted_count,
            "errors": errors,
        }
        logger.info("推送表 {} 到 HAP 完成: {}", table_name, result)
        return result

    async def get_sync_status(self) -> dict:
        """获取各表同步状态统计。

        Returns:
            dict: {table_name: {total: N, synced: N, pending_create: N, ...}}
        """
        status_result: dict[str, dict] = {}

        async with async_session() as session:
            for table_name, mapping in TABLE_HAP_MAP.items():
                model = mapping["model"]

                # 总数
                total_result = await session.execute(
                    select(func.count()).select_from(model)
                )
                total = total_result.scalar() or 0

                # 按状态统计
                status_counts: dict[str, int] = {"total": total}
                for status in SyncStatus:
                    count_result = await session.execute(
                        select(func.count())
                        .select_from(model)
                        .where(model.sync_status == status)
                    )
                    status_counts[status.value] = count_result.scalar() or 0

                status_result[table_name] = status_counts

        return status_result

    async def pull_all(self) -> dict:
        """从 HAP 拉取全部表（按依赖顺序）。"""
        results: dict[str, dict] = {}
        for table_name in SYNC_ORDER:
            results[table_name] = await self.pull_from_hap(table_name)
        return results

    async def push_all_pending(self) -> dict:
        """推送全部待同步数据。"""
        results: dict[str, dict] = {}
        for table_name in SYNC_ORDER:
            results[table_name] = await self.push_to_hap(table_name)
        return results
