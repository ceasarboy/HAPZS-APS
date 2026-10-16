"""可插拔排产策略层（移植自 mps-web src/strategy.js；纯函数，不依赖 schedule/aps）。

设计目标（改造方案 §1）：
 - 将「排产顺序 / 产能分配偏好 / 优化目标」从硬编码中抽出，形成独立的策略注册表 STRATEGIES；
 - 计划员通过参数（opts.strategy）切换策略，无需改动调度内核代码；
 - 每个策略自带：目标函数权重、排序规则 orderFn、产能分配策略 allocPolicy、
    约束说明 constraints、评估指标 metrics，且排产结果可解释、可追溯。

依赖约束（避免循环依赖）：
 - 仅依赖 priority.py（比较器/全序）与 dates.py，不依赖 schedule / aps；
 - 评估指标 strategy_metrics 接收调用方已算好的 weeklyLoad 行，自身不重算产能。
"""
from datetime import date
from functools import cmp_to_key

from app.mps import priority as prio
from app.mps.dates import add_days, diff_days, js_round, to_str

# ---------------------------------------------------------------- 策略内工具
def family_of(r) -> str:
    """工艺族：取 code 第一段（'-' 之前），如 M01-2DS -> M01；同族即同测试治具/程序族。"""
    code = ((r or {}).get("order") or {}).get("code") or ""
    fam = str(code).split("-")[0]
    return fam or "NA"


def workload_of(r) -> float:
    """工单总工艺量（投料量口径，作为产能占用与排序的代理）。"""
    return float((r or {}).get("input_qty") or 0)


def bottleneck_load_of(r):
    """是否存在瓶颈工序，及其瓶颈负荷（投入量 / 瓶颈通量）。"""
    if not r or not r.get("bottleneck"):
        return None
    thr = r["bottleneck"].get("throughput")
    if not (thr and thr > 0) or not ((r.get("input_qty") or 0) > 0):
        return None
    return r["input_qty"] / thr


# ---------------------------------------------------------------- 排序规则
def order_by_priority(results, opts=None) -> list:
    """订单优先级优先（默认）：全序 comparator（置顶→优先级→交期→…）。

    week_days 透传（3B2 修复）：影响第 7 级瓶颈负荷率档位；缺省回 6（3A 口径）。
    """
    return prio.sort_results(results, week_days=prio._num((opts or {}).get("week_days"), 6))


def order_by_due(results, opts=None) -> list:
    """交期优先（EDD）：交期最早者先排，无交期排最后；同交期按全序 comparator 兜底。

    注（评审留痕）：due_buffer_days 对排序无观察效果——交期匀移保持相对序、哨兵日期不动，
    remain 分支为 JS 同源死代码（da==db 时 remain 恒等）。保留参数以对齐配置面，语义决策留计划 3B。
    """
    o = opts or {}
    base = o.get("base_date") or to_str(date.today())
    buf = prio._num(o.get("due_buffer_days"), 0)

    def due_of(r):
        due = r["order"].get("due_date")
        return add_days(due, buf) if due else "9999-12-31"

    def remain(due):
        return diff_days(base, due) if due else None

    def cmp(a, b):
        da, db = due_of(a), due_of(b)
        if da != db:
            return -1 if da < db else 1
        ra, rb = remain(da), remain(db)  # JS 同源死分支（da==db 时恒等）；保留痕迹
        if ra is not None and rb is not None and ra != rb:
            return -1 if ra < rb else 1
        return prio.cmp_result(a, b)

    return sorted(results, key=cmp_to_key(cmp))


def order_by_util(results, opts=None) -> list:
    """产能利用率优先：先排工艺量大者（大件先占产能，减少碎片），同量按交期。"""
    def cmp(a, b):
        wa, wb = workload_of(a), workload_of(b)
        if wa != wb:
            return -1 if wb < wa else 1  # 大单先排，利于紧凑填充产能
        return prio.cmp_result(a, b)

    return sorted(results, key=cmp_to_key(cmp))


def order_by_setup(results, opts=None) -> list:
    """换线换模最少（GT 成组）：同工艺族连续排，族内按交期；族间切换才产生换型。"""
    def cmp(a, b):
        fa, fb = family_of(a), family_of(b)
        if fa != fb:
            return -1 if fa < fb else 1  # 同族聚拢，最小化跨族换型
        da = a["order"].get("due_date") or "9999-12-31"
        db = b["order"].get("due_date") or "9999-12-31"
        if da != db:
            return -1 if da < db else 1
        na = str(a["order"].get("order_no") or "")
        nb = str(b["order"].get("order_no") or "")
        if na != nb:
            return -1 if na < nb else 1
        return prio.cmp_result(a, b)

    return sorted(results, key=cmp_to_key(cmp))


def order_by_bottleneck(results, opts=None) -> list:
    """瓶颈工序优先（拉动式）：先排命中瓶颈的工单，按瓶颈负荷降序，保证瓶颈不被饿死。"""
    def cmp(a, b):
        ba, bb = bottleneck_load_of(a), bottleneck_load_of(b)
        ha, hb = (0 if ba is None else 1), (0 if bb is None else 1)
        if ha != hb:
            return -1 if hb < ha else 1  # 有瓶颈者优先
        if ba is not None and bb is not None and ba != bb:
            return -1 if bb < ba else 1  # 瓶颈负荷高者先排
        da = a["order"].get("due_date") or "9999-12-31"
        db = b["order"].get("due_date") or "9999-12-31"
        if da != db:
            return -1 if da < db else 1
        return prio.cmp_result(a, b)

    return sorted(results, key=cmp_to_key(cmp))


# ---------------------------------------------------------------- 策略注册表
# 每项策略字段（与 strategy.js 逐字对齐）：
#  id / name / desc        —— 标识与说明（前端下拉用）
#  objective               —— 多目标优化权重 {tardy, setup, imbal, makespan}
#  orderFn(results,opts)   —— 返回排序后的工单核算结果数组（处理顺序）
#  allocPolicy             —— 'pack' 紧凑填充（提利用率）| 'nooverlap' 防同资源同日重叠（配合换型建模）
#  constraints             —— 该策略生效的约束集合（用于文档与校验提示）
#  metrics                 —— 该策略侧重关注的评估指标键名
#  tag                     —— UI 标签
STRATEGIES = {
    "priority": {
        "id": "priority", "name": "订单优先级优先", "tag": "默认",
        "desc": "按项目优先级（置顶>手动>自动评分）全序排产，与现状完全一致。适合日常按重要性驱动的排程。",
        "objective": {"tardy": 1, "setup": 2, "imbal": 1, "makespan": 0.1},
        "orderFn": order_by_priority,
        "allocPolicy": "pack",
        "constraints": ["route", "serial", "capacity", "kit", "shift"],
        "metrics": ["onTimeRate", "setup", "imbalance"],
    },
    "due": {
        "id": "due", "name": "交期优先（EDD）", "tag": "准交",
        "desc": "交期最早者最先排（最早交货期优先），最大化准时交付率，适合交付压力大、延期成本高的场景。",
        "objective": {"tardy": 3, "setup": 1, "imbal": 1, "makespan": 0.2},
        "orderFn": order_by_due,
        "allocPolicy": "pack",
        "constraints": ["route", "serial", "capacity", "kit", "shift"],
        "metrics": ["onTimeRate", "tardiness", "maxLate"],
    },
    "util": {
        "id": "util", "name": "产能利用率优先", "tag": "满产",
        "desc": "大工艺量工单优先占产能、紧凑填充，降低设备空闲与负载不均衡；适合产能紧张、追求高设备综合效率（OEE）的场景。",
        "objective": {"tardy": 1, "setup": 1, "imbal": 3, "makespan": 0.05},
        "orderFn": order_by_util,
        "allocPolicy": "pack",
        "constraints": ["route", "serial", "capacity", "kit", "shift"],
        "metrics": ["utilization", "imbalance"],
    },
    "setup": {
        "id": "setup", "name": "换线换模最少（GT 成组）", "tag": "少换型",
        "desc": "按工艺族（测试治具/程序族）聚拢连续排产，仅在族间切换时产生换型，最小化换线换模次数与在制品搬运。",
        "objective": {"tardy": 1, "setup": 4, "imbal": 1, "makespan": 0.1},
        "orderFn": order_by_setup,
        "allocPolicy": "nooverlap",
        "constraints": ["route", "serial", "capacity", "kit", "shift", "setup"],
        "metrics": ["setup", "onTimeRate"],
    },
    "bottleneck": {
        "id": "bottleneck", "name": "瓶颈工序优先（拉动）", "tag": "瓶颈",
        "desc": "优先排程命中瓶颈工序的工单并让瓶颈持续被喂料，避免瓶颈饿死造成整体产出损失；适合瓶颈明显、产出受限的产线。",
        "objective": {"tardy": 1, "setup": 1, "imbal": 2, "makespan": 0.1},
        "orderFn": order_by_bottleneck,
        "allocPolicy": "pack",
        "constraints": ["route", "serial", "capacity", "kit", "shift"],
        "metrics": ["bottleneckUtil", "utilization"],
    },
}

STRATEGY_IDS = list(STRATEGIES.keys())


def get_strategy(id, p=None) -> dict:
    """取策略；非法/缺省回退到 priority（与现状一致）。
    若传入参数表 P，则合并其中 strategy_<id>_<objectiveKey> 覆盖目标函数权重，
    使「策略目标权重」可在线配置并生效（用于策略评估打分与 APS 多目标优化权重）；
    非法值（不可解析/负值）保留原值。"""
    base = STRATEGIES.get(id) or STRATEGIES["priority"]
    if p is None:
        # 加固：返回副本而非注册表本体（防止调用方原地改 objective 污染全局）
        return {**base, "objective": dict(base["objective"])}
    obj = dict(base["objective"])
    for k in obj:
        v = prio._num(p.get("strategy_" + base["id"] + "_" + k), None)
        if v is not None and v >= 0:
            obj[k] = v
    return {**base, "objective": obj}


# ---------------------------------------------------------------- 可配置项 Schema
# 通用目标函数权重 schema（所有策略均可编辑，驱动策略评估打分与 APS 优化权重）
OBJECTIVE_SCHEMA = [
    {"key": "tardy", "label": "准交", "min": 0, "max": 5, "step": 0.1, "hint": "越重视准时交付"},
    {"key": "setup", "label": "少换型", "min": 0, "max": 5, "step": 0.1, "hint": "越重视减少换线换模"},
    {"key": "imbal", "label": "负荷均衡", "min": 0, "max": 5, "step": 0.1, "hint": "越重视各工序负荷均衡"},
    {"key": "makespan", "label": "短工期", "min": 0, "max": 5, "step": 0.1, "hint": "越重视缩短总工期"},
]

# 各策略可调参数 schema（前端据此渲染配置面板；key 即 params 表键名，保存即生效）
STRATEGY_CONFIG_SCHEMA = {
    "priority": [
        {"key": "prio_w_u", "label": "紧急度 U", "group": "评分权重", "min": 0, "max": 1, "step": 0.01, "default": 0.30, "affects": "优先级评分"},
        {"key": "prio_w_b", "label": "瓶颈负荷 B", "group": "评分权重", "min": 0, "max": 1, "step": 0.01, "default": 0.25, "affects": "优先级评分"},
        {"key": "prio_w_k", "label": "齐套 K", "group": "评分权重", "min": 0, "max": 1, "step": 0.01, "default": 0.15, "affects": "优先级评分"},
        {"key": "prio_w_r", "label": "研发 R", "group": "评分权重", "min": 0, "max": 1, "step": 0.01, "default": 0.10, "affects": "优先级评分"},
        {"key": "prio_w_d", "label": "交期 D", "group": "评分权重", "min": 0, "max": 1, "step": 0.01, "default": 0.10, "affects": "优先级评分"},
        {"key": "prio_w_w", "label": "水位 W", "group": "评分权重", "min": 0, "max": 1, "step": 0.01, "default": 0.10, "affects": "优先级评分"},
        {"key": "prio_thr_p0", "label": "P0 阈值", "group": "分级阈值", "min": 0, "max": 100, "step": 1, "default": 80, "unit": "分", "affects": "P0/P1/P2/P3 分级"},
        {"key": "prio_thr_p1", "label": "P1 阈值", "group": "分级阈值", "min": 0, "max": 100, "step": 1, "default": 65, "unit": "分", "affects": "P1/P2/P3 分级"},
        {"key": "prio_thr_p2", "label": "P2 阈值", "group": "分级阈值", "min": 0, "max": 100, "step": 1, "default": 40, "unit": "分", "affects": "P2/P3 分级"},
    ],
    "due": [
        {"key": "due_buffer_days", "label": "交期缓冲天数", "group": "排序规则", "min": 0, "max": 30, "step": 1, "default": 0, "unit": "天", "affects": "交期排序（向后平移，更保守）"},
    ],
    "setup": [
        {"key": "setup_days", "label": "换线换模天数", "group": "换型建模", "min": 0, "max": 5, "step": 0.1, "default": 0.5, "unit": "天", "affects": "换型占用产能"},
    ],
    "util": [],
    "bottleneck": [],
}


def get_strategy_config_values(id, p=None) -> dict:
    """取某策略当前配置值（从参数表 P 合并，缺省回退 schema 默认值）。"""
    schema = STRATEGY_CONFIG_SCHEMA.get(id) or []
    vals = {}
    for f in schema:
        raw = (p or {}).get(f["key"])
        v = prio._num(raw, None) if raw is not None and raw != "" else None
        vals[f["key"]] = f["default"] if v is None else v
    obj = {}
    base = STRATEGIES.get(id) or STRATEGIES["priority"]
    for k in base["objective"]:
        raw = (p or {}).get("strategy_" + id + "_" + k)
        v = prio._num(raw, None) if raw is not None and raw != "" else None
        obj[k] = base["objective"][k] if v is None else v
    return {"fields": vals, "objective": obj}


# ---------------------------------------------------------------- 策略得分
def strategy_score(strat, m):
    """用策略目标函数权重对一组评估指标算「策略契合度」0~100（权重越大越主导打分）。
    使「目标函数权重」这一可配置项在排产结果中真实可见、可对比。"""
    if m is None:
        return None
    o = (strat or {}).get("objective") or {}
    wsum = (o.get("tardy") or 0) + (o.get("setup") or 0) + (o.get("imbal") or 0) + (o.get("makespan") or 0) or 1
    onTime = (m["onTimeRate"] if m.get("onTimeRate") is not None else 0) / 100           # 准交越高越好
    lowSetup = 1 - min(1, (m.get("setupTotal") or 0) / max(1, (m.get("total") or 1) * 0.5))  # 换型越少越好
    balanced = 1 - min(1, (m.get("imbalance") or 0) / 1)                                 # 不均衡σ越小越好
    shortMake = 1 - min(1, (m.get("makespan") or 0) / 60)                                # 工期越短越好（以 60 天为参照）
    return js_round(100 * ((o.get("tardy") or 0) * onTime + (o.get("setup") or 0) * lowSetup
                           + (o.get("imbal") or 0) * balanced + (o.get("makespan") or 0) * shortMake) / wsum)


# ---------------------------------------------------------------- 评估指标
def strategy_metrics(planned, load) -> dict:
    """计算策略维度的评估指标。load 为 weeklyLoad 结果（调用方传入，避免重复核算）。"""
    items = [r for r in planned if not r.get("error")]
    total = len(items)
    late = len([r for r in items if (r.get("plan") or {}).get("judge") == "延期"])
    onTime = len([r for r in items
                  if (r.get("order") or {}).get("due_date")
                  and (r.get("plan") or {}).get("judge")
                  and r["plan"]["judge"] != "延期"])
    rates = [(l or {}).get("load_rate") for l in (load or [])]
    rates = [x for x in rates if x is not None and x > 0]
    mean = sum(rates) / len(rates) if rates else 0
    imbalance = (sum((b - mean) ** 2 for b in rates) / (len(rates) or 1)) ** 0.5
    overloadWC = len([l for l in (load or []) if (l or {}).get("judge") == "超载"])
    setupTotal = sum(
        (b.get("setup_days") or 0)
        for r in items if (r.get("gantt") or {}).get("bars")
        for b in r["gantt"]["bars"] if b.get("setup_days")
    )
    fin = [(r.get("plan") or {}).get("finish_date") for r in items if (r.get("plan") or {}).get("finish_date")]
    # 加固：锚点取首个有 start_date 的非 error 行（JS 用 planned[0]，error 首行时 makespan 塌缩为 0）
    start0 = next(((r.get("plan") or {}).get("start_date") for r in items
                   if (r.get("plan") or {}).get("start_date")), None)
    makespan = max((diff_days(start0 or d, d) or 0) for d in fin) if fin else 0
    # 瓶颈工序利用率 = 最高负荷率的工序
    bottleneckUtil = max(rates) if rates else 0
    utilization = mean
    return {
        "total": total, "late": late, "onTime": onTime,
        "onTimeRate": js_round((onTime / total) * 1000) / 10 if total else None,
        "utilization": js_round(utilization * 1000) / 1000,
        "imbalance": js_round(imbalance * 1000) / 1000,
        "overloadWC": overloadWC,
        "setupTotal": js_round(setupTotal * 1000) / 1000,
        "makespan": makespan,
        "bottleneckUtil": js_round(bottleneckUtil * 1000) / 1000,
    }
