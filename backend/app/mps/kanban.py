"""工序每日生产任务看板（移植自 mps-web src/kanban.js，121 行）。

从「排产结果 + 工序级产能账本(ledger) + 资源日产能(flux_of)」构建看板数据：
 - 按 (级别/工序/模式) 资源维度，展开每个工单在所选日期当天的生产任务；
 - 含订单号、产品、计划数量、开工/完工时间、执行状态、负荷率、异常预警；
 - 支持按日期、工序、级别、模式筛选；与排产结果同步（每次重算即刷新）。

micro 差异（对齐 JS 语义）：
 - `Math.round` → `js_round`（半上舍入 floor(x+0.5)；Python 内置 round 为银行家舍入，
   如 0.0005*1000 类边界会与 JS 不一致）；
 - `ledger[key][q_idx]` 越界/负值在 JS 取 undefined → {used: 0}；Python 负索引会绕到尾部，
   故显式守卫 `0 <= q_idx < len(rows)`；
 - base 缺省 `date.today()`（本地时区）vs JS `new Date().toISOString()`（UTC）——跨日边界微差；
 - groups 平局按 op 码点序（JS localeCompare 依赖语言环境，中文下可能不同）。
 - 错误分支（无效日期）返回 {base_date, query_date, ok: False, error, tasks, summary, filters}，不含 groups（JS 同构；消费方需空值防护）。
"""
from datetime import date

from app.mps.dates import diff_days, js_round


def parse_res(key):
    """解析资源键 `${level}|${op}|${mode}`（兼容前置分部件 `前置分部件|code`）。"""
    if not key:
        return None
    parts = str(key).split("|")
    if len(parts) >= 3:
        return {"level": parts[0], "op": parts[1], "mode": parts[2]}
    if str(key).startswith("前置分部件"):
        return {"level": "前置", "op": "分部件",
                "mode": (parts[1] if len(parts) > 1 else "") or "-"}
    return {"level": parts[0] or "-", "op": "-", "mode": "-"}


def build_kanban(planned, ledger, flux_of, opts=None):
    """构建看板。

    planned 排产结果（schedule_process_constrained.planned 行）；
    ledger 资源日产能账本 { key: [{used, slots}] }；flux_of 资源日产能 { key: flux }；
    opts { base_date, date, level, op, mode }。
    """
    o = opts or {}
    base = o.get("base_date") or next(
        (r["plan"]["start_date"] for r in planned if r.get("plan") and r["plan"].get("start_date")),
        None) or date.today().isoformat()
    q_date = o.get("date") or base
    q_idx = diff_days(base, q_date)
    if q_idx is None:
        return {"base_date": base, "query_date": q_date, "ok": False, "error": "查询日期无效",
                "tasks": [], "summary": _empty_summary(),
                "filters": {"levels": [], "ops": [], "modes": []}}

    tasks = []
    for r in planned:
        if r.get("error") or not r.get("plan") or not r.get("gantt"):
            continue
        bars = [b for b in (r["gantt"].get("bars") or [])
                if b.get("kind") != "setup" and b.get("res") and b.get("from") and b.get("to")]
        for bar in bars:
            res = parse_res(bar["res"])
            if not res:
                continue
            if o.get("level") and res["level"] != o["level"]:
                continue
            if o.get("op") and res["op"] != o["op"]:
                continue
            if o.get("mode") and res["mode"] != o["mode"]:
                continue
            di = diff_days(base, bar["from"])
            d_end = diff_days(base, bar["to"])
            if di is None or d_end is None:
                continue
            if not (q_idx >= di and q_idx < d_end):
                continue

            flux = flux_of.get(bar["res"])
            flux = 0 if flux is None else flux
            rows = ledger.get(bar["res"]) or []
            cell = rows[q_idx] if 0 <= q_idx < len(rows) else None
            used = (cell or {}).get("used") or 0
            load_rate = used / flux if flux > 0 else None

            delayed = r["plan"].get("judge") == "延期"
            material = bool(r["plan"].get("kit_risk")) or not r["order"].get("kit_date")
            overload = load_rate is not None and load_rate > 1 + 1e-9
            warnings = []
            if overload:
                warnings.append("超负荷")
            if delayed:
                warnings.append("延期")
            if material:
                warnings.append("缺料")
            # 状态梯：超负荷 > 延期 > 缺料 > 正常
            status = "超负荷" if overload else "延期" if delayed else "缺料" if material else "正常"

            tasks.append({
                "level": res["level"], "op": res["op"], "mode": res["mode"], "res": bar["res"],
                "order_no": r["order"].get("order_no"), "product": r["order"].get("product"),
                "code": r["order"].get("code"),
                "qty": r.get("input_qty"),
                "step_std": bar.get("step_std"), "seq": bar.get("seq"),
                "plan_from": bar["from"], "plan_to": bar["to"],
                "status": status, "warnings": warnings,
                "load_rate": None if load_rate is None else js_round(load_rate * 1000) / 1000,
                "used": js_round(used * 100) / 100, "flux": js_round(flux * 100) / 100,
                "strategy": r["plan"].get("strategy_name") or "",
                "kit_date": r["order"].get("kit_date") or "",
                "due_date": r["order"].get("due_date") or "",
                "judge": r["plan"].get("judge") or "",
            })

    summary = {
        "task_count": len(tasks),
        "overload_count": sum(1 for t in tasks if t["status"] == "超负荷"),
        "delayed_count": sum(1 for t in tasks if "延期" in t["warnings"]),
        "material_count": sum(1 for t in tasks if "缺料" in t["warnings"]),
        "resource_count": len({t["res"] for t in tasks}),
        "normal_count": sum(1 for t in tasks if t["status"] == "正常"),
    }

    levels = sorted({t["level"] for t in tasks})
    ops = sorted({t["op"] for t in tasks})
    modes = sorted({t["mode"] for t in tasks})

    by_resource = {}
    for t in tasks:
        by_resource.setdefault(t["res"], []).append(t)
    groups = []
    for k, arr in by_resource.items():
        parts = parse_res(k)
        max_rate = max(0, *[(t["load_rate"] or 0) for t in arr])
        groups.append({"res": k, "level": parts["level"], "op": parts["op"], "mode": parts["mode"],
                       "max_load_rate": js_round(max_rate * 1000) / 1000, "tasks": arr})
    groups.sort(key=lambda g: (-g["max_load_rate"], g["op"]))

    return {"base_date": base, "query_date": q_date, "ok": True,
            "summary": summary, "tasks": tasks, "groups": groups,
            "filters": {"levels": levels, "ops": ops, "modes": modes}}


def _empty_summary():
    return {"task_count": 0, "overload_count": 0, "delayed_count": 0,
            "material_count": 0, "resource_count": 0, "normal_count": 0}
