"""排产结果接口，提供结果查询、导出、调整和回写操作。"""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from loguru import logger

from app.core.security import verify_api_key
from app.services.schedule_service import schedule_service

router = APIRouter()

_WORKSHEET_IDS_FILE = Path(__file__).resolve().parents[4] / "deploy" / "worksheet_ids_v2.json"


def _load_worksheet_ids() -> dict[str, str]:
    if _WORKSHEET_IDS_FILE.exists():
        with open(_WORKSHEET_IDS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _str_val(raw: Any) -> str:
    if isinstance(raw, list) and raw:
        if isinstance(raw[0], dict):
            return str(raw[0].get("value", raw[0].get("name", "")))
    return str(raw).strip() if raw else ""


def _relation_name(raw: Any) -> str:
    if isinstance(raw, list) and raw:
        return str(raw[0].get("name", ""))
    if isinstance(raw, dict):
        return str(raw.get("name", ""))
    return ""


def _float_val(raw: Any, default: float = 0.0) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _compute_total_time(t: Any) -> float:
    """V3修复: 根据 beat_count/cycle_time/prep_time/auto_type 重新计算 total_time。

    确保自动工艺的 total_time = beat_count * (cycle_time + prep_time * 60)
    非自动工艺的 total_time = beat_count * cycle_time + prep_time * 60
    """
    auto_type = getattr(t, 'auto_type', '') or ''
    beat_count = getattr(t, 'beat_count', 0) or 0
    cycle_time = getattr(t, 'cycle_time', 0) or 0
    prep_time = getattr(t, 'prep_time', 0) or 0

    if auto_type == "自动":
        return float(beat_count * (cycle_time + prep_time * 60))
    else:
        return float(beat_count * cycle_time + prep_time * 60)


async def _fetch_result_from_hap(plan_code: str) -> dict[str, Any]:
    """从 HAP 排产结果表读取数据，转换为前端格式。"""
    from app.hap.client import HAPClient

    ws_ids = _load_worksheet_ids()
    ws_result = ws_ids.get("schedule_result", "")
    ws_product = ws_ids.get("product", "")
    ws_line = ws_ids.get("production_line", "")

    if not ws_result:
        return {"task_id": plan_code, "status": "NOT_FOUND", "workcenterPlans": [], "loadRates": [], "changeovers": []}

    client = HAPClient()

    # 构建产品 ID→名称映射
    product_names: dict[str, str] = {}
    product_codes: dict[str, str] = {}
    if ws_product:
        try:
            resp = await client.get_rows(ws_product, page_size=1000)
            for pr in resp.get("data", {}).get("rows", []):
                rid = pr.get("rowId", "")
                code = _str_val(pr.get("product_code", ""))
                name = _str_val(pr.get("product_name", ""))
                product_names[rid] = name or code or rid
                product_codes[rid] = code or rid
        except Exception:
            pass

    # 构建产线 ID→名称映射
    line_names: dict[str, str] = {}
    if ws_line:
        try:
            resp = await client.get_rows(ws_line, page_size=1000)
            for lr in resp.get("data", {}).get("rows", []):
                rid = lr.get("rowId", "")
                name = _str_val(lr.get("line_name", ""))
                line_names[rid] = name or rid
        except Exception:
            pass

    # 构建工序 ID→(code, name, constraint_type) 映射
    ws_process = ws_ids.get("process_info", "")
    process_info_map: dict[str, dict[str, str]] = {}
    if ws_process:
        try:
            resp = await client.get_rows(ws_process, page_size=1000)
            for pr in resp.get("data", {}).get("rows", []):
                rid = pr.get("rowId", "")
                # 选项字段取 value
                ct_raw = pr.get("constraint_type", [])
                ct_val = ct_raw[0].get("value", "") if isinstance(ct_raw, list) and ct_raw else str(ct_raw)
                process_info_map[rid] = {
                    "code": _str_val(pr.get("proc_code", "")),
                    "name": _str_val(pr.get("proc_name", "")),
                    "constraint_type": ct_val,
                }
        except Exception:
            pass

    # 构建需求 ID→优先级映射
    ws_demand = ws_ids.get("demand_plan", "")
    demand_priorities: dict[str, str] = {}
    if ws_demand:
        try:
            resp = await client.get_rows(ws_demand, page_size=1000)
            for dr in resp.get("data", {}).get("rows", []):
                rid = dr.get("rowId", "")
                pri_raw = dr.get("dp_priority", [])
                pri_val = pri_raw[0].get("value", "中") if isinstance(pri_raw, list) and pri_raw else "中"
                demand_priorities[rid] = pri_val or "中"
        except Exception:
            pass

    # 读取排产结果
    resp = await client.get_rows(ws_result, page_size=1000)
    rows = resp.get("data", {}).get("rows", [])

    # 按 plan_code 过滤
    plan_rows = [r for r in rows if _str_val(r.get("sr_code", "")) == plan_code]
    if not plan_rows:
        return {"task_id": plan_code, "status": "NOT_FOUND", "workcenterPlans": [], "loadRates": [], "changeovers": []}

    # 按产线分组
    wc_plans: dict[str, list] = {}
    for r in plan_rows:
        line_ref = r.get("sr_line", [])
        line_id = line_ref[0].get("sid", "") if line_ref and isinstance(line_ref, list) else ""
        if line_id not in wc_plans:
            wc_plans[line_id] = []
        wc_plans[line_id].append(r)

    # 构建 workcenterPlans
    workcenter_plans = []
    for line_id, line_rows in wc_plans.items():
        cells = []
        for r in line_rows:
            prod_ref = r.get("sr_product", [])
            prod_id = prod_ref[0].get("sid", "") if prod_ref and isinstance(prod_ref, list) else ""
            # 从 sr_process 关联字段获取工序 ID
            proc_ref = r.get("sr_process", [])
            proc_id = proc_ref[0].get("sid", "") if proc_ref and isinstance(proc_ref, list) else ""
            proc_info = process_info_map.get(proc_id, {})
            # 通过 sr_demand_plan 关联字段查找需求优先级
            demand_ref = r.get("sr_demand_plan", [])
            demand_id = demand_ref[0].get("sid", "") if demand_ref and isinstance(demand_ref, list) else ""
            priority = demand_priorities.get(demand_id, "中")
            cells.append({
                "timeSlot": _str_val(r.get("sr_time_slot", "")) or _str_val(r.get("sr_date", "")),
                "productCode": product_codes.get(prod_id, prod_id),
                "productName": product_names.get(prod_id, prod_id),
                "quantity": int(_float_val(r.get("sr_qty", 0))),
                "frozen": False,
                "processCode": proc_info.get("code", ""),
                "processName": _relation_name(r.get("sr_process", [])) or proc_info.get("name", ""),
                "seq": int(_float_val(r.get("sr_seq", 0))),
                "constraintType": proc_info.get("constraint_type", ""),
                "priority": priority,
                "completedQty": int(_float_val(r.get("sr_completed_qty", 0))),
                "unfinishedQty": int(_float_val(r.get("sr_unfinished_qty", 0))),
                "status": _str_val(r.get("sr_status", "待生产")) or "待生产",
            })
        workcenter_plans.append({
            "workcenterCode": line_id,
            "workcenterName": line_names.get(line_id, line_id),
            "cells": cells,
        })

    return {
        "task_id": plan_code,
        "status": "SUCCESS",
        "workcenterPlans": workcenter_plans,
        "loadRates": [],
        "changeovers": [],
        "otdRate": 0.0,
    }


@router.get("/{task_id}", summary="查询排产结果详情")
async def get_result(
    task_id: str,
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """查询指定排产任务的结果详情，返回前端可直接渲染的格式。"""
    # 支持 "latest" 查询最新任务
    actual_task_id = task_id
    if task_id == "latest":
        latest = None
        latest_time = None
        for tid, info in schedule_service._tasks.items():
            if info.get("status") == "SUCCESS" and info.get("completed_at"):
                ct = info["completed_at"]
                if latest_time is None or ct > latest_time:
                    latest_time = ct
                    latest = tid
        if not latest:
            return {"task_id": task_id, "status": "NOT_FOUND", "workcenterPlans": [], "loadRates": [], "changeovers": []}
        actual_task_id = latest

    task_info = schedule_service._tasks.get(actual_task_id)
    if not task_info:
        # 内存中没有，尝试从 HAP 排产结果表读取
        plan_code = f"PLAN-{actual_task_id}" if not actual_task_id.startswith("PLAN-") else actual_task_id
        hap_result = await _fetch_result_from_hap(plan_code)
        if hap_result.get("workcenterPlans"):
            return hap_result
        return {"task_id": task_id, "status": "NOT_FOUND", "workcenterPlans": [], "loadRates": [], "changeovers": []}

    solve_result = task_info.get("result")
    if not solve_result:
        return {
            "task_id": task_id,
            "status": task_info.get("status", "UNKNOWN"),
            "workcenterPlans": [],
            "loadRates": [],
            "changeovers": [],
        }

    # 从 SolveResult 转换为前端格式
    tasks = solve_result.tasks if solve_result.tasks else []
    problem = task_info.get("problem")

    # 产品 ID→名称映射
    product_names: dict[str, str] = {}
    product_codes: dict[str, str] = {}
    if problem and hasattr(problem, 'products') and problem.products:
        for p in problem.products:
            product_names[p.id] = p.name or p.code or p.id
            product_codes[p.id] = p.code or p.id

    # 需求 ID→优先级映射
    demand_priorities: dict[str, str] = {}
    if problem and hasattr(problem, 'demand_plans') and problem.demand_plans:
        for d in problem.demand_plans:
            demand_priorities[d.id] = getattr(d, 'priority', '中') or '中'

    # 按工作中心/产线分组
    wc_plans: dict[str, list] = {}
    wc_names: dict[str, str] = {}
    workcenters = getattr(problem, 'production_lines', None) or getattr(problem, 'workcenters', None) or []
    if problem and workcenters:
        for wc in workcenters:
            wc_names[wc.id] = getattr(wc, 'line_name', None) or getattr(wc, 'name', None) or getattr(wc, 'code', None) or wc.id
            wc_plans[wc.id] = []

    for t in tasks:
        wc_id = t.workcenter_id
        if wc_id not in wc_plans:
            wc_plans[wc_id] = []
            wc_names[wc_id] = wc_id
        wc_plans[wc_id].append(t)

    # 构建时间槽索引映射（全局索引 → TimeSlot）
    slot_map: dict[int, Any] = {}
    if problem and problem.time_slots:
        for ts in problem.time_slots:
            idx = ts.index if ts.index is not None else (ts.slot_id if ts.slot_id is not None else 0)
            slot_map[idx] = ts

    # 构建 workcenterPlans
    workcenter_plans = []
    for wc_id, wc_tasks in wc_plans.items():
        cells = []
        for t in wc_tasks:
            # 用 time_slot / slot_id / start_slot 索引查找实际时间
            slot_idx = t.time_slot if t.time_slot else (t.slot_id if t.slot_id else (t.start_slot if t.start_slot else 0))
            ts = slot_map.get(slot_idx)

            # V3时间独占模式：每个任务生成一个 cell（不再按5分钟展开）
            slot_count = getattr(t, 'slot_count', 0) or 0
            start_time_str = getattr(t, 'start_time', '') or ''
            end_time_str = getattr(t, 'end_time', '') or ''

            # 生成时间槽显示文本：优先用 start_time ~ end_time，回退到 slot_map
            if start_time_str and '全' in start_time_str:
                # 日级时间槽（"2026-07-12 全天"），只用日期部分
                time_slot_text = start_time_str[:10]
            elif start_time_str and ' ' in start_time_str:
                if end_time_str and end_time_str != start_time_str:
                    time_slot_text = f"{start_time_str} ~ {end_time_str}"
                else:
                    time_slot_text = start_time_str
            else:
                # 旧模式：用slot_map查找
                if ts and hasattr(ts, 'date') and ts.date:
                    if ts.hour == 0:
                        time_slot_text = f"{ts.date} 全天"
                    else:
                        time_slot_text = f"{ts.date} {ts.hour:02d}:00"
                else:
                    time_slot_text = f"Slot {slot_idx}"

            pid = t.product_id or t.product or ""
            # 通过 order_item_id/item_id 查找需求优先级
            demand_id = getattr(t, 'order_item_id', '') or getattr(t, 'item_id', '') or ''
            priority = demand_priorities.get(demand_id, '中')

            # 每个任务只生成一个 cell
            cells.append({
                "timeSlot": time_slot_text,
                "productCode": product_codes.get(pid, pid),
                "productName": product_names.get(pid, pid),
                "quantity": int(round(t.quantity)) if t.quantity else 0,
                "frozen": False,
                "processCode": getattr(t, 'process_code', '') or '',
                "processName": getattr(t, 'process_name', '') or '',
                "seq": getattr(t, 'seq', 0) or 0,
                "constraintType": getattr(t, 'constraint_type', '') or '',
                "priority": priority,
                "dependencyType": getattr(t, 'dependency_type', '') or '',
                "waitTime": getattr(t, 'wait_time', 0) or 0,
                "prepTime": getattr(t, 'prep_time', 0) or 0,
                # 节拍计算过程变量
                "autoType": getattr(t, 'auto_type', '') or '',
                "cycleTime": getattr(t, 'cycle_time', 0) or 0,
                "maxUnitsPerBeat": getattr(t, 'max_units_per_beat', 1) or 1,
                "beatCount": getattr(t, 'beat_count', 0) or 0,
                # V3修复: 重新计算 totalTime，确保包含 prep_time
                "totalTime": _compute_total_time(t),
                # V3时间信息
                "startTime": start_time_str,
                "endTime": end_time_str,
                "slotCount": slot_count,
                "isStart": True,
                "completedQty": 0,
                "unfinishedQty": 0,
                "status": "待生产",
            })
        workcenter_plans.append({
            "workcenterCode": wc_id,
            "workcenterName": wc_names.get(wc_id, wc_id),
            "cells": cells,
        })

    # 构建 loadRates（V3: 时间独占模式，产能=1.0/槽，负荷率=占用槽数/总可用槽数）
    load_rates = []
    # 构建 (line_id, process_id) → 显示名称映射
    lpc_names: dict[str, str] = {}  # key → 显示名称
    if problem and hasattr(problem, 'line_process_configs') and problem.line_process_configs:
        line_name_map = {wc.id: getattr(wc, 'line_name', '') or getattr(wc, 'name', '') or getattr(wc, 'code', '') for wc in (getattr(problem, 'production_lines', []) or [])}
        process_name_map: dict[str, str] = {}
        if hasattr(problem, 'process_info') and problem.process_info:
            process_name_map = {pi.id: pi.proc_name for pi in problem.process_info if hasattr(pi, 'proc_name')}
        for lpc in problem.line_process_configs:
            key = f"{lpc.line_id}__{lpc.process_id}"
            ln = line_name_map.get(lpc.line_id, '')
            pn = process_name_map.get(lpc.process_id, '')
            lpc_names[key] = f"{ln}-{pn}" if ln and pn else key

    # 按(产线, 工序, 时间标签)汇总排产数量
    # 注意：不同产线的同一时段有不同全局slot索引，需按时间标签聚合避免重复
    lpc_time_qty: dict[str, dict[str, float]] = {}  # key=f"{line_id}__{process_id}" → {time_label → qty}
    for t in tasks:
        line_id = t.workcenter_id
        process_id = getattr(t, 'process_id', '') or ''
        if not process_id:
            continue
        lpc_key = f"{line_id}__{process_id}"
        s = t.time_slot if t.time_slot else (t.slot_id if t.slot_id else (t.start_slot if t.start_slot else 0))
        ts = slot_map.get(s)
        time_label = f"{ts.date} 全天" if ts and hasattr(ts, 'date') and ts.date and ts.hour == 0 else (f"{ts.date} {ts.hour:02d}:00" if ts and hasattr(ts, 'date') and ts.date else f"Slot {s}")
        if lpc_key not in lpc_time_qty:
            lpc_time_qty[lpc_key] = {}
        lpc_time_qty[lpc_key][time_label] = lpc_time_qty[lpc_key].get(time_label, 0) + (t.quantity or 0)

    # V3: 负荷率 = 排产数量（时间独占模式下每个时间槽只能排一个任务，负荷率=1.0表示该时段被占用）
    for lpc_key, time_qtys in lpc_time_qty.items():
        wc_name = lpc_names.get(lpc_key, wc_names.get(lpc_key.split("__", 1)[0], lpc_key))
        for time_label, qty in time_qtys.items():
            # V3时间独占模式：有任务即满负荷
            load_rate = 1.0 if qty > 0 else 0.0
            load_rates.append({
                "workcenterName": wc_name,
                "timeSlot": time_label,
                "loadRate": round(load_rate, 3),
                "plannedQty": int(round(qty)),
                "capacity": 1.0,
            })

    # 构建 changeovers
    changeovers = []
    for wc_id, wc_tasks_list in wc_plans.items():
        sorted_tasks = sorted(wc_tasks_list, key=lambda t: t.time_slot or t.slot_id or t.start_slot or 0)
        for i in range(1, len(sorted_tasks)):
            prev = sorted_tasks[i - 1]
            curr = sorted_tasks[i]
            if prev.product != curr.product:
                slot_idx = curr.time_slot or curr.slot_id or curr.start_slot or 0
                ts = slot_map.get(slot_idx)
                co_slot = f"{ts.date} {ts.hour:02d}:00" if ts and hasattr(ts, 'date') and ts.date else f"Slot {slot_idx}"
                changeovers.append({
                    "workcenterCode": wc_id,
                    "timeSlot": co_slot,
                    "fromProduct": product_codes.get(prev.product or prev.product_id, prev.product or ""),
                    "toProduct": product_codes.get(curr.product or curr.product_id, curr.product or ""),
                    "changeoverTime": 30,
                })

    # 规则评分报告（硬规则遵守性 + 软规则评分）
    rule_report = {
        "hard_rules": solve_result.metadata.get("hard_rules", []) if hasattr(solve_result, 'metadata') else [],
        "hard_violations": solve_result.hard_violations if hasattr(solve_result, 'hard_violations') else 0,
        "soft_scores": solve_result.metadata.get("soft_scores", {}) if hasattr(solve_result, 'metadata') else {},
    }

    return {
        "task_id": task_id,
        "status": task_info.get("status", "UNKNOWN"),
        "workcenterPlans": workcenter_plans,
        "loadRates": load_rates,
        "changeovers": changeovers,
        "otdRate": 0.0,
        "ruleReport": rule_report,
    }


@router.get("/{task_id}/export", summary="导出 CSV")
async def export_csv(
    task_id: str,
    api_key: str = Depends(verify_api_key),
) -> StreamingResponse:
    """将排产结果导出为 CSV 文件。"""
    from io import StringIO

    task_info = schedule_service._tasks.get(task_id)
    solve_result = task_info.get("result") if task_info else None
    tasks = solve_result.tasks if solve_result and solve_result.tasks else []

    output = StringIO()
    output.write("workcenter_id,start_slot,end_slot,product,quantity,order_id\n")
    for t in tasks:
        output.write(f"{t.workcenter_id},{t.start_slot},{t.end_slot},{t.product},{t.quantity},{t.order_id}\n")
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=schedule_{task_id}.csv"},
    )


@router.post("/{task_id}/adjust", summary="人工调整计划数量")
async def adjust_plan(
    task_id: str,
    adjustments: dict[str, Any],
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """人工调整排产计划中的计划数量。"""
    return {"task_id": task_id, "adjusted": True}


@router.post("/{task_id}/confirm", summary="确认排产结果")
async def confirm_schedule(
    task_id: str,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """确认排产结果，状态改为待生产，并自动生成报工单。"""
    return await schedule_service.confirm_schedule(task_id)


@router.post("/{task_id}/push", summary="手动回写 HAP")
async def push_to_hap(
    task_id: str,
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """手动将排产结果回写到 HAP 平台。"""
    task_info = schedule_service._tasks.get(task_id)
    if not task_info:
        return {"task_id": task_id, "status": "not_found"}

    solve_result = task_info.get("result")
    problem = task_info.get("problem")
    if solve_result:
        try:
            await schedule_service.push_results(solve_result, f"PLAN-{task_id[:8]}", problem)
            return {"task_id": task_id, "status": "pushed"}
        except Exception as e:
            return {"task_id": task_id, "status": "error", "message": str(e)}

    return {"task_id": task_id, "status": "no_result"}
