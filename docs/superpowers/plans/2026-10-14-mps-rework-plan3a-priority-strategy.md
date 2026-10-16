# MPS 改造 计划 3A/6：优先级与策略层 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 1:1 移植 mps-web 的**优先级引擎**（`priority.js` 383 行：6 因子评分→P0~P3→数值映射→8 级全序比较器→置顶/拖拽/审计/批量撤销）与**可插拔策略层**（`strategy.js` 257 行：5 策略注册表/排序器/指标/得分/配置 schema），并解决计划 2 遗留的"order 优先级透传字段"接口确认。

**Architecture:** 纯计算与持久化分离（对齐 mps-web 职责边界）：`app/mps/priority.py`（纯函数，不写库）+ `app/mps/priority_service.py`（异步 SQLAlchemy 编排：置顶/解除/拖拽/审计日志/批量快照撤销）+ `app/mps/strategy.py`（纯函数）+ 新增共享 `app/mps/dates.py`（日期工具，统一 schedule/priority/strategy 三处重复实现）。计划 3B（排产解码与求解）再消费本层。

**Tech Stack:** Python 3.13.5（内嵌 `offline\runtime\python\python.exe`）、pytest（asyncio auto）、SQLAlchemy 2.0 异步（服务层）；沿用计划 1/2 种子与夹具。

**唯一移植参照（只读）：** `D:\MPS\mps-web\src\priority.js`（383 行）、`src\strategy.js`（257 行）、`src\schedule.js` 的日期工具（19-41 行）。

**check-list 覆盖（本计划负责）：** CHK-PRIO-001~010（PRIO-009 双向同步归计划 4；PRIO-010 疑点保留"阻塞"但实现现全序语义）。

**与 JS 的约定差异（沿用工程惯例，实现时按此处理并留痕）：**
| 项 | JS 行为 | 本实现 |
|---|---|---|
| `Number("")` | 0（有限数，会覆盖缺省） | 空串视为缺省（更安全；`_num` 兜底） |
| `Math.round(0.5)` | 1（半上取整） | `dates.add_days` 用 `floor(x+0.5)` 复刻；`priority_of` 的 `Math.round` 用同法 |
| `localeCompare` | 本地化比较 | Python 码点比较（order_no 为 ASCII 编号，等价；留痕） |
| 结果排序键 `pinned` | `Number(||0)` | `_num` 同语义 |

---

### Task 1: 日期工具（dates.py）

**Files:**
- Create: `backend/app/mps/dates.py`
- Create: `backend/tests/mps/test_mps_dates.py`

- [ ] **Step 1.1: 编写失败测试**

`backend/tests/mps/test_mps_dates.py`：
```python
"""MPS 日期工具：解析/格式化/加天/差天（含 JS Math.round 半上取整复刻）。"""
from app.mps.dates import DAY, add_days, diff_days, to_date, to_str


def test_parse_and_format():
    from datetime import date

    assert to_date("2026-12-31") == date(2026, 12, 31)
    assert to_date("2026-12-31T08:00:00Z") == date(2026, 12, 31)
    assert to_date(date(2026, 1, 2)) == date(2026, 1, 2)
    assert to_date("") is None and to_date(None) is None and to_date("bad") is None
    assert to_str(date(2026, 1, 2)) == "2026-01-02"
    assert to_str(None) == ""


def test_add_days_half_rounding_matches_js():
    # JS Math.round(0.5)=1 → 复刻为 floor(x+0.5)
    assert add_days("2026-01-01", 0.5) == "2026-01-02"
    assert add_days("2026-01-01", 1) == "2026-01-02"
    assert add_days("2026-01-01", -0.5) == "2026-01-01"   # floor(0)=0
    assert add_days("2026-01-01", 2.4) == "2026-01-03"
    assert add_days("bad", 1) == ""


def test_diff_days():
    assert diff_days("2026-12-14", "2026-12-31") == 17
    assert diff_days("2026-12-31", "2026-12-14") == -17
    assert diff_days(None, "2026-01-01") is None
    assert DAY == 86400000
```

- [ ] **Step 1.2: 运行确认失败** → `ModuleNotFoundError: app.mps.dates`

- [ ] **Step 1.3: 创建 `backend/app/mps/dates.py`**

```python
"""MPS 排产日期工具（移植自 mps-web schedule.js:19-41 / priority.js:53-75 的 UTC 日期函数）。

micro 差异：invalid 输入返回 None/''（JS 返回 null/''），语义一致。
"""
import math
from datetime import date, timedelta

DAY = 86400000  # 毫秒常量（对齐 JS；Python 侧仅作文档保留）


def to_date(s):
    """解析 'YYYY-MM-DD...' → date；无效返回 None。"""
    if not s:
        return None
    if isinstance(s, date):
        return s
    try:
        return date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def to_str(d) -> str:
    if not d:
        return ""
    return d.isoformat()


def _js_round(x: float) -> int:
    """JS Math.round 语义：半上取整（floor(x+0.5)）。"""
    return math.floor(float(x) + 0.5)


def add_days(s, n) -> str:
    d = to_date(s)
    if not d:
        return ""
    return (d + timedelta(days=_js_round(n))).isoformat()


def diff_days(a, b):
    """b − a（天）；任一无效返回 None。"""
    da, db = to_date(a), to_date(b)
    if not da or not db:
        return None
    return (db - da).days
```

- [ ] **Step 1.4: 运行确认通过** → `... -m pytest tests/mps/test_mps_dates.py -v`（预期 3 passed）；全量 `... -m pytest tests -q`（预期 108 passed）
- [ ] **Step 1.5: 提交** `feat(mps): 共享日期工具 dates.py（复刻 JS 半上取整）`

---

### Task 2: priority.py 评分与分级（第一批）

**Files:**
- Create: `backend/app/mps/priority.py`
- Create: `backend/tests/mps/test_mps_priority.py`

- [ ] **Step 2.1: 编写失败测试（评分/分级/映射）**

```python
"""优先级纯核心①：6 因子评分 / 分级 / 数值映射（移植 priority.js §2）。"""
import pytest

from app.mps.priority import (
    DEFAULTS, LEVELS, PINNED_PRIORITY, bottleneck_rate, cfg_of, evaluate,
    level_info, level_of, level_of_priority, priority_of, score_factors,
)


def test_cfg_of_defaults_and_normalization():
    c = cfg_of({})
    assert c["prio_w_u"] == 0.30 and c["prio_thr_p0"] == 80 and c["week_days"] == 6
    c2 = cfg_of({"prio_w_u": 0.6, "prio_w_b": 0.6, "prio_w_k": 0, "prio_w_r": 0, "prio_w_d": 0, "prio_w_w": 0})
    assert c2["prio_w_u"] == pytest.approx(0.5) and c2["prio_w_b"] == pytest.approx(0.5)  # 和=1.2 → 归一
    c3 = cfg_of({"prio_w_u": "abc", "week_days": "5"})
    assert c3["prio_w_u"] == 0.30 and c3["week_days"] == 5


def _calc(delivery_days=17.0, throughput=100.0, input_qty=1052):
    return {"delivery": {"days": delivery_days},
            "bottleneck": {"throughput": throughput}, "input_qty": input_qty}


def test_score_factors_overdue_and_urgent():
    f = score_factors({"due_date": "2026-01-01", "order_type": "加急"},
                      _calc(), cfg_of({}), "2026-06-01")
    assert f["U"] == 100 and f["remain"] < 0
    assert f["W"] == 40                       # 加急 +40
    assert level_of(f, {"order_type": "加急"}, cfg_of({})) == "P0"


def test_score_factors_kit_and_dependency():
    # 齐套晚于最晚上线 → K=100、D=30
    f = score_factors({"due_date": "2026-07-01", "kit_date": "2026-07-05", "first_flag": "首单"},
                      _calc(delivery_days=17.0), cfg_of({}), "2026-06-01")
    assert f["K"] == 100 and f["D"] == 30
    # 首单且齐套 OK → D=80、W≥15
    f2 = score_factors({"due_date": "2026-07-01", "kit_date": "2026-06-01", "first_flag": "首单"},
                       _calc(), cfg_of({}), "2026-06-01")
    assert f2["D"] == 80 and f2["W"] == 15 and f2["K"] == 0


def test_score_factors_slack_buckets():
    from app.mps.dates import add_days as add

    base = {"kit_date": "2026-06-01"}
    def B(remain, delivery):
        f = score_factors({**base, "due_date": add("2026-06-01", remain)},
                          _calc(delivery_days=delivery), cfg_of({}), "2026-06-01")
        return f["B"]
    assert B(15, 17) == 100   # slack<1
    assert B(17, 15) == 80    # 1≤slack<1.2（17/15≈1.133）
    assert B(20, 15) == 60    # 1.2≤slack<1.5 (20/15≈1.33)
    assert B(25, 15) == 40    # 1.5≤slack<2 (25/15≈1.67)
    assert B(50, 15) == 20    # slack≥2


def test_level_and_priority_mapping():
    c = cfg_of({})
    assert level_of({"remain": -1, "score": 0}, {}, c) == "P0"
    assert level_of({"remain": 10, "score": 85}, {}, c) == "P0"
    assert level_of({"remain": 10, "score": 70}, {}, c) == "P1"
    assert level_of({"remain": 10, "score": 50}, {}, c) == "P2"
    assert level_of({"remain": 10, "score": 10}, {}, c) == "P3"
    assert priority_of("P0", 100) == 1
    assert priority_of("P0", 0) == 99
    assert priority_of("P1", 100) == 100
    assert priority_of("P2", 50) == 450        # 300 + round(0.5*299)=449.5→450
    assert priority_of("P3", 0) == 999
    assert level_info("P1")["label"] == "高" and level_info("X") is None
    assert level_of_priority(0) == "P0"
    assert level_of_priority(150) == "P1"
    assert level_of_priority(500) == "P2"
    assert level_of_priority(700) == "P3"
    assert level_of_priority(50) == "P0"
    assert level_of_priority(5000) == "P3"
    assert level_of_priority(None) == "P3"


def test_evaluate_end_to_end():
    ev = evaluate({"due_date": "2026-06-10", "kit_date": "2026-06-01", "order_type": "常规"},
                  _calc(delivery_days=17.0), cfg_of({}), "2026-06-01")
    assert set(ev) == {"score", "level", "priority", "factors"}
    assert ev["priority"] == priority_of(ev["level"], ev["score"])
    assert DEFAULTS["prio_thr_p0"] == 80 and PINNED_PRIORITY == 0 and LEVELS[0]["level"] == "P0"
```

**注意**：`test_score_factors_slack_buckets` 的 `add` 已在函数顶部导入（保持自包含可运行）。

- [ ] **Step 2.2: 运行确认失败** → `ModuleNotFoundError: app.mps.priority`

- [ ] **Step 2.3: 创建 `backend/app/mps/priority.py`（第一批）**

```python
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
```

- [ ] **Step 2.4: 运行确认通过** → `... -m pytest tests/mps/test_mps_priority.py -v`（预期 6 passed）；全量（预期 114 passed）
- [ ] **Step 2.5: 提交** `feat(mps): 优先级纯核心①——6因子评分/分级/数值映射`

---

### Task 3: priority.py 排序与重算（第二批）＋ kernel 优先级透传接口

**Files:**
- Modify: `backend/app/mps/priority.py`（追加 sort_key/cmp_order/result_key/cmp_result/sort_results/sort_orders/recompute_rows/reorder_target）
- Modify: `backend/app/mps/kernel.py`（order 透传字段；解决计划 2 遗留）
- Modify: `backend/tests/mps/test_mps_priority.py`（追加）
- Modify: `backend/tests/mps/test_kernel_calc.py`（追加透传测试）
- Modify: `docs/superpowers/plans/2026-10-14-mps-rework-plan2-calc-kernel.md`（kernel 代码块与差异清单镜像同步）

- [ ] **Step 3.0: 评审跟进修正（Task 1+2 遗留，随本任务落地）**

1. `app/mps/dates.py`：`to_date` 增加 datetime 分支（datetime 是 date 子类），顶部 `from datetime import date, datetime`：
```python
    if isinstance(s, datetime):
        return s.date()
    if isinstance(s, date):
        return s
```
   docstring 补记：`to_date("20260102")` 在 Py3.13 被 fromisoformat 接受（JS 正则拒绝）——畸形输入微差；并增加公开别名 `js_round = _js_round  # 公开别名（priority/strategy 复用）`。
2. `test_mps_dates.py` 追加：
```python
def test_datetime_inputs_normalized():
    from datetime import datetime

    dt = datetime(2026, 1, 2, 3, 4, 5)
    assert to_date(dt).isoformat() == "2026-01-02"
    assert to_str(to_date(dt)) == "2026-01-02"
    assert add_days(dt, 1) == "2026-01-03"
    assert diff_days(dt, "2026-01-05") == 3
```
3. `app/mps/priority.py`：顶部 `from datetime import date`，`evaluate` 内联 `__import__("datetime")` 改 `date.today()`；`_js_round` 改从 dates 导入（`from app.mps.dates import js_round as _js_round`，替换本地定义）；`bottleneck_rate` 的 `_num(bn.get("throughput"), 1)` 加注释"守卫下不可达，防御性"；`score_factors` docstring 补一行"因子键名 U/B/…/deliveryDays/latestStart/isFirst 与 priority.js 一一对应，勿改 snake_case"。
4. `test_mps_priority.py` 追加：
```python
def test_evaluate_literal_and_bool_num():
    from app.mps.priority import _num

    ev = evaluate({"due_date": "2026-06-10", "kit_date": "2026-06-01", "order_type": "常规"},
                  _calc(delivery_days=17.0), cfg_of({}), "2026-06-01")
    assert ev["score"] == 74.9 and ev["level"] == "P1" and ev["priority"] == 150
    assert _num(True, 0) == 1.0 and _num(False, 7) == 0.0     # kernel 置顶 bool 透传承重点
```

- [ ] **Step 3.1: 追加失败测试**

`test_mps_priority.py` 追加：
```python
def test_cmp_order_eight_levels():
    from app.mps.priority import cmp_order

    a = {"pinned": 0, "priority": 100, "sort_no": None, "due_date": "2026-07-01", "order_no": "B"}
    b = {"pinned": 1, "pinned_at": "2026-06-01", "priority": 0, "due_date": "2026-12-01", "order_no": "A"}
    assert cmp_order(a, b) > 0                       # 1 置顶优先
    assert cmp_order(b, a) < 0
    p1 = {"pinned": 1, "pinned_at": "2026-06-01", "order_no": "X"}
    p2 = {"pinned": 1, "pinned_at": "2026-06-02", "order_no": "Y"}
    assert cmp_order(p1, p2) < 0                     # 2 先置顶先排
    assert cmp_order({"priority": 100}, {"priority": 200}) < 0   # 3 数值升序
    assert cmp_order({"priority": 100, "sort_no": 1}, {"priority": 100, "sort_no": 2}) < 0  # 4 拖拽序
    assert cmp_order({"priority": 100, "due_date": "2026-07-01"},
                     {"priority": 100, "due_date": "2026-07-02"}) < 0                            # 5 交期早
    assert cmp_order({"priority": 100, "delivery_days": 10},
                     {"priority": 100, "delivery_days": 20}) < 0                                # 6 快单
    assert cmp_order({"priority": 100, "bottleneck_rate": 0.9},
                     {"priority": 100, "bottleneck_rate": 0.1}) < 0                             # 7 瓶颈高
    assert cmp_order({"priority": 100, "order_no": "A"},
                     {"priority": 100, "order_no": "B"}) < 0                                    # 8 编号兜底
    # 默认兜底：空交期 9999-12-31、未拖拽 1e9、缺优先级 100
    k = sort_key({"order_no": "Z"})
    assert k["due_date"] == "9999-12-31" and k["sort_no"] == 1e9 and k["priority"] == 100


def test_sort_stability_shuffled():
    from app.mps.priority import sort_orders

    base = [{"order_no": f"O{i}", "priority": 100 + (i % 3)} for i in range(9)]
    once = [o["order_no"] for o in sort_orders(base)]
    import random
    shuffled = base[:]
    random.Random(7).shuffle(shuffled)
    assert [o["order_no"] for o in sort_orders(shuffled)] == once  # 稳定可复现


def test_result_key_and_cmp_result():
    from app.mps.priority import cmp_result, result_key

    def mk(no, days, thr, qty, due=None, pr=100):
        return {"order": {"order_no": no, "due_date": due, "priority": pr},
                "delivery": {"days": days}, "bottleneck": {"throughput": thr}, "input_qty": qty}
    r1, r2 = mk("A", 10, 100, 100), mk("B", 20, 100, 100)
    assert result_key(r1, week_days=6)["delivery_days"] == 10
    assert cmp_result(r1, r2) < 0                      # 快单优先（第 6 级）
    r3 = mk("C", 10, 100, 600)                         # 瓶颈占用=ceil(600/100)=6 天 → 1.0
    assert result_key(r3, week_days=6)["bottleneck_rate"] == 1.0


def test_recompute_rows_manual_and_pinned():
    from app.mps.priority import recompute_rows

    cfg = cfg_of({})
    orders = [
        {"id": "1", "order_no": "A", "due_date": "2026-06-20", "kit_date": "2026-06-01", "priority": 500, "prio_source": "manual", "pinned": 0},
        {"id": "2", "order_no": "B", "due_date": "2026-06-20", "kit_date": "2026-06-01", "priority": 0, "pinned": 1, "pinned_until": "2026-12-31"},
        {"id": "3", "order_no": "C", "due_date": "2026-01-01", "priority": 800},
    ]
    calc = {"A": _calc(), "B": _calc(), "C": _calc()}
    out = recompute_rows(orders, calc, cfg, "2026-06-01", {})
    assert out[0]["applied"] is False and "手动值" in out[0]["skipReason"] and out[0]["priority"] == 500
    assert out[1]["applied"] is False and out[1]["skipReason"] == "已置顶，保持不变"
    assert out[2]["level"] == "P0" and out[2]["applied"] is True and out[2]["changed"] is True
    forced = recompute_rows(orders, calc, cfg, "2026-06-01", {"force": True})
    assert forced[0]["applied"] is True and forced[0]["priority"] != 500


def test_reorder_target_pinned_and_normal():
    from app.mps.priority import PINNED_PRIORITY, reorder_target

    order = {"priority": 100, "sort_no": None}
    t = reorder_target(order, {"sort_no": 10}, {"sort_no": 20}, True)
    assert t["pinned"] == 1 and t["sort_no"] == 15 and t["priority"] == PINNED_PRIORITY and t["source"] == "pin"
    t2 = reorder_target(order, {"sort_no": 10}, None, True)
    assert t2["sort_no"] == 20                          # a+10
    t3 = reorder_target(order, None, {"sort_no": 10}, True)
    assert t3["sort_no"] == 0                           # b-10
    t4 = reorder_target(order, None, None, True)
    assert t4["sort_no"] == 10                          # 兜底
    t5 = reorder_target(order, {"sort_no": 10}, {"sort_no": 10.0000001}, True)
    assert t5["sort_no"] == 11                          # 碰撞让位 a+1
    n = reorder_target(order, {"priority": 100, "pinned": 0}, {"priority": 200, "pinned": 0}, False)
    assert n["priority"] == 150 and n["pinned"] == 0 and n["source"] == "manual" and n["level"] == "P1"
    n2 = reorder_target(order, None, {"priority": 200, "pinned": 0}, False)
    assert n2["priority"] == 190                        # b-10
    n3 = reorder_target(order, {"priority": 9995, "pinned": 0}, None, False)
    assert n3["priority"] == 9999                       # min(9999, a+10)
    n4 = reorder_target({"priority": 100}, {"priority": 150, "pinned": 0}, {"priority": 150, "pinned": 0}, False)
    assert n4["priority"] == 151                        # 与邻居重合让位


def test_result_key_delivery_none_and_bottleneck_override():
    from app.mps.priority import result_key

    k = result_key({"order": {"order_no": "A"}, "delivery": None, "input_qty": 10}, week_days=6)
    assert k["delivery_days"] == 1e9                      # JS calc.delivery && … 语义
    k2 = result_key({"order": {"order_no": "A"}, "delivery": {"days": 5}, "bottleneck_load_rate": 0.7})
    assert k2["delivery_days"] == 5 and k2["bottleneck_rate"] == 0.7
```

`test_kernel_calc.py` 追加（透传接口）：
```python
def test_order_priority_passthrough():
    """优先级透传字段（计划 3A 接口确认：供 cmp_order/result_key 消费）。"""
    order = _order()
    order.update({"id": "o-1", "prio_level": "P1", "prio_score": 66.6, "prio_source": "manual",
                  "prio_manual": 150, "pinned": True, "pinned_at": "2026-10-01", "sort_no": 2.5, "status": "正常"})
    r = calc_order(order, _ctx_m02_2d())
    o = r["order"]
    assert o["id"] == "o-1" and o["prio_level"] == "P1" and o["prio_score"] == 66.6
    assert o["prio_source"] == "manual" and o["pinned"] is True and o["pinned_at"] == "2026-10-01"
    assert o["sort_no"] == 2.5 and o["status"] == "正常"
    # 缺省：prio_source=auto、pinned=False、sort_no=None
    o2 = calc_order(_order(), _ctx_m02_2d())["order"]
    assert o2["prio_source"] == "auto" and o2["pinned"] is False and o2["sort_no"] is None
    # datetime 归一化：pinned_at 始终为 'YYYY-MM-DD' 字符串（cmp 键依赖字符串比较）
    from datetime import datetime

    o3 = _order()
    o3["pinned_at"] = datetime(2026, 10, 1, 8, 0)
    assert calc_order(o3, _ctx_m02_2d())["order"]["pinned_at"] == "2026-10-01"
    # 字符串布尔防御：pinned='0' → False（同步场景可能传字符串标记）；缺省 pinned_at=""
    o4 = _order()
    o4["pinned"] = "0"
    assert calc_order(o4, _ctx_m02_2d())["order"]["pinned"] is False
    assert calc_order(_order(), _ctx_m02_2d())["order"]["pinned_at"] == ""
```

- [ ] **Step 3.2: 运行确认失败** → 缺函数/字段

- [ ] **Step 3.3: priority.py 追加实现**

```python
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
    days = ((r or {}).get("delivery") or {}).get("days")
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
    return sorted(results, key=_cmp_key_factory(week_days))


def sort_orders(orders) -> list:
    return sorted(orders, key=lambda o: sort_key(o))
```
**实现提示**：`sorted(key=...)` 不能直接用 `cmp_order`；为保持"全序可复现"，用 `functools.cmp_to_key(cmp_result)` 包装（`cmp_result` 传 week_days 用 `functools.partial`）：
```python
from functools import cmp_to_key, partial
def sort_results(results, week_days=6) -> list:
    return sorted(results, key=cmp_to_key(partial(cmp_result, week_days=week_days)))

def sort_orders(orders) -> list:
    return sorted(orders, key=cmp_to_key(cmp_order))
```
（执行者按此实现，删除 `_cmp_key_factory` 占位。）

```python
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
```

- [ ] **Step 3.4: kernel.py 透传字段（+ 计划 2 镜像同步）**

`kernel.calc_order` 的 return 中 `"order"` 块改为（在原字段基础上追加；对齐 engine.js:163-171 + 本模型扩展）；同时新增 `_fmt_dt` 帮助函数（放在 `_parse_due` 附近）保证 `pinned_at` 恒为 `'YYYY-MM-DD'` 字符串（cmp 键依赖字符串比较，禁止 datetime 直通）：
```python
def _fmt_dt(v) -> str:
    """datetime/date → 'YYYY-MM-DD'；其它值原样或空串（pinned_at 排序键依赖字符串比较）。"""
    from datetime import date, datetime

    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return v or ""
```
```python
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
```
同步修改 kernel.py 模块 docstring 的"字段裁剪"清单：删除"未移植 order 的优先级透传字段"一行（改为已透传），并在 `docs/superpowers/plans/2026-10-14-mps-rework-plan2-calc-kernel.md` 的 kernel 代码块与差异清单做相同镜像修改。

- [ ] **Step 3.5: 运行确认通过**
- 定向：`... -m pytest tests/mps/test_mps_priority.py tests/mps/test_kernel_calc.py -v`（预期 12 + 19 passed）
- 全量：`... -m pytest tests -q`（预期 123 passed, 1 skipped：基线 114 + 本任务 9 用例，含质量跟进 +1）
- [ ] **Step 3.6: 提交** `feat(mps): 优先级纯核心②（8级全序/重算/拖拽）+ kernel 优先级透传接口`

---

### Task 4: priority_service.py（持久化编排）

**Files:**
- Create: `backend/app/mps/priority_service.py`
- Create: `backend/tests/mps/test_mps_priority_service.py`

- [ ] **Step 4.1: 编写失败测试（PRIO-005/007/008）**

```python
"""优先级持久化服务：置顶/到期解除/拖拽/审计日志/批量快照撤销。"""
from datetime import date, timedelta

from sqlalchemy import select

from app.models.mps import Order, PriorityBatch, PriorityLog
from app.mps.priority_service import (
    create_batch, expire_pins, pin_orders, reorder_and_log, undo_batch, unpin_orders,
)


async def _mk_order(session, no, **kw):
    o = Order(order_no=no, product="P", code="M02-2D", qty=10, **kw)
    session.add(o)
    await session.commit()
    return o


async def test_pin_sets_fields_and_logs(sqlite_session):
    o = await _mk_order(sqlite_session, "A-1")
    res = await pin_orders(sqlite_session, [o.id], until="2026-12-31", operator="alice")
    assert res[0]["ok"] is True
    await sqlite_session.refresh(o)
    assert o.pinned is True and o.priority == 0 and o.prio_level == "P0" and o.prio_source == "pin"
    assert o.pinned_until == date(2026, 12, 31) and o.pinned_by == "alice"
    log = (await sqlite_session.execute(select(PriorityLog))).scalars().one()
    assert log.action == "pin" and log.new_priority == 0 and log.operator == "alice"


async def test_pin_rejects_non_normal_status(sqlite_session):
    o = await _mk_order(sqlite_session, "A-2", status="暂停")
    res = await pin_orders(sqlite_session, [o.id], until=None, operator="bob")
    assert res[0]["ok"] is False and "不可置顶" in res[0]["reason"]


async def test_expire_pins_only_past(sqlite_session):
    past = await _mk_order(sqlite_session, "A-3", pinned=True, priority=0, prio_level="P0", prio_source="pin",
                           pinned_until=date.today() - timedelta(days=1))
    future = await _mk_order(sqlite_session, "A-4", pinned=True, priority=0, prio_level="P0", prio_source="pin",
                             pinned_until=date.today() + timedelta(days=5))
    expired = await expire_pins(sqlite_session)
    assert [e["order_no"] for e in expired] == ["A-3"]
    await sqlite_session.refresh(past)
    await sqlite_session.refresh(future)
    assert past.pinned is False and past.pinned_until is None and past.prio_source == "auto"
    assert future.pinned is True


async def test_unpin_and_reorder(sqlite_session):
    o1 = await _mk_order(sqlite_session, "B-1", priority=100)
    o2 = await _mk_order(sqlite_session, "B-2", priority=250, prio_level="P1")
    o3 = await _mk_order(sqlite_session, "B-3", priority=400, prio_level="P2")
    r = await reorder_and_log(sqlite_session, o2.id, o1.id, o3.id, False, operator="carol")
    assert r["ok"] is True
    await sqlite_session.refresh(o2)
    assert o2.priority == 250 and o2.prio_source == "manual"   # (100+400)/2
    logs = (await sqlite_session.execute(select(PriorityLog))).scalars().all()
    assert any(l.action == "reorder" and l.new_priority == 250 for l in logs)

    r2 = await unpin_orders(sqlite_session, [o1.id], operator="carol")
    assert r2[0]["ok"] is True


async def test_batch_snapshot_and_undo(sqlite_session):
    o1 = await _mk_order(sqlite_session, "C-1", priority=150, prio_level="P1")
    o2 = await _mk_order(sqlite_session, "C-2", priority=350, prio_level="P2")
    b = await create_batch(sqlite_session, "recompute", [o1, o2], operator="dave")
    o1.priority, o1.prio_level = 20, "P0"
    o2.priority, o2.prio_level = 90, "P0"
    await sqlite_session.commit()
    n = await undo_batch(sqlite_session, b.batch_id, operator="dave")
    assert n == 2
    await sqlite_session.refresh(o1)
    await sqlite_session.refresh(o2)
    assert o1.priority == 150 and o1.prio_level == "P1"
    assert o2.priority == 350 and o2.prio_level == "P2"
    await sqlite_session.refresh(b)
    assert b.undone is True
    logs = (await sqlite_session.execute(select(PriorityLog))).scalars().all()
    assert any(l.action == "undo" and l.batch_id == b.batch_id for l in logs)


async def test_reorder_pinned_drag_out_and_status_guard(sqlite_session):
    from app.mps.priority import PINNED_PRIORITY

    o1 = await _mk_order(sqlite_session, "D-1", priority=100)
    o2 = await _mk_order(sqlite_session, "D-2", priority=200)
    paused = await _mk_order(sqlite_session, "D-3", priority=300, status="暂停")
    # 拖入置顶组
    r = await reorder_and_log(sqlite_session, o2.id, None, None, True, operator="eve")
    assert r["ok"] is True
    await sqlite_session.refresh(o2)
    assert o2.pinned is True and o2.priority == PINNED_PRIORITY and o2.prio_level == "P0"
    assert o2.sort_no == 10 and o2.pinned_at is not None
    # 拖出置顶组 → 清 pinned_at/until/sort_no，普通组中点 250，prio_manual 同步
    o3 = await _mk_order(sqlite_session, "D-4", priority=400)
    r2 = await reorder_and_log(sqlite_session, o2.id, o1.id, o3.id, False, operator="eve")
    assert r2["ok"] is True
    await sqlite_session.refresh(o2)
    assert o2.pinned is False and o2.pinned_at is None and o2.pinned_until is None and o2.sort_no is None
    assert o2.priority == 250 and o2.prio_manual == 250
    # 非正常状态拒绝
    r3 = await reorder_and_log(sqlite_session, paused.id, None, None, True, operator="eve")
    assert r3["ok"] is False and "不可拖拽" in r3["reason"]


async def test_pin_mixed_batch(sqlite_session):
    ok_o = await _mk_order(sqlite_session, "E-1")
    paused = await _mk_order(sqlite_session, "E-2", status="完成")
    res = await pin_orders(sqlite_session, [ok_o.id, paused.id, "nope-id"], until=None, operator="frank")
    assert [x["ok"] for x in res] == [True, False, False]
    logs = (await sqlite_session.execute(select(PriorityLog))).scalars().all()
    assert len(logs) == 1 and logs[0].action == "pin"


async def test_undo_datetime_roundtrip_and_double_undo(sqlite_session):
    from datetime import datetime

    o = await _mk_order(sqlite_session, "F-1", priority=0, prio_level="P0", prio_score=80.0,
                        pinned=True, prio_source="pin",
                        pinned_at=datetime(2026, 1, 2, 3, 4, 5), pinned_until=date(2026, 12, 31))
    b = await create_batch(sqlite_session, "recompute", [o], operator="gina")
    o.pinned, o.pinned_at, o.pinned_until, o.priority, o.prio_score = False, None, None, 500, 40.0
    await sqlite_session.commit()
    n = await undo_batch(sqlite_session, b.batch_id, operator="gina")
    assert n == 1
    await sqlite_session.refresh(o)
    assert o.pinned is True and o.pinned_at == datetime(2026, 1, 2, 3, 4, 5)
    assert o.pinned_until == date(2026, 12, 31) and o.priority == 0 and o.prio_score == 80.0
    assert await undo_batch(sqlite_session, b.batch_id) == 0     # 已撤销批次再撤销 → 0
```

- [ ] **Step 4.2: 运行确认失败**

- [ ] **Step 4.3: 创建 `backend/app/mps/priority_service.py`**

```python
"""优先级持久化服务（对应 mps-web server.js 编排职责；异步 SQLAlchemy）。

- 置顶/解除/到期：写 Order 字段 + PriorityLog 审计（PRIO-005/007）
- 拖拽落位：调用 priority.reorder_target 计算并落库
- 批量快照：PriorityBatch.snapshot 保存变更前状态，支持整体撤销（PRIO-008）
"""
from datetime import date, datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mps import Order, PriorityBatch, PriorityLog
from app.mps import priority as prio


def _now():
    return datetime.now()


async def write_log(session: AsyncSession, **row) -> PriorityLog:
    """独立日志写入（自带 commit；勿用于批处理循环——批量场景用各业务函数的内部记日志）。"""
    log = PriorityLog(**row)
    session.add(log)
    await session.commit()
    return log


async def pin_orders(session: AsyncSession, ids: list[str], until=None, operator: str = "") -> list[dict]:
    """置顶：priority=0、P0、source=pin；非"正常"状态拒绝。"""
    out = []
    until_d = None
    if until:
        until_d = date.fromisoformat(str(until)[:10])
    for oid in ids:
        o = (await session.execute(select(Order).where(Order.id == oid))).scalar_one_or_none()
        if not o:
            out.append({"id": oid, "ok": False, "reason": "工单不存在"})
            continue
        if (o.status or "正常") != "正常":
            out.append({"id": oid, "order_no": o.order_no, "ok": False,
                        "reason": f"{o.status or '非正常'}状态工单不可置顶"})
            continue
        old_priority, old_level = o.priority, o.prio_level
        o.pinned = True
        o.pinned_at = _now()
        o.pinned_until = until_d
        o.pinned_by = operator or ""
        o.priority = prio.PINNED_PRIORITY
        o.prio_level = "P0"
        o.prio_source = "pin"
        o.prio_updated_at = _now()
        o.prio_updated_by = operator or ""
        session.add(PriorityLog(
            order_id=oid, order_no=o.order_no, action="pin",
            old_priority=old_priority, new_priority=prio.PINNED_PRIORITY,
            old_level=old_level, new_level="P0",
            reason=f"临时置顶至 {until}" if until else "长期置顶", operator=operator or "",
        ))
        out.append({"id": oid, "order_no": o.order_no, "ok": True, "old_priority": old_priority})
    await session.commit()
    return out


async def unpin_orders(session: AsyncSession, ids: list[str], operator: str = "") -> list[dict]:
    """取消置顶（priority 由调用方重算恢复）。"""
    out = []
    for oid in ids:
        o = (await session.execute(select(Order).where(Order.id == oid))).scalar_one_or_none()
        if not o:
            out.append({"id": oid, "ok": False, "reason": "工单不存在"})
            continue
        old_priority, old_level = o.priority, o.prio_level
        o.pinned = False
        o.pinned_until = None
        o.pinned_at = None
        o.prio_source = "auto"
        o.prio_updated_at = _now()
        o.prio_updated_by = operator or ""
        session.add(PriorityLog(
            order_id=oid, order_no=o.order_no, action="unpin",
            old_priority=old_priority, old_level=old_level,
            reason="手动取消置顶", operator=operator or "",
        ))
        out.append({"id": oid, "order_no": o.order_no, "ok": True, "old_priority": old_priority})
    await session.commit()
    return out


async def expire_pins(session: AsyncSession, today=None) -> list[dict]:
    """置顶到期惰性解除：pinned=1 且 pinned_until < today → 解除并记日志。"""
    t = date.fromisoformat(str(today)[:10]) if today else date.today()
    rows = (await session.execute(
        select(Order).where(Order.pinned.is_(True), Order.pinned_until.is_not(None), Order.pinned_until < t)
    )).scalars().all()
    for o in rows:
        o.pinned = False
        o.pinned_until = None
        o.pinned_at = None
        o.prio_source = "auto"
        o.prio_updated_at = _now()
        session.add(PriorityLog(
            order_id=o.id, order_no=o.order_no, action="unpin",
            old_priority=o.priority, old_level=o.prio_level,
            reason=f"置顶到期自动解除（有效期至 {t} 之前）", operator="system",
        ))
    if rows:
        await session.commit()
    return [{"id": o.id, "order_no": o.order_no} for o in rows]


async def reorder_and_log(session: AsyncSession, order_id: str, prev_id=None, next_id=None,
                          to_pinned: bool = False, operator: str = "") -> dict:
    """拖拽落位并落库（只改被拖动的一条）。非"正常"状态工单拒绝（对齐 mps-web server.js）。"""
    o = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not o:
        return {"ok": False, "reason": "工单不存在"}
    if (o.status or "正常") != "正常":
        return {"ok": False, "reason": f"{o.status or '非正常'}状态工单不可拖拽"}
    prev = (await session.execute(select(Order).where(Order.id == prev_id))).scalar_one_or_none() if prev_id else None
    nxt = (await session.execute(select(Order).where(Order.id == next_id))).scalar_one_or_none() if next_id else None

    def _d(x):
        if x is None:
            return None
        return {"priority": x.priority, "sort_no": x.sort_no, "pinned": x.pinned, "id": x.id}

    target = prio.reorder_target(_d(o), _d(prev), _d(nxt), to_pinned)
    old_priority, old_level, old_sort_no = o.priority, o.prio_level, o.sort_no
    o.pinned = bool(target["pinned"])
    o.priority = target["priority"]
    o.sort_no = target["sort_no"]
    o.prio_level = target["level"]
    o.prio_source = target["source"]
    o.prio_updated_at = _now()
    o.prio_updated_by = operator or ""
    if target["pinned"]:
        o.pinned_at = o.pinned_at or _now()
    else:
        o.pinned_at = None
        o.pinned_until = None
        o.prio_manual = target["priority"]          # 拖入普通组即计划员显式排序（对齐 server.js）
    session.add(PriorityLog(
        order_id=order_id, order_no=o.order_no, action="reorder",
        old_priority=old_priority, new_priority=o.priority,
        old_level=old_level, new_level=o.prio_level,
        old_sort_no=old_sort_no, new_sort_no=o.sort_no,
        reason="拖拽排序", operator=operator or "",
    ))
    await session.commit()
    return {"ok": True, "target": target}


_SNAPSHOT_FIELDS = ("priority", "prio_level", "prio_source", "prio_manual", "prio_score",
                    "sort_no", "pinned", "pinned_at", "pinned_until", "pinned_by")


def _ser(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


async def create_batch(session: AsyncSession, action: str, orders: list[Order], operator: str = "") -> PriorityBatch:
    """记录批量操作快照（撤销用）。"""
    snapshot = {str(o.id): {f: _ser(getattr(o, f)) for f in _SNAPSHOT_FIELDS} for o in orders}
    batch = PriorityBatch(batch_id=uuid.uuid4().hex, action=action,
                          item_count=len(orders), snapshot=snapshot, operator=operator or "")
    session.add(batch)
    await session.commit()
    return batch


async def undo_batch(session: AsyncSession, batch_id: str, operator: str = "system") -> int:
    """撤销批量操作：按快照恢复字段并记日志（日志 batch_id=batch.batch_id；undo_of 列未用）。"""
    batch = (await session.execute(select(PriorityBatch).where(PriorityBatch.batch_id == batch_id))).scalar_one_or_none()
    if not batch or batch.undone or not batch.snapshot:
        return 0
    restored = 0
    for oid, snap in batch.snapshot.items():
        o = (await session.execute(select(Order).where(Order.id == oid))).scalar_one_or_none()
        if not o:
            continue
        old_priority, old_level = o.priority, o.prio_level
        for f, v in snap.items():
            if f in ("pinned_at", "pinned_until") and isinstance(v, str) and v:
                v = datetime.fromisoformat(v) if f == "pinned_at" else date.fromisoformat(v)
            setattr(o, f, v)
        o.prio_updated_at = _now()
        o.prio_updated_by = operator
        session.add(PriorityLog(
            order_id=oid, order_no=o.order_no, action="undo",
            old_priority=old_priority, new_priority=o.priority,
            old_level=old_level, new_level=o.prio_level,
            reason=f"撤销批量{batch.action}", operator=operator, batch_id=batch.batch_id,
        ))
        restored += 1
    batch.undone = True
    await session.commit()
    return restored
```

- [ ] **Step 4.4: 运行确认通过** → 定向 8 passed（首发 5 + 跟进 3）；全量（**131 passed, 1 skipped**）

**评审跟进（2026-10-14 质量审查后并入）**：`reorder_and_log` 增加非"正常"状态守卫（对齐 mps-web server.js）；拖入普通组时同步 `prio_manual`；`_SNAPSHOT_FIELDS` 增补 `prio_score/pinned_by`；`create_batch` 顶部 `import uuid` + `_ser` 抽取；`undo_batch` docstring 修正。**并发决策留痕**：拖拽/置顶乐观锁（`expected_prio_updated_at` → 409）由后续 API 层实现，本服务层已维护 `prio_updated_at` 供比对。
- [ ] **Step 4.5: 提交** `feat(mps): 优先级持久化服务（置顶/到期/拖拽/审计/批量撤销）`

---

### Task 5: strategy.py（策略层移植）

**Files:**
- Create: `backend/app/mps/strategy.py`
- Create: `backend/tests/mps/test_mps_strategy.py`

- [ ] **Step 5.1: 编写失败测试**

```python
"""策略层：5 策略注册表/排序器/指标/得分/配置 schema（移植 strategy.js）。"""
import pytest

from app.mps.strategy import (
    OBJECTIVE_SCHEMA, STRATEGIES, STRATEGY_CONFIG_SCHEMA, STRATEGY_IDS,
    bottleneck_load_of, family_of, get_strategy, get_strategy_config_values,
    order_by_bottleneck, order_by_due, order_by_priority, order_by_setup, order_by_util,
    strategy_metrics, strategy_score, workload_of,
)


def _r(no, code="M01-2DS", due="2026-07-01", qty=100, thr=None, days=17, judge="满足"):
    return {"order": {"order_no": no, "code": code, "due_date": due},
            "input_qty": qty,
            "bottleneck": {"throughput": thr} if thr else None,
            "delivery": {"days": days},
            "plan": {"judge": judge, "start_date": "2026-06-01", "finish_date": "2026-06-10"},
            "gantt": {"bars": []}}


def test_registry_and_defaults():
    assert STRATEGY_IDS == ["priority", "due", "util", "setup", "bottleneck"]
    s = get_strategy("due")
    assert s["allocPolicy"] == "pack"
    assert STRATEGIES["setup"]["allocPolicy"] == "nooverlap"
    assert get_strategy("nope")["id"] == "priority"      # 非法回退
    s2 = get_strategy("due", {"strategy_due_tardy": 4.5, "strategy_due_setup": "abc"})
    assert s2["objective"]["tardy"] == 4.5 and s2["objective"]["setup"] == 1  # 非法保留原值


def test_family_and_helpers():
    assert family_of(_r("A", code="M01-2DS")) == "M01"
    assert family_of(_r("A", code="")) == "NA"
    assert workload_of(_r("A", qty=1052)) == 1052 and workload_of({}) == 0
    assert bottleneck_load_of(_r("A", qty=600, thr=100)) == 6
    assert bottleneck_load_of(_r("A", thr=None)) is None


def test_order_fns():
    a = _r("A", code="M01-2DS", due="2026-07-02", qty=100, thr=100)
    b = _r("B", code="M02-2D", due="2026-07-01", qty=500, thr=50)
    c = _r("C", code="M01-2DS", due="2026-07-01", qty=200, thr=None)
    assert [x["order"]["order_no"] for x in order_by_due([a, b, c], {"base_date": "2026-06-01"})] == ["B", "C", "A"]
    assert [x["order"]["order_no"] for x in order_by_util([a, b, c], {})] == ["B", "C", "A"]     # 500>200>100
    assert [x["order"]["order_no"] for x in order_by_setup([b, a, c], {})] == ["C", "A", "B"]    # 族 M01 聚拢；族内交期早者先
    assert [x["order"]["order_no"] for x in order_by_bottleneck([a, c, b], {})] == ["B", "A", "C"]  # 600/100=6 > 100/100=1 > 无
    d = _r("D", code="M01-2DS", due="2026-07-03")
    assert order_by_due([a, d], {"base_date": "2026-06-01", "due_buffer_days": 10}) is not None


def test_strategy_metrics_and_score():
    planned = [_r("A", judge="延期"), _r("B", judge="满足"), _r("C", judge="无交期")]
    planned[2]["order"]["due_date"] = None                 # 无交期订单不计入 onTime（JS 口径）
    # 让 A 有 setup 条
    planned[0]["gantt"]["bars"] = [{"setup_days": 0.5}, {"setup_days": 0}]
    load = [{"load_rate": 1.5, "judge": "超载"}, {"load_rate": 0.5, "judge": "正常"}]
    m = strategy_metrics(planned, load)
    assert m["total"] == 3 and m["late"] == 1 and m["onTime"] == 1
    assert m["onTimeRate"] == pytest.approx(33.3, abs=0.1)
    assert m["overloadWC"] == 1 and m["setupTotal"] == 0.5
    assert m["utilization"] == pytest.approx(1.0)          # mean(1.5,0.5)
    assert m["bottleneckUtil"] == 1.5
    sc = strategy_score(STRATEGIES["priority"], m)
    assert 0 <= sc <= 100


def test_config_schemas():
    assert [f["key"] for f in OBJECTIVE_SCHEMA] == ["tardy", "setup", "imbal", "makespan"]
    assert STRATEGY_CONFIG_SCHEMA["due"][0]["key"] == "due_buffer_days"
    vals = get_strategy_config_values("setup", {"setup_days": 1.5})
    assert vals["fields"]["setup_days"] == 1.5
    vals2 = get_strategy_config_values("setup", {"strategy_setup_tardy": 2})
    assert vals2["objective"]["tardy"] == 2
```

- [ ] **Step 5.2: 运行确认失败**

- [ ] **Step 5.3: 创建 `backend/app/mps/strategy.py`**

按 priority.js 同比例移植（`app/mps/strategy.py` 完整代码见下；`cmp_result` 来自 priority）：

```python
"""可插拔排产策略层（移植自 mps-web src/strategy.js；纯函数，不依赖 schedule/aps）。"""
from functools import cmp_to_key

from app.mps import priority as prio


def family_of(r) -> str:
    code = ((r or {}).get("order") or {}).get("code") or ""
    return str(code).split("-")[0] or "NA"


def workload_of(r) -> float:
    return float((r or {}).get("input_qty") or 0)


def bottleneck_load_of(r):
    if not r or not r.get("bottleneck"):
        return None
    thr = r["bottleneck"].get("throughput")
    if not (thr and thr > 0) or not ((r.get("input_qty") or 0) > 0):
        return None
    return r["input_qty"] / thr


def order_by_priority(results, opts=None) -> list:
    return prio.sort_results(results)


def order_by_due(results, opts=None) -> list:
    from app.mps.dates import add_days, diff_days, to_str
    from datetime import date
    o = opts or {}
    base = o.get("base_date") or to_str(date.today())
    buf = prio._num(o.get("due_buffer_days"), 0)

    def due_of(r):
        due = r["order"].get("due_date")
        return add_days(due, buf) if due else "9999-12-31"

    def key(r):
        due = due_of(r)
        remain = diff_days(base, due) if due else None
        return (due, remain if remain is not None else 1e18, prio.sort_key(prio.result_key(r)))

    ... 
```
**实现提示（执行者按此风格完成，测试为准）**：为使「同交期按全序 comparator 兜底」且可排序，`order_by_due/setup/bottleneck` 用 `cmp_to_key` 组合比较器实现（主键比较相同时调用 `prio.cmp_result(a, b)`），避免混合排序键。`order_by_setup` 主键=(family, due_date, order_no)；`order_by_bottleneck` 主键=(有瓶颈否降序, 瓶颈负荷降序, due 升序) 后接 cmp_result；`order_by_util` 主键=(-qty) 后接 cmp_result。

其余常量与函数照 strategy.js 逐字移植：`STRATEGIES`（5 项，含 objective/allocPolicy/constraints/metrics/tag/desc）、`STRATEGY_IDS`、`get_strategy(id, p=None)`（strategy_<id>_<k> 覆盖合并）、`OBJECTIVE_SCHEMA`、`STRATEGY_CONFIG_SCHEMA`、`get_strategy_config_values(id, p)`、`strategy_metrics(planned, load)`、`strategy_score(strat, m)`（逐公式：onTime/lowSetup/balanced/shortMake 与加权）。

- [ ] **Step 5.4: 运行确认通过** → 定向 6 passed；全量（预期 138 passed）
- [ ] **Step 5.5: 提交** `feat(mps): 策略层移植（5策略/指标/得分/配置schema）`

---

### Task 6: 计划 3A 收尾（清单回写 PRIO + 执行记录）

- [ ] **Step 6.1: 对照抽查**：priority.py ↔ priority.js（评分段/比较器段）、strategy.py ↔ strategy.js（注册表/指标段）各挑 2 段逐行核对，报告结论。
- [ ] **Step 6.2: 全量回归 + check-list 回写**：CHK-PRIO-001~008 → 通过（真实测试路径）；PRIO-009 保持"待实现（计划4）"；PRIO-010 → "阻塞(疑点·按现全序语义实现)"。
- [ ] **Step 6.3: 执行记录**：更新计划 3 执行记录（新建 `docs/superpowers/plans/2026-10-14-mps-rework-plan3-execution-log.md`，含 3A 摘要/决策/教训）+ 提交。

---

## 完成定义（计划 3A 结束时）

1. `dates.py`/`priority.py`/`priority_service.py`/`strategy.py` 与源文件逐段对齐（Task 6 抽查）；
2. PRIO-001~008 测试全绿（≥16 用例）；kernel 透传接口落地且计划 2 镜像同步；
3. 全量测试绿灯（≥138 passed）；
4. 每任务独立提交；计划与实现镜像。

## 后续衔接

- **计划 3B（排产解码与求解）**：schedule.js 解码层（schedule/scheduleProcessConstrained/allocEarliest/opWork/ganttChart）、order_operations 分解与返工追加、kanban.js、aps.js（gate/启发式/局部搜索）+ **GA 求解核心（DEAP，可配置；确定性基准=策略 orderFn+解码器；CP-SAT 适配延后并在文档标注）**、SCHED-010 批次落库、SCHED 清单回写。

## Self-Review 记录

- 规格覆盖：PRIO-001~010 全部映射至 Tasks 2~6（009 转计划 4、010 阻塞保留）；strategy 全量移植；kernel 遗留"优先级透传"在本计划解决。
- 占位符扫描：无 TBD；Task 5 的 orderFns 以"实现提示+cmp_to_key 组合"给出精确做法（测试值为强约束），执行者按提示完成、不得改变语义。
- 类型一致性：dict 键（`pinned/pinned_at/priority/sort_no/due_date/delivery_days/bottleneck_rate/order_no`）贯穿 sort_key/result_key/cmp；服务层字段与计划 1 Order 模型一致（pinned_until 为 date、pinned_at 为 datetime）。
