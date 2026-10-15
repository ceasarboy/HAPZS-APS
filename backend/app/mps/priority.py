"""项目（工单）优先级纯计算层（移植自 mps-web src/priority.js；不写库）。

职责边界：评分/分级/映射/排序/重算建议/拖拽落位计算；
落库与日志由 app.mps.priority_service 负责（对应 mps-web server.js 编排）。
micro 差异见计划 3A 文档「约定差异」表。
"""
import math

from app.mps.dates import add_days, diff_days, to_date, to_str  # noqa: F401（与 JS 同模块自持语义）

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


def _js_round(x) -> int:
    return math.floor(float(x) + 0.5)


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
    days = math.ceil(_num(calc.get("input_qty"), 0) / _num(bn.get("throughput"), 1))
    return clamp(days / max(1, _num(cfg.get("week_days"), 6)), 0, 1)


def score_factors(order, calc, cfg, today) -> dict:
    """6 因子评分（各因子 0~100）：U 交期 .30｜B 缓冲 .25｜K 齐套 .15｜R 资源 .10｜D 依赖 .10｜W 加权 .10。"""
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
    t = today or to_str(__import__("datetime").date.today())
    f = score_factors(order, calc, c, t)
    level = level_of(f, order, c)
    return {"score": f["score"], "level": level, "priority": priority_of(level, f["score"]), "factors": f}
