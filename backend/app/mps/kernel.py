"""MPS 核算内核（移植自 mps-web src/engine.js；口径对齐《SiP产线成套工艺计算逻辑说明书-V1.6》）。

约定：
- 纯函数：输入订单 dict + 上下文 dict（proc_map/route_map/wc_map/params），输出结果 dict；
- 参数一律按数值/枚举语义解析（见 consts.PARAM_DEFS 约定）；
- 结果键名与 mps-web 结果结构保持同构（snake_case），便于逐项对照与后续计划消费；
- 下游消费约定：feature_usage 的 missing=True 时不可使用 usage（Task2 置 thr=None、Task4 load 跳过）；
  required_fields 对重复未映射特征不去重（JS 保真）。

与 engine.js 的已知微观差异（均不在业务数据路径上）：
1) nz(" ")：JS Number(" ")=0；本实现 float(" ") 失败 → 返回默认值；
2) feature_usage 遇非数值串：JS 得 usage=NaN/missing=false；本实现返回 missing=True（更安全的收紧）；
3) pick_mode 的 qty 须为数值（JS 隐式转换，Python 会 TypeError）——调用方先 nz。

相对 engine.js 的字段裁剪（计划 3/5 需要时按需补回）：
- 未移植 features 的 JSON 字符串解析（本系统模型即 JSON dict）；
- 未移植 steps[].id / flux_mean / flux_peak_data（balance.js 有意延后）；
- 未移植 gantt.vapor 与 process.owner/note（owner 可一行透传，计划 3 需要时加；本模型无 note 字段）；
- warnings 文案顺序为 sorted 序（JS 为首现序，纯文案差异）；
- 扩展字段：delivery.buffer_days / delivery.latest_start_date 为本系统新增。
"""
from __future__ import annotations

import math

from app.mps.consts import FEATURE_FIELDS, FEATURE_MAP


def nz(v, d):
    """空值兜底：None/''/不可解析/NaN → 默认值；否则取 float。"""
    if v is None or v == "":
        return d
    try:
        f = float(v)
    except (TypeError, ValueError):
        return d
    return d if math.isnan(f) else f


def ceil_int(v: float) -> int:
    """向上取整（含 1e-9 容差，避免浮点尾差）。移植自 mps-web ceilInt。"""
    return math.ceil(float(v) - 1e-9)


def urgent_cycle(t: float) -> float:
    """加急压缩：ΔT=IF(T≤5,1, IF(T≤10,2,3))；下限 1 天（CHK-CYCLE-003/004）。"""
    dt = 1 if t <= 5 else 2 if t <= 10 else 3
    return max(t - dt, 1)


def ramp_flux_factor(day_index: float, ramp_days: float) -> float:
    """爬坡期第 t 天有效通量系数 = min(1, t/T)（CHK-CYCLE-008；仅产能校验折算用）。

    暂无调用方：待计划 3（排产解码/产能校验）或计划 5 接入。
    """
    t = nz(ramp_days, 0)
    if t <= 0:
        return 1.0
    return min(1.0, nz(day_index, 0) / t)


def required_fields(code: str, route_rows: list[dict]) -> list[dict]:
    """某套工艺选择后需录入的必填特征项（含未映射特征的原样提示）。"""
    steps = sorted((r for r in route_rows if r["code"] == code), key=lambda r: r["seq"])
    keys: set[str] = set()
    for s in steps:
        for k in FEATURE_MAP.get(s.get("feature") or "", []):
            keys.add(k)
    fields = [dict(f, required=True) for f in FEATURE_FIELDS if f["key"] in keys]
    for s in steps:
        feat = s.get("feature") or ""
        if feat and feat not in FEATURE_MAP:
            fields.append({
                "key": feat, "label": feat, "unit": "", "group": "未映射",
                "required": True, "unmapped": True,
            })
    return fields


def pick_mode(wc: dict | None, qty: float) -> dict | None:
    """生产模式分流（CHK-FLUX-009/010/011）：按订单批量与阈值选半自动/自动。

    按名称判定 semi/auto（不依赖 modes 行序——明道云同步后行序不保证）；
    engine.js 在有序输入（半自动在前）下与本实现行为一致。
    """
    if not wc or not wc.get("modes"):
        return None
    modes = wc["modes"]
    if len(modes) == 1:
        return {"mode": modes[0], "mode_name": modes[0].get("mode") or "/"}
    semi = next((m for m in modes if "半自动" in str(m.get("mode", ""))), modes[0])
    auto = next(
        (m for m in modes if "自动" in str(m.get("mode", "")) and "半自动" not in str(m.get("mode", ""))),
        modes[-1],
    )
    threshold = nz(semi.get("split_threshold"), 0)
    chosen = semi if qty < threshold else auto
    return {"mode": chosen, "mode_name": chosen.get("mode") or "/"}


def feature_usage(step: dict, feats: dict) -> dict:
    """工序在某产品下的单只特征用量（CHK-FLUX-014 缺参排除）。"""
    mapped = FEATURE_MAP.get(step.get("feature") or "", [])
    if step.get("feature") == "工单产品数量N":
        return {"key": "N", "usage": 1, "missing": False}
    usage_key = mapped[0] if mapped else None
    if not usage_key:
        return {"key": None, "usage": 1, "missing": True}
    usage = feats.get(usage_key)
    if usage is None or usage == "" or nz(usage, 0) <= 0:
        return {"key": usage_key, "usage": None, "missing": True}
    return {"key": usage_key, "usage": nz(usage, 0), "missing": False}


def conv_factor(step: dict, feats: dict, p: dict) -> float:
    """折算系数（CHK-FLUX-006/007/008/017）：DB 按胶水类型数、WB 按引线类型数。"""
    field = step.get("cf_field")
    if not field or field == "/":
        return 1.0
    feature = str(step.get("feature") or "")
    if field == "DB胶水类型Y_die":
        cnt_key = "Y_die2" if feature.endswith("-2") else "Y_die"
        cnt = nz(feats.get(cnt_key), 1) or 1
        return nz(p.get("cf_db_3") if cnt >= 3 else (p.get("cf_db_2") if cnt == 2 else p.get("cf_db_1")), 1.0)
    cnt_key = "Y_wire2" if feature.endswith("-2") else "Y_wire"
    cnt = nz(feats.get(cnt_key), 1) or 1
    return nz(p.get("cf_wb_3") if cnt >= 3 else (p.get("cf_wb_2") if cnt == 2 else p.get("cf_wb_1")), 1.0)


def _parse_due(due) -> "date | None":
    from datetime import date, datetime

    if due is None or due == "":
        return None
    if isinstance(due, datetime):
        return due.date()
    if isinstance(due, date):
        return due
    try:
        return date.fromisoformat(str(due)[:10])
    except ValueError:
        return None


def _fmt_dt(v) -> str:
    """datetime/date → 'YYYY-MM-DD'；其它值原样或空串（pinned_at 排序键依赖字符串比较）。"""
    from datetime import date, datetime

    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v or ""


def calc_order(order: dict, ctx: dict) -> dict:
    """单条工单完整核算（移植 calcOrder + 参数化扩展）。

    扩展（相对 mps-web）：round_mode（ceil/exact）、order_buffer_days、
    ramp_trigger（first_flag/first_only/all）、wb_auto_flux_override（模块级自动WB通量覆盖）。
    """
    from datetime import timedelta

    proc_map, route_map, wc_map, p = ctx["proc_map"], ctx["route_map"], ctx["wc_map"], ctx["params"]
    proc = proc_map.get(order["code"])
    if not proc:
        raise ValueError(f"未找到成套工艺：{order['code']}")

    feats = order.get("features") or {}
    steps = sorted(route_map.get(order["code"], []), key=lambda r: r["seq"])
    qty = nz(order.get("qty"), 0)
    has_vapor = str(order.get("water_vapor") or "有") != "无"
    is_urgent = str(order.get("order_type")) == "加急"
    vapor_cut = nz(p.get("vapor_cap_cut"), 1)
    is_component = str(order["code"]).startswith("C")
    use_peak = str(p.get("use_peak") or "mean") == "peak"
    round_mode = str(p.get("round_mode") or "ceil")
    buffer_days = nz(p.get("order_buffer_days"), 0)
    ramp_trigger = str(p.get("ramp_trigger") or "first_flag")
    wb_override = nz(p.get("wb_auto_flux_override"), 0)

    # 1. 单件装配周期（封盖水汽调节 + 前置分部件；平行分部件不占周期）
    cycle_sum = 0.0
    step_cycle: list[dict] = []
    for s in steps:
        c = nz(s.get("cycle"), 0)
        adjusted = False
        if not has_vapor and str(s.get("step_std") or "").startswith("封盖") and c > vapor_cut:
            c = vapor_cut
            adjusted = True
        cycle_sum += c
        step_cycle.append({"c": c, "adjusted": adjusted})
    t_base = max(cycle_sum, 1)
    sub_included = nz(proc.get("subpart_cycle"), 0) if proc.get("subpart_mode") == "前置" else 0
    t_base += sub_included
    t_urgent = urgent_cycle(t_base)
    t_used = t_urgent if is_urgent else t_base

    # 2. 成品率 / 装配放量比（组件级可按开关剔除钎焊；CHK-YIELD-001..006）
    y_full, y_ratio = 1.0, 1.0
    yield_chain: list[dict] = []
    for s in steps:
        y = nz(s.get("yield_overall"), 1)
        y_full *= y
        skip = is_component and nz(p.get("exclude_braze_yield"), 0) == 1 and s.get("step_std") == "钎焊"
        if not skip:
            y_ratio *= y
        yield_chain.append({"step": s.get("step_std"), "y": y, "skipped": skip})
    ratio = 1 / y_ratio if y_ratio > 0 else 1
    ratio_full = 1 / y_full if y_full > 0 else 1

    # 3. 投料量（含产出校核迭代；CHK-YIELD-004/005）
    y_eff = y_ratio
    q = ceil_int(qty * ratio)
    guard = 0
    while q * y_eff < qty and guard < 1000:
        q += 1
        guard += 1

    # 4. 产品级通量（CHK-FLUX-002..014；wb_auto_flux_override 覆盖疑点①）
    item: list[dict] = []
    for i, s in enumerate(steps):
        wc_key = f"{s.get('level')}|{s.get('step_std')}"
        wc = wc_map.get(wc_key)
        picked = pick_mode(wc, qty)
        if picked:
            base = nz(picked["mode"].get("flux_peak"), 0) if use_peak else nz(picked["mode"].get("flux_base"), 0)
            # [扩展] 疑点①双档：覆盖同时替换 mean/peak 取值（config 里 wb_auto_flux_override>0 时生效）
            if (wb_override > 0 and s.get("level") == "模块级" and s.get("step_std") == "WB"
                    and picked["mode_name"] == "自动WB"):
                base = wb_override
        else:
            base = 0
        fu = feature_usage(s, feats)
        cf = conv_factor(s, feats, p)
        thr = (base * cf) / fu["usage"] if (not fu["missing"] and (fu["usage"] or 0) > 0) else None
        item.append({
            "seq": s.get("seq"), "step_raw": s.get("step_raw"), "step_std": s.get("step_std"),
            "level": s.get("level"), "wc_key": wc_key,
            "cycle": step_cycle[i]["c"], "cycle_adjusted": step_cycle[i]["adjusted"],
            "y_overall": nz(s.get("yield_overall"), 1), "feature": s.get("feature"),
            "feature_key": fu["key"], "usage": fu["usage"], "missing": fu["missing"],
            "cf": cf, "mode": picked["mode_name"] if picked else "/",
            "flux_base": base, "cf_field": s.get("cf_field"),
            "unit": picked["mode"].get("unit", "") if picked else "",
            "throughput": thr, "days": ceil_int(q / thr) if (thr and thr > 0) else None,
        })

    # 5. 瓶颈工序（取小；缺参与无通量不参与）
    valid = [s for s in item if (not s["missing"]) and (s["throughput"] or 0) > 0]
    bn = min(valid, key=lambda s: s["throughput"]) if valid else None
    for s in item:
        s["is_bottleneck"] = bool(bn is not None and s is bn)
    c_flux = bn["throughput"] if bn else None

    # 6. 批量总装配周期（round_mode 双档；CHK-DELIVERY-002/003）
    if c_flux and c_flux > 0:
        if round_mode == "ceil":
            batch_cycle = t_used + max(0, ceil_int((q - c_flux) / c_flux))
        else:
            batch_cycle = t_used + max(0.0, (q - c_flux) / c_flux)
    else:
        batch_cycle = t_used

    # 7. 爬坡 / 交付周期（CHK-CYCLE-006/007/009、CHK-DELIVERY-004/005/006）
    first_flag = str(order.get("first_flag") or "否")
    triggered = first_flag in ("首单", "复线", "变更首件")
    if ramp_trigger == "all":
        applied = True
    elif ramp_trigger == "first_only":          # 疑点④取值B（CHK-CYCLE-009B）
        applied = first_flag == "首单"
    else:                                       # "first_flag" 默认（疑点④取值A，CHK-CYCLE-009A）
        applied = triggered
    ramp_used = nz(proc.get("ramp_days"), 0) if applied else 0
    delivery_cycle = batch_cycle + ramp_used + buffer_days

    latest_start_date = None
    due = _parse_due(order.get("due_date"))
    if due is not None:
        latest_start_date = (due - timedelta(days=delivery_cycle)).isoformat()

    gantt = build_gantt(item, t_used, batch_cycle, proc, q)
    return {
        "order": {
            "id": order.get("id"), "order_no": order.get("order_no"), "product": order.get("product"),
            "code": order["code"], "order_type": order.get("order_type"), "first_flag": first_flag,
            "water_vapor": "有" if has_vapor else "无", "qty": qty,
            "due_date": order.get("due_date"), "kit_date": order.get("kit_date") or "",
            "priority": order.get("priority"), "remark": order.get("remark"),
            "prio_level": order.get("prio_level") or "", "prio_score": order.get("prio_score"),
            "prio_source": order.get("prio_source") or "auto", "prio_manual": order.get("prio_manual"),
            "pinned": bool(nz(order.get("pinned"), 0)), "pinned_at": _fmt_dt(order.get("pinned_at")),
            "sort_no": order.get("sort_no"), "status": order.get("status") or "正常",
        },
        "process": {"code": proc.get("code"), "name": proc.get("name"), "arch": proc.get("arch")},
        "features": feats,
        "cycle": {"base": t_base, "urgent": t_urgent, "used": t_used, "cycle_sum": cycle_sum,
                  "subpart_included": sub_included},
        "yield": {"full": y_full, "ratio_basis": y_ratio, "chain": yield_chain},
        "ratio": {"used": ratio, "full": ratio_full,
                  "exclude_braze": is_component and nz(p.get("exclude_braze_yield"), 0) == 1},
        "input_qty": q,
        "output_check": {"expected": math.floor(q * y_eff), "needed": qty, "ok": math.floor(q * y_eff) >= qty},
        "steps": item,
        "bottleneck": (
            {"seq": bn["seq"], "step_std": bn["step_std"], "step_raw": bn["step_raw"], "mode": bn["mode"],
             "throughput": bn["throughput"], "flux_base": bn["flux_base"], "cf": bn["cf"],
             "usage": bn["usage"], "feature": bn["feature"]}
            if bn else None
        ),
        "batch": {"batch_cycle": batch_cycle,
                  "bottleneck_days": ceil_int(q / c_flux) if (c_flux and c_flux > 0) else None},
        "ramp": {"days": nz(proc.get("ramp_days"), 0), "used": ramp_used, "triggered": triggered},
        "delivery": {"days": delivery_cycle, "buffer_days": buffer_days, "latest_start_date": latest_start_date},
        "gantt": gantt,
        "warnings": build_warnings(item),
    }


def build_gantt(item: list[dict], t_used: float, batch: float, proc: dict, q: float) -> dict:
    """工序在制窗口与浮动（移植 buildGantt；相对天数）。"""
    n = len(item)
    lead0 = nz(proc.get("subpart_cycle"), 0) if proc.get("subpart_mode") == "前置" else 0
    acc = lead0
    rows = []
    for i, s in enumerate(item):
        rows.append({**s, "idx": i, "earliest_start": acc})
        acc += s["cycle"]
    tail = 0.0
    for i in range(n - 1, -1, -1):
        rows[i]["latest_finish"] = batch - tail
        tail += rows[i]["cycle"]
    bars = []
    for r in rows:
        window = max(r["latest_finish"] - r["earliest_start"], r["cycle"])
        busy = min(max(r["days"] or 1, 1), window)
        bars.append({
            "kind": "step", "seq": r["seq"], "step_std": r["step_std"], "step_raw": r["step_raw"],
            "mode": r["mode"], "earliest_start": r["earliest_start"], "latest_finish": r["latest_finish"],
            "window_days": window, "busy_days": busy, "float_days": window - busy,
            "cycle": r["cycle"], "throughput": r["throughput"], "usage": r["usage"],
            "feature": r["feature"], "is_bottleneck": r["is_bottleneck"],
            "cycle_adjusted": r["cycle_adjusted"],
        })
    if lead0 > 0:
        bars.insert(0, {
            "kind": "subpart", "seq": 0, "step_std": "前置分部件", "step_raw": "前置分部件", "mode": "/",
            "earliest_start": 0, "latest_finish": lead0, "window_days": lead0, "busy_days": lead0,
            "float_days": 0, "cycle": lead0, "throughput": None, "usage": None, "feature": "",
            "is_bottleneck": False, "cycle_adjusted": False,
        })
    return {"batch_days": batch, "lead_days": t_used, "input_qty": q, "bars": bars}


def build_warnings(item: list[dict]) -> list[dict]:
    """缺 BOM 特征 / 工序主数据缺失 提示（CHK-FLUX-014 / CHK-LOAD-010）。"""
    w = []
    missing = [s for s in item if s["missing"]]
    if missing:
        feats = "、".join(sorted({str(s["feature"]) for s in missing}))
        w.append({"level": "error", "text": f"缺少 BOM 特征参数：{feats}，相关工序未参与取小"})
    no_wc = [s for s in item if not s["wc_key"] or (s["flux_base"] or 0) <= 0]
    if no_wc:
        keys = "、".join(sorted({str(s["wc_key"]) for s in no_wc}))
        w.append({"level": "warn", "text": f"工序主数据缺失：{keys}"})
    return w
