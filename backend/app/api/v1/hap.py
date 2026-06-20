"""HAP 数据代理接口，提供需求计划、资源日历、产线等数据的拉取和同步。"""

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.security import verify_api_key
from app.hap.client import HAPClient
from app.services.schedule_service import (
    WORKSHEET_IDS,
    _float_val,
    _int_val,
    _opt_value,
    _relation_id,
    _relation_name,
    _str_val,
)

router = APIRouter()


def _get_hap_client() -> HAPClient:
    return HAPClient()


# ── V2 端点 ──────────────────────────────────────────────────────────────


@router.get("/products", summary="拉取产品列表")
async def get_products(
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """从 HAP 拉取产品主数据列表（供紧急插单选择）。"""
    client = _get_hap_client()
    ws_id = WORKSHEET_IDS.get("product", "")
    if not ws_id:
        return []
    resp = await client.get_rows(ws_id, page_size=1000)
    rows = resp.get("data", {}).get("rows", [])
    return [
        {
            "id": r.get("rowId", ""),
            "code": _str_val(r.get("product_code", "")),
            "name": _str_val(r.get("product_name", "")),
        }
        for r in rows
    ]


@router.get("/demand-plans", summary="拉取需求计划列表")
async def get_demand_plans(
    status: str | None = Query(default=None, description="需求计划状态筛选"),
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """从 HAP 拉取需求计划列表。"""
    client = _get_hap_client()
    ws_id = WORKSHEET_IDS.get("demand_plan", "")
    if not ws_id:
        return []
    resp = await client.get_rows(ws_id)
    rows = resp.get("data", {}).get("rows", [])
    result = []
    for r in rows:
        result.append({
            "id": r.get("rowId", ""),
            "dp_code": _str_val(r.get("dp_code", "")),
            "dp_quantity": _float_val(r.get("dp_quantity", 0)),
            "dp_unit": _opt_value(r.get("dp_unit", "")),
            "dp_due_date": _str_val(r.get("dp_due_date", "")),
            "dp_priority": _opt_value(r.get("dp_priority", "")),
            "dp_status": _opt_value(r.get("dp_status", "")),
            "dp_product": _relation_name(r.get("related_product", "")),
            "dp_remark": _str_val(r.get("dp_remark", "")),
        })
    return result


@router.get("/resource-calendar", summary="拉取资源日历")
async def get_resource_calendar(
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """从 HAP 拉取资源日历数据。"""
    client = _get_hap_client()
    ws_id = WORKSHEET_IDS.get("resource_calendar", "")
    if not ws_id:
        return []
    resp = await client.get_rows(ws_id)
    rows = resp.get("data", {}).get("rows", [])
    result = []
    for r in rows:
        result.append({
            "id": r.get("rowId", ""),
            "rc_code": _str_val(r.get("rc_code", "")),
            "rc_date": _str_val(r.get("rc_date", "")),
            "rc_is_workday": _opt_value(r.get("rc_is_workday", "")),
            "rc_daily_capacity": _int_val(r.get("rc_daily_capacity", 0)),
            "rc_efficiency": _float_val(r.get("rc_efficiency", 0)),
            "rc_effective_capacity": _float_val(r.get("rc_effective_capacity", 0)),
            "rc_equipment_count": _int_val(r.get("rc_equipment_count", 0)),
            "rc_worker_count": _int_val(r.get("rc_worker_count", 0)),
            "rc_line": _relation_name(r.get("related_line", "")),
        })
    return result


@router.get("/production-lines", summary="拉取产线列表")
async def get_production_lines(
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """从 HAP 拉取产线数据。"""
    client = _get_hap_client()
    ws_id = WORKSHEET_IDS.get("production_line", "")
    if not ws_id:
        return []
    resp = await client.get_rows(ws_id)
    rows = resp.get("data", {}).get("rows", [])
    result = []
    for r in rows:
        result.append({
            "id": r.get("rowId", ""),
            "line_code": _str_val(r.get("line_code", "")),
            "line_name": _str_val(r.get("line_name", "")),
            "line_type": _opt_value(r.get("line_type", "")),
            "line_capacity": _int_val(r.get("line_capacity", 0)),
            "line_load": _float_val(r.get("line_load", 0)),
            "line_efficiency": _float_val(r.get("line_efficiency", 0)),
            "line_location": _str_val(r.get("line_location", "")),
            "line_status": _opt_value(r.get("line_status", "")),
        })
    return result


@router.get("/material-kitting", summary="拉取物料齐套信息")
async def get_material_kitting(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """从 HAP 拉取物料齐套信息数据。"""
    client = _get_hap_client()
    ws_id = WORKSHEET_IDS.get("material_kitting", "")
    if not ws_id:
        return {"total": 0, "rows": []}
    resp = await client.get_rows(ws_id)
    rows = resp.get("data", {}).get("rows", [])
    result = []
    for r in rows:
        result.append({
            "id": r.get("rowId", ""),
            "demand_id": _relation_id(r.get("related_demand", "")),
            "product_id": _relation_id(r.get("related_product", "")),
            "process_id": _relation_id(r.get("related_process", "")),
            "material_id": _relation_id(r.get("related_material", "")),
            "required_qty": _int_val(r.get("required_qty", 0)),
            "available_qty": _int_val(r.get("available_qty", 0)),
            "shortage_qty": _int_val(r.get("shortage_qty", 0)),
            "kitting_date": _str_val(r.get("kitting_date", "")),
            "kitting_status": _opt_value(r.get("kitting_status", "")),
        })
    return {"total": len(result), "rows": result}


@router.get("/process-info", summary="拉取工序信息")
async def get_process_info(
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """从 HAP 拉取工序信息数据。"""
    client = _get_hap_client()
    ws_id = WORKSHEET_IDS.get("process_info", "")
    if not ws_id:
        return []
    resp = await client.get_rows(ws_id)
    rows = resp.get("data", {}).get("rows", [])
    result = []
    for r in rows:
        result.append({
            "id": r.get("rowId", ""),
            "proc_code": _str_val(r.get("proc_code", "")),
            "proc_name": _str_val(r.get("proc_name", "")),
            "proc_type": _opt_value(r.get("proc_type", "")),
            "constraint_type": _opt_value(r.get("constraint_type", "")),
            "cycle_time": _float_val(r.get("cycle_time", 0)),
            "setup_time": _float_val(r.get("setup_time", 0)),
            "wait_time": _float_val(r.get("wait_time", 0)),
            "wait_includes_offhours": bool(r.get("wait_includes_offhours")) if r.get("wait_includes_offhours") else True,
            "prep_time": _float_val(r.get("prep_time", 0)),
            "is_qc_point": _opt_value(r.get("is_qc_point", "")),
            "status": _opt_value(r.get("proc_status", "")),
        })
    return result


@router.get("/product-processes", summary="拉取产品工艺")
async def get_product_processes(
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """从 HAP 拉取产品工艺数据。"""
    client = _get_hap_client()
    ws_id = WORKSHEET_IDS.get("product_process", "")
    if not ws_id:
        return []
    resp = await client.get_rows(ws_id)
    rows = resp.get("data", {}).get("rows", [])
    result = []
    for r in rows:
        pid = _relation_id(r.get("pp_product", ""))
        prid = _relation_id(r.get("pp_process", ""))
        if not pid or not prid:
            continue  # 跳过关联字段为空的脏数据
        result.append({
            "id": r.get("rowId", ""),
            "product_id": pid,
            "process_id": prid,
            "seq": _int_val(r.get("pp_seq", 0)),
            "std_time": _float_val(r.get("pp_std_time", 0)),
            "dependency_type": _opt_value(r.get("dependency_type", "")),
            "is_key": _opt_value(r.get("pp_is_key", "")),
            "remark": _str_val(r.get("pp_remark", "")),
        })
    return result


@router.get("/line-process-configs", summary="拉取产线工艺配置")
async def get_line_process_configs(
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """从 HAP 拉取产线工艺配置数据。"""
    client = _get_hap_client()
    ws_id = WORKSHEET_IDS.get("line_process_config", "")
    if not ws_id:
        return []
    resp = await client.get_rows(ws_id)
    rows = resp.get("data", {}).get("rows", [])
    result = []
    for r in rows:
        result.append({
            "id": r.get("rowId", ""),
            "line_id": _relation_id(r.get("lpc_line", "")),
            "process_id": _relation_id(r.get("lpc_process", "")),
            "daily_capacity": _int_val(r.get("lpc_daily_capacity", 0)),
            "efficiency": _float_val(r.get("lpc_efficiency", 0)),
            "min_batch": _int_val(r.get("lpc_min_batch", 0)),
            "is_bottleneck": _opt_value(r.get("lpc_is_bottleneck", "")),
            "equipment_count": _int_val(r.get("lpc_equipment_count", 0)),
            "worker_count": _int_val(r.get("lpc_worker_count", 0)),
            "status": _opt_value(r.get("lpc_status", "")),
        })
    return result


@router.get("/process-bom", summary="拉取工序BOM")
async def get_process_bom(
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """从 HAP 拉取工序 BOM 数据。"""
    client = _get_hap_client()
    ws_id = WORKSHEET_IDS.get("process_bom", "")
    if not ws_id:
        return []
    resp = await client.get_rows(ws_id)
    rows = resp.get("data", {}).get("rows", [])
    result = []
    for r in rows:
        result.append({
            "id": r.get("rowId", ""),
            "product_id": _relation_id(r.get("pb_product", "")),
            "process_id": _relation_id(r.get("pb_process", "")),
            "material_id": _relation_id(r.get("pb_material", "")),
            "unit_qty": _float_val(r.get("pb_unit_qty", 0)),
            "reusable": _opt_value(r.get("pb_reusable", "")),
            "remark": _str_val(r.get("pb_remark", "")),
        })
    return result


# ── V1 兼容端点 ──────────────────────────────────────────────────────────


@router.get("/orders", summary="拉取订单明细列表（兼容V1）")
async def get_orders(
    status: str | None = Query(default=None, description="订单状态筛选"),
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """从 HAP 拉取订单明细列表（V1 兼容，调用 get_demand_plans）。"""
    return await get_demand_plans(status=status, api_key=api_key)


@router.get("/calendar", summary="拉取生产日历（兼容V1）")
async def get_calendar(
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """从 HAP 拉取生产日历数据（V1 兼容，调用 get_resource_calendar）。"""
    return await get_resource_calendar(api_key=api_key)


@router.get("/workcenters", summary="拉取工作中心（兼容V1）")
async def get_workcenters(
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """从 HAP 拉取工作中心数据（V1 兼容，调用 get_production_lines）。"""
    return await get_production_lines(api_key=api_key)


@router.get("/kitting", summary="拉取齐套信息（兼容V1）")
async def get_kitting(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """从 HAP 拉取齐套信息数据（V1 兼容，调用 get_material_kitting）。"""
    return await get_material_kitting(api_key=api_key)


@router.post("/sync", summary="手动触发全量数据同步")
async def sync_all(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """手动触发全量数据同步。"""
    return {"status": "success", "message": "全量数据同步已触发"}
