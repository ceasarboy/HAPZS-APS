"""项目（工单）优先级纯计算层（移植自 mps-web src/priority.js；不写库）。

职责边界：评分/分级/映射/排序/重算建议/拖拽落位计算；
落库与日志由 app.mps.priority_service 负责（对应 mps-web server.js 编排）。
micro 差异见计划 3A 文档「约定差异」表。
"""
import math
from datetime import date
from functools import cmp_to_key, partial

from app.mps.dates import add_days, diff_days, js_round as _js_round, to_date, to_str  # noqa: F401（与 JS 同模块自持语义）

DEFAULTS = {
    "prio_w_u": 0.30, "prio_w_b": 0.25, "prio_w_k": 0.15, "prio_w_r": 0.10, "prio_w_d": 0.10, "prio_w_w": 0.10,
    "prio_thr_p0": 80, "prio_thr_p1": 65, "prio_thr_p2": 40,
    "prio_urgent_bonus": 40, "prio_first_bonus": 15,
}

LEVELS = [
    {"level": "P0", "lo": 1, "hi": 99, "label": "特急"},
    {"level": "P1", "lo": 100, "hi": 299, "label": "高"},
    {"level": "P2", "lo": 300, "hi": 599, "label": "中"},
    {"level": "P3", "lo": 600, "hi": 999, "label": "低"},
]
PINNED_PRIORITY = 0
FIRST_FLAGS = ["首单", "复线", "变更首件"]


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _num(v, default):
    """数值解析：None/''/非法/NaN → 默认值（JS Number 语义 + 安全兜底）。"""
    if v is None or v == "":
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def cfg_of(p=None) -> dict:
    """读取权重/阈值配置；权重和不为 1 时强制归一化。"""
    p = p or {}
    c = {k: _num(p.get(k), v) for k, v in DEFAULTS.items()}
    s = c["prio_w_u"] + c["prio_w_b"] + c["prio_w_k"] + c["prio_w_r"] + c["prio_w_d"] + c["prio_w_w"]
    if s > 0 and abs(s - 1) > 1e-9:
        for k in ("prio_w_u", "prio_w_b", "prio_w_k", "prio_w_r", "prio_w_d", "prio_w_w"):
            c[k] = c[k] / s
    c["week_days"] = _num(p.get("week_days"), 6)
    return c


def bottleneck_rate(calc, cfg) -> float:
    """瓶颈资源占用率代理口径（0~1）：占用天数 / 可用天数。"""
    if not calc:
        return 0.0
    if calc.get("bottleneck_load_rate") is not None:
        return clamp(_num(calc.get("bottleneck_load_rate"), 0), 0, 1)
    bn = calc.get("bottleneck")
    if not bn or not (_num(bn.get("throughput"), 0) > 0) or not (_num(calc.get("input_qty"), 0) > 0):
        return 0.0
    days = math.ceil(_num(calc.get("input_qty"), 0) / _num(bn.get("throughput"), 1))  # 守卫下不可达，防御性
    return clamp(days / max(1, _num(cfg.get("week_days"), 6)), 0, 1)


def score_factors(order, calc, cfg, today) -> dict:
    """6 因子评分（各因子 0~100）：U 交期 .30｜B 缓冲 .25｜K 齐套 .15｜R 资源 .10｜D 依赖 .10｜W 加权 .10。

    因子键名 U/B/…/deliveryDays/latestStart/isFirst 与 priority.js 一一对应，勿改 snake_case。
    """
    o = order or {}
    due = o.get("due_date") or ""
    kit = o.get("kit_date") or ""
    remain = diff_days(today, due) if due else None
    delivery_days = _num((calc or {}).get("delivery", {}).get("days"), 0) if calc else 0
    latest_start = add_days(due, -delivery_days) if (due and delivery_days > 0) else None

    if remain is None:
        u = 20
    elif remain < 0:
        u = 100
    else:
        u = clamp(100 - remain * 3, 10, 100)

    if remain is None or delivery_days <= 0:
        b = 50
    else:
        slack = remain / delivery_days
        b = 100 if slack < 1 else 80 if slack < 1.2 else 60 if slack < 1.5 else 40 if slack < 2 else 20

    if not kit:
        k = 30
    elif latest_start and diff_days(latest_start, kit) > 0:
        k = 100
    elif diff_days(today, kit) > 0:
        k = 60
    else:
        k = 0

    r = clamp(bottleneck_rate(calc, cfg) * 100, 0, 100)

    is_first = str(o.get("first_flag") or "否") in FIRST_FLAGS
    d = 30 if (not kit or k >= 100) else (80 if is_first else 50)

    w = 0.0
    if "加急" in str(o.get("order_type") or ""):
        w += cfg["prio_urgent_bonus"]
    if is_first:
        w += cfg["prio_first_bonus"]
    w = clamp(w, 0, 100)

    score = clamp(
        cfg["prio_w_u"] * u + cfg["prio_w_b"] * b + cfg["prio_w_k"] * k
        + cfg["prio_w_r"] * r + cfg["prio_w_d"] * d + cfg["prio_w_w"] * w,
        0, 100,
    )
    return {"U": u, "B": b, "K": k, "R": r, "D": d, "W": w,
            "score": _js_round(score * 10) / 10,
            "remain": remain, "deliveryDays": delivery_days, "latestStart": latest_start, "isFirst": is_first}


def level_of(f, order, cfg) -> str:
    """分级判定：逾期/加急直进 P0，其余按阈值。"""
    o = order or {}
    if f.get("remain") is not None and f["remain"] < 0:
        return "P0"
    if "加急" in str(o.get("order_type") or ""):
        return "P0"
    score = _num(f.get("score"), 0)
    if score >= cfg["prio_thr_p0"]:
        return "P0"
    if score >= cfg["prio_thr_p1"]:
        return "P1"
    if score >= cfg["prio_thr_p2"]:
        return "P2"
    return "P3"


def priority_of(level, score) -> int:
    """级内数值映射：分数越高 → priority 越小（区间不交叉）。"""
    lv = next((x for x in LEVELS if x["level"] == level), LEVELS[3])
    return lv["lo"] + _js_round(((100 - _num(score, 0)) / 100) * (lv["hi"] - lv["lo"]))


def level_info(level):
    return next((x for x in LEVELS if x["level"] == level), None)


def level_of_priority(v) -> str:
    """由 priority 数值反查级别（旧数据/手动值展示）。"""
    n0 = _num(v, None)
    if n0 is None:
        return "P3"
    if n0 <= PINNED_PRIORITY:
        return "P0"
    for lv in LEVELS:
        if lv["lo"] <= n0 <= lv["hi"]:
            return lv["level"]
    return "P0" if n0 < 100 else "P3"


def evaluate(order, calc, cfg=None, today=None) -> dict:
    """单工单评估：分数 → 级别 → priority 数值。"""
    c = cfg or cfg_of()
    t = today or to_str(date.today())
    f = score_factors(order, calc, c, t)
    level = level_of(f, order, c)
    return {"score": f["score"], "level": level, "priority": priority_of(level, f["score"]), "factors": f}


def sort_key(o) -> dict:
    """排序键归一化（空交期 9999-12-31；未拖拽 sort_no=1e9；缺优先级=100）。"""
    x = o or {}
    pr = x.get("priority")
    return {
        "pinned": _num(x.get("pinned"), 0),
        "pinned_at": x.get("pinned_at") or "",
        "priority": _num(pr, 100) if pr is not None else 100,
        "sort_no": 1e9 if x.get("sort_no") is None else _num(x.get("sort_no"), 1e9),
        "due_date": x.get("due_date") or "9999-12-31",
        "delivery_days": 1e9 if x.get("delivery_days") is None else _num(x.get("delivery_days"), 1e9),
        "bottleneck_rate": _num(x.get("bottleneck_rate"), 0),
        "order_no": str(x.get("order_no") or ""),
    }


def cmp_order(a, b) -> int:
    """8 级全序比较（置顶→置顶时间→优先级→拖拽序→交期→快单→瓶颈→编号）。"""
    x, y = sort_key(a), sort_key(b)
    if x["pinned"] != y["pinned"]:
        return -1 if x["pinned"] > y["pinned"] else 1          # 1 置顶优先
    if x["pinned"] and x["pinned_at"] != y["pinned_at"]:
        return -1 if x["pinned_at"] < y["pinned_at"] else 1    # 2 先置顶先排
    if x["priority"] != y["priority"]:
        return -1 if x["priority"] < y["priority"] else 1      # 3 数值升序
    if x["sort_no"] != y["sort_no"]:
        return -1 if x["sort_no"] < y["sort_no"] else 1        # 4 拖拽序
    if x["due_date"] != y["due_date"]:
        return -1 if x["due_date"] < y["due_date"] else 1      # 5 交期早
    if x["delivery_days"] != y["delivery_days"]:
        return -1 if x["delivery_days"] < y["delivery_days"] else 1  # 6 快单
    if x["bottleneck_rate"] != y["bottleneck_rate"]:
        return -1 if x["bottleneck_rate"] > y["bottleneck_rate"] else 1  # 7 瓶颈负荷高
    if x["order_no"] != y["order_no"]:
        return -1 if x["order_no"] < y["order_no"] else 1      # 8 编号兜底（码点序）
    return 0


def result_key(r, week_days=6) -> dict:
    o = (r or {}).get("order") or {}
    days = (r or {}).get("delivery", {}).get("days")
    return {
        "pinned": _num(o.get("pinned"), 0),
        "pinned_at": o.get("pinned_at") or "",
        "priority": 100 if o.get("priority") is None else _num(o.get("priority"), 100),
        "sort_no": 1e9 if o.get("sort_no") is None else _num(o.get("sort_no"), 1e9),
        "due_date": o.get("due_date") or "9999-12-31",
        "delivery_days": _num(days, 1e9) if days is not None else 1e9,
        "bottleneck_rate": bottleneck_rate(r, {"week_days": week_days}),
        "order_no": str(o.get("order_no") or ""),
    }


def cmp_result(a, b, week_days=6) -> int:
    return cmp_order(result_key(a, week_days), result_key(b, week_days))


def sort_results(results, week_days=6) -> list:
    return sorted(results, key=cmp_to_key(partial(cmp_result, week_days=week_days)))


def sort_orders(orders) -> list:
    return sorted(orders, key=cmp_to_key(cmp_order))


def recompute_rows(orders, calc_map, cfg, today, opts=None) -> list:
    """批量重算（纯计算）：置顶>手动>自动；自动重算永不静默覆盖手动值。"""
    o2 = opts or {}
    out = []
    for ord_ in orders:
        calc = calc_map.get(str(ord_.get("order_no"))) or None
        ev = evaluate(ord_, calc, cfg, today)
        cur = 100 if ord_.get("priority") is None else _num(ord_.get("priority"), 100)
        source = ord_.get("prio_source") or "auto"
        is_pinned = _num(ord_.get("pinned"), 0)
        target, applied, skip = ev["priority"], True, ""
        if is_pinned:
            target, applied, skip = cur, False, "已置顶，保持不变"
        elif source == "manual" and not o2.get("force"):
            target, applied, skip = cur, False, "手动值，仅给建议"
        cur_level = ord_.get("prio_level") or level_of_priority(cur)
        out.append({
            "id": ord_.get("id"), "order_no": ord_.get("order_no"),
            "score": ev["score"], "level": ev["level"], "priority": target,
            "cur_priority": cur, "cur_level": cur_level,
            "source": source, "suggest_diff": ev["level"] if cur_level != ev["level"] else "",
            "factors": ev["factors"], "applied": applied, "skipReason": skip,
            "changed": applied and abs(target - cur) > 1e-9,
        })
    return out


def reorder_target(order, prev, next_, to_pinned) -> dict:
    """拖拽落位计算（小数索引：置顶组用 sort_no、普通组用 priority）。"""
    def nz_num(v):
        if v is None or v == "":
            return None
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        return f if math.isfinite(f) else None

    if to_pinned:
        a = nz_num((prev or {}).get("sort_no"))
        b = nz_num((next_ or {}).get("sort_no"))
        if a is not None and b is not None:
            s = (a + b) / 2
        elif a is not None:
            s = a + 10
        elif b is not None:
            s = b - 10
        else:
            s = 10
        if a is not None and abs(s - a) < 1e-6:
            s = a + 1
        return {"pinned": 1, "priority": PINNED_PRIORITY, "sort_no": _js_round(s * 1000) / 1000,
                "level": "P0", "source": "pin"}
    a = nz_num((prev or {}).get("priority")) if (prev and not prev.get("pinned")) else None
    b = nz_num((next_ or {}).get("priority")) if (next_ and not next_.get("pinned")) else None
    if a is not None and b is not None:
        p = _js_round((a + b) / 2)
    elif a is not None:
        p = min(9999, a + 10)
    elif b is not None:
        p = max(1, b - 10)
    else:
        p = nz_num(order.get("priority")) if nz_num(order.get("priority")) is not None else 100
    if a is not None and p == a:
        p = a + 1
    if b is not None and p == b:
        p = max(1, b - 1)
    p = _js_round(clamp(p, 1, 9999))
    return {"pinned": 0, "priority": p, "sort_no": None, "level": level_of_priority(p), "source": "manual"}
