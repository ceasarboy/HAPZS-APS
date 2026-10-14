# MPS 改造 计划 2/6：核算内核 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 mps-web 核算内核（`D:\MPS\mps-web\src\engine.js` 全文 + `schedule.js` 的 `weeklyLoad`/`lineBottleneck`）1:1 移植为 Python（`app/mps/kernel.py`、`app/mps/load.py`），并新增 DB 上下文装载（`app/mps/context.py`）；逐条实现 check-list 的 CALC/CYCLE/YIELD/FLUX/DELIVERY/LOAD 条目，官方算例（M02-2D 等）逐项对齐。

**Architecture:** 纯函数内核（移植）+ 上下文装载层（DB→dict）。内核不依赖 SQLAlchemy/ORM：输入为"订单 dict + 上下文 (proc_map/route_map/wc_map/params)"，输出为与 mps-web 同构的结果 dict（供计划 3 排产/计划 5 前端直接消费）。参数语义遵循 `app/mps/consts.py` 的"数值/枚举解析"约定；疑点全部走 `system_param` 双档（`round_mode`、`order_buffer_days`、`ramp_trigger`、`wb_auto_flux_override`、`exclude_braze_yield`）。

**Tech Stack:** Python 3.11+（本机内嵌 3.13.5：`D:\aps-hap\offline\runtime\python\python.exe`）、pytest（asyncio auto）、SQLAlchemy 2.0（仅 context 层用）。

**唯一移植参照（只读，不得修改）：** `D:\MPS\mps-web\src\engine.js`（242 行，已全文确认）、`D:\MPS\mps-web\src\schedule.js` 的 `weeklyLoad`(375-410) 与 `lineBottleneck`(414-432)。

**验收锚点：** `docs/checklists/mps-logic-checklist.md`（逐条测试命名）；官方算例：M02-2D（T=6/加急4/通量100/瓶颈DB/放行比1.052/投料1052/批量16/占用11/交付17/最晚投料12/14）、M01-2DS 周负荷（2.64/3.08/0.88 三条负荷率）。

**与 mps-web 的已知有意差异（参数化，默认对齐官方口径）：**
| 项 | mps-web 行为 | 本系统默认 | 参数 |
|---|---|---|---|
| 批量项取整 | `ceilInt`（16） | 同（ceil） | `round_mode`（ceil/exact） |
| 订单缓冲 | 已于其注释声明"取消" | 计入 1 天（官方算例 17） | `order_buffer_days`（1/0） |
| WB 自动通量 | 主数据 12000 | 12000（可用参数覆盖为 20000） | `wb_auto_flux_override`（0=用主数据） |
| 爬坡触发 | 首单/复线/变更首件 | 同；`all` 可选 | `ramp_trigger` |

---

### Task 1: 内核基础与单点函数（kernel.py 第一批）

**Files:**
- Create: `backend/app/mps/kernel.py`
- Create: `backend/tests/mps/test_kernel_units.py`

- [ ] **Step 1.1: 编写失败测试**

创建 `backend/tests/mps/test_kernel_units.py`：

```python
"""内核单点函数：本地工具 / 加急 / 分流 / 特征用量 / 折算系数 / 必填字段。"""
from app.mps.kernel import (
    ceil_int, conv_factor, feature_usage, nz, pick_mode, ramp_flux_factor,
    required_fields, urgent_cycle,
)


def test_nz_and_ceil_int():
    assert nz(None, 6) == 6 and nz("", 6) == 6 and nz("abc", 6) == 6
    assert nz("2.5", 0) == 2.5
    assert ceil_int(9.52) == 10 and ceil_int(10.0) == 10
    assert ceil_int(0.1) == 1


def test_urgent_cycle_tiers():
    assert urgent_cycle(5) == 4      # ≤5 → ΔT=1
    assert urgent_cycle(6) == 4      # 6~10 → ΔT=2
    assert urgent_cycle(10) == 8
    assert urgent_cycle(11) == 8     # >10 → ΔT=3
    assert urgent_cycle(1) == 1      # 下限 1 天
    assert urgent_cycle(2) == 1


def test_ramp_flux_factor():
    assert ramp_flux_factor(0, 2) == 0.0
    assert ramp_flux_factor(1, 2) == 0.5
    assert ramp_flux_factor(2, 2) == 1.0
    assert ramp_flux_factor(5, 2) == 1.0
    assert ramp_flux_factor(1, 0) == 1.0  # 无爬坡


def test_pick_mode_module_db_split():
    wc = {
        "modes": [
            {"mode": "半自动DB", "flux_base": 2000, "split_threshold": 20},
            {"mode": "自动DB", "flux_base": 6000, "split_threshold": 20},
        ]
    }
    assert pick_mode(wc, 19)["mode_name"] == "半自动DB"   # CHK-FLUX-001
    assert pick_mode(wc, 20)["mode_name"] == "自动DB"
    assert pick_mode(wc, 1000)["mode_name"] == "自动DB"   # 参考批量口径
    assert pick_mode({"modes": [{"mode": "/", "flux_base": 500}]}, 1)["mode_name"] == "/"


def test_feature_usage_and_missing():
    step = {"feature": "DB-芯片数N_die"}
    assert feature_usage(step, {"N_die": 60}) == {"key": "N_die", "usage": 60, "missing": False}
    assert feature_usage(step, {})["missing"] is True      # CHK-FLUX-014 缺参
    assert feature_usage({"feature": "工单产品数量N"}, {}) == {"key": "N", "usage": 1, "missing": False}
    assert feature_usage({"feature": "不存在的特征"}, {})["missing"] is True


def test_conv_factor_db_wb():
    p = {"cf_db_1": 1, "cf_db_2": 0.9, "cf_db_3": 0.8, "cf_wb_1": 1, "cf_wb_2": 0.95, "cf_wb_3": 0.9}
    db = {"cf_field": "DB胶水类型Y_die", "feature": "DB-芯片数N_die"}
    wb = {"cf_field": "WB引线类型Y_wire", "feature": "WB-键合线数N_wire"}
    assert conv_factor(db, {"Y_die": 1}, p) == 1.0
    assert conv_factor(db, {"Y_die": 2}, p) == 0.9
    assert conv_factor(db, {"Y_die": 3}, p) == 0.8
    assert conv_factor(wb, {"Y_wire": 2}, p) == 0.95
    assert conv_factor(wb, {"Y_wire": 4}, p) == 0.9
    assert conv_factor({"cf_field": "/"}, {}, p) == 1.0
    # 第2组（特征名以 -2 结尾）走 Y_die2 / Y_wire2（CHK-FLUX-017）
    db2 = {"cf_field": "DB胶水类型Y_die", "feature": "DB-芯片数N_die-2"}
    assert conv_factor(db2, {"Y_die": 1, "Y_die2": 2}, p) == 0.9


def test_required_fields():
    routes = [
        {"code": "X", "seq": 2, "feature": "WB-键合线数N_wire"},
        {"code": "X", "seq": 1, "feature": "DB-芯片数N_die"},
        {"code": "Y", "seq": 1, "feature": "SMT-贴装元件数N_smt"},
    ]
    fields = required_fields("X", routes)
    keys = [f["key"] for f in fields]
    assert keys == ["N_die", "Y_die", "N_wire", "Y_wire"]  # 按 FEATURE_FIELDS 顺序，seq 排序
    unmapped = required_fields("Z", [{"code": "Z", "seq": 1, "feature": "未知-特征X"}])
    assert unmapped[0]["unmapped"] is True


def test_pick_mode_none_and_empty():
    assert pick_mode(None, 1) is None
    assert pick_mode({}, 1) is None
    assert pick_mode({"modes": []}, 1) is None


def test_conv_factor_wb_second_group_and_default():
    p = {"cf_wb_1": 1, "cf_wb_2": 0.95, "cf_wb_3": 0.9}
    wb2 = {"cf_field": "WB引线类型Y_wire", "feature": "WB-键合线数N_wire-2"}
    assert conv_factor(wb2, {"Y_wire": 1, "Y_wire2": 3}, p) == 0.9   # 第2组走 Y_wire2
    wb = {"cf_field": "WB引线类型Y_wire", "feature": "WB-键合线数N_wire"}
    assert conv_factor(wb, {}, p) == 1.0                            # 缺键默认 1 种


def test_feature_usage_zero_empty_missing():
    step = {"feature": "DB-芯片数N_die"}
    assert feature_usage(step, {"N_die": 0})["missing"] is True
    assert feature_usage(step, {"N_die": ""})["missing"] is True
    assert feature_usage(step, {"N_die": -1})["missing"] is True
```

- [ ] **Step 1.2: 运行确认失败**

（在 `backend` 目录）`& "D:\aps-hap\offline\runtime\python\python.exe" -m pytest tests/mps/test_kernel_units.py -v`
Expected: FAIL —— `ModuleNotFoundError: No module named 'app.mps.kernel'`。

- [ ] **Step 1.3: 创建 `backend/app/mps/kernel.py`（第一批）**

```python
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
    """生产模式分流（CHK-FLUX-009/010/011）：按订单批量与阈值选半自动/自动。"""
    if not wc or not wc.get("modes"):
        return None
    modes = wc["modes"]
    if len(modes) == 1:
        return {"mode": modes[0], "mode_name": modes[0].get("mode") or "/"}
    threshold = nz(modes[0].get("split_threshold"), 0)
    auto = next(
        (m for m in modes if "自动" in str(m.get("mode", "")) and "半自动" not in str(m.get("mode", ""))),
        modes[1],
    )
    semi = modes[0]
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
```

- [ ] **Step 1.4: 运行确认通过**

```powershell
& "D:\aps-hap\offline\runtime\python\python.exe" -m pytest tests/mps/test_kernel_units.py -v
```
Expected: 7 passed。

- [ ] **Step 1.5: 提交**

```bash
git add backend/app/mps/kernel.py backend/tests/mps/test_kernel_units.py
git commit -m "feat(kernel): 内核单点函数移植（nz/ceil/加急/分流/用量/折算/必填）"
```

---

### Task 2: calc_order 主体移植（含参数化扩展）

**Files:**
- Modify: `backend/app/mps/kernel.py`（追加 calc_order / build_gantt / build_warnings）
- Create: `backend/tests/mps/test_kernel_calc.py`

- [ ] **Step 2.1: 编写失败测试（官方算例与核心口径）**

创建 `backend/tests/mps/test_kernel_calc.py`：

```python
"""calc_order 主体：官方算例 M02-2D 与周期/成品率/投料/瓶颈/批量/交付口径。"""
import pytest

from app.mps.kernel import calc_order

P_BASE = {
    "week_days": 6, "peak_factor": 1.1, "use_peak": "mean",
    "exclude_braze_yield": 1,
    "cf_db_1": 1, "cf_db_2": 0.9, "cf_db_3": 0.8,
    "cf_wb_1": 1, "cf_wb_2": 0.95, "cf_wb_3": 0.9,
    "vapor_cap_cut": 1, "order_buffer_days": 1, "reference_batch": 1000,
    "round_mode": "ceil", "ramp_trigger": "first_flag", "wb_auto_flux_override": 0,
}


def _ctx_m02_2d():
    proc = {
        "code": "M02-2D", "name": "不含SMT二维模块成套工艺", "ramp_days": 1,
        "subpart_mode": None, "subpart_cycle": 0,
    }
    routes = [
        {"code": "M02-2D", "seq": 1, "step_raw": "DB", "step_std": "DB", "level": "模块级",
         "cycle": 1, "yield_overall": 0.97, "feature": "DB-芯片数N_die", "cf_field": "DB胶水类型Y_die"},
        {"code": "M02-2D", "seq": 2, "step_raw": "WB", "step_std": "WB", "level": "模块级",
         "cycle": 1, "yield_overall": 0.99, "feature": "WB-键合线数N_wire", "cf_field": "WB引线类型Y_wire"},
        {"code": "M02-2D", "seq": 3, "step_raw": "调试", "step_std": "调试", "level": "模块级",
         "cycle": 1, "yield_overall": 1, "feature": "工单产品数量N", "cf_field": "/"},
        {"code": "M02-2D", "seq": 4, "step_raw": "封盖前终检", "step_std": "终检", "level": "模块级",
         "cycle": 1, "yield_overall": 0.995, "feature": "工单产品数量N", "cf_field": "/"},
        {"code": "M02-2D", "seq": 5, "step_raw": "封盖", "step_std": "封盖", "level": "模块级",
         "cycle": 2, "yield_overall": 0.995, "feature": "工单产品数量N", "cf_field": "/"},
    ]
    wc_map = {
        "模块级|DB": {"modes": [
            {"mode": "半自动DB", "flux_base": 2000, "flux_peak": 2200, "split_threshold": 20, "unit": "只芯片/天，芯片数N_die"},
            {"mode": "自动DB", "flux_base": 6000, "flux_peak": 6600, "split_threshold": 20, "unit": "只芯片/天，芯片数N_die"},
        ]},
        "模块级|WB": {"modes": [
            {"mode": "半自动WB", "flux_base": 4500, "flux_peak": 4950, "split_threshold": 20, "unit": "根丝/天"},
            {"mode": "自动WB", "flux_base": 12000, "flux_peak": 13200, "split_threshold": 20, "unit": "根丝/天"},
        ]},
        "模块级|调试": {"modes": [{"mode": "/", "flux_base": 10000, "flux_peak": 11000, "unit": "只产品/天"}]},
        "模块级|终检": {"modes": [{"mode": "/", "flux_base": 10000, "flux_peak": 11000, "unit": "只产品/天"}]},
        "模块级|封盖": {"modes": [{"mode": "/", "flux_base": 8000, "flux_peak": 8800, "unit": "只产品/天"}]},
    }
    return {"proc_map": {"M02-2D": proc}, "route_map": {"M02-2D": routes},
            "wc_map": wc_map, "params": dict(P_BASE)}


def _order(**kw):
    base = {"order_no": "T", "product": "模块-01", "code": "M02-2D", "order_type": "常规",
            "first_flag": "否", "water_vapor": "有", "qty": 1000, "due_date": "2026-12-31",
            "features": {"N_die": 60, "N_wire": 60}, "priority": 100}
    base.update(kw)
    return base


def test_chk_calc_001_m02_2d_cycle_flux():
    r = calc_order(_order(), _ctx_m02_2d())
    assert r["cycle"]["base"] == 6          # 1+1+1+1+2
    assert r["cycle"]["urgent"] == 4
    assert r["bottleneck"]["step_std"] == "DB"
    assert r["bottleneck"]["mode"] == "自动DB"
    assert r["bottleneck"]["throughput"] == pytest.approx(100.0)  # 6000÷60
    assert r["steps"][1]["throughput"] == pytest.approx(200.0)    # WB 12000÷60


def test_chk_calc_002_m02_2d_yield_feed_delivery():
    r = calc_order(_order(), _ctx_m02_2d())
    assert r["yield"]["ratio_basis"] == pytest.approx(0.9507210075, rel=1e-9)
    assert r["ratio"]["used"] == pytest.approx(1.052, rel=1e-3)
    assert r["input_qty"] == 1052
    assert r["batch"]["batch_cycle"] == 16
    assert r["batch"]["bottleneck_days"] == 11      # ⌈1052÷100⌉
    assert r["delivery"]["days"] == 17              # 16+0+1 缓冲
    assert r["delivery"]["latest_start_date"] == "2026-12-14"


def test_chk_cycle_005_vapor_cap():
    r = calc_order(_order(water_vapor="无"), _ctx_m02_2d())
    assert r["cycle"]["base"] == 5          # 封盖 2→1
    assert r["steps"][4]["cycle_adjusted"] is True


def test_chk_cycle_006_007_ramp():
    r1 = calc_order(_order(first_flag="首单"), _ctx_m02_2d())
    assert r1["ramp"]["used"] == 1 and r1["delivery"]["days"] == 18   # 16 + 1 爬坡 + 1 缓冲
    r2 = calc_order(_order(first_flag="复线"), _ctx_m02_2d())
    assert r2["ramp"]["used"] == 1
    r3 = calc_order(_order(first_flag="否"), _ctx_m02_2d())
    assert r3["ramp"]["used"] == 0


def test_chk_delivery_002_negative_term_zero():
    # 批量极小：Q < C 时批量项取 0
    r = calc_order(_order(qty=5, features={"N_die": 60, "N_wire": 60}), _ctx_m02_2d())
    assert r["batch"]["batch_cycle"] == r["cycle"]["used"]


def test_chk_delivery_004_005_buffer_variants():
    ctx = _ctx_m02_2d()
    r0 = calc_order(_order(), ctx)
    ctx["params"]["order_buffer_days"] = 0
    r1 = calc_order(_order(), ctx)
    assert r1["delivery"]["days"] == 16 and r0["delivery"]["days"] == 17


def test_chk_yield_005_output_check_iterate():
    # 构造 yRatio 使 ⌈qty×ratio⌉ 恰好产出不足，需要迭代 +1
    ctx = _ctx_m02_2d()
    # 用 qty=1 且 yRatio<1 触发迭代：1×ratio≈1.052→Q=2，2×0.9507=1.90≥1 OK；
    r = calc_order(_order(qty=1, features={"N_die": 60, "N_wire": 60}), ctx)
    assert r["output_check"]["ok"] is True
    assert r["output_check"]["expected"] >= 1


def test_chk_delivery_003_round_mode_variants():
    ctx = _ctx_m02_2d()
    r_ceil = calc_order(_order(), ctx)
    ctx["params"]["round_mode"] = "exact"
    r_exact = calc_order(_order(), ctx)
    assert r_ceil["batch"]["batch_cycle"] == 16
    assert r_exact["batch"]["batch_cycle"] == pytest.approx(15.52, abs=1e-6)


def test_chk_cycle_009_ramp_trigger_variants():
    ctx = _ctx_m02_2d()
    ctx["params"]["ramp_trigger"] = "all"
    r = calc_order(_order(first_flag="否"), ctx)
    assert r["ramp"]["used"] == 1     # 全部订单都触发爬坡
```

- [ ] **Step 2.2: 运行确认失败**

`... -m pytest tests/mps/test_kernel_calc.py -v` → FAIL（calc_order 未定义）。

- [ ] **Step 2.3: 在 `backend/app/mps/kernel.py` 追加实现**

```python
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


def calc_order(order: dict, ctx: dict) -> dict:
    """单条工单完整核算（移植 calcOrder + 参数化扩展）。

    扩展（相对 mps-web）：round_mode（ceil/exact）、order_buffer_days、
    ramp_trigger（first_flag/all）、wb_auto_flux_override（模块级自动WB通量覆盖）。
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
    applied = ramp_trigger == "all" or triggered
    ramp_used = nz(proc.get("ramp_days"), 0) if applied else 0
    delivery_cycle = batch_cycle + ramp_used + buffer_days

    latest_start_date = None
    due = _parse_due(order.get("due_date"))
    if due is not None:
        latest_start_date = (due - timedelta(days=delivery_cycle)).isoformat()

    gantt = build_gantt(item, t_used, batch_cycle, proc, q)
    return {
        "order": {
            "order_no": order.get("order_no"), "product": order.get("product"), "code": order["code"],
            "order_type": order.get("order_type"), "first_flag": first_flag,
            "water_vapor": "有" if has_vapor else "无", "qty": qty,
            "due_date": order.get("due_date"), "kit_date": order.get("kit_date") or "",
            "priority": order.get("priority"), "remark": order.get("remark"),
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
    """缺 BOM 特征 / 工序主数据缺失 提示（CHK-FLUX-018）。"""
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
```

- [ ] **Step 2.4: 运行确认通过**

`... -m pytest tests/mps/test_kernel_calc.py -v` → 预期 10 passed。
（若任一数字不符：对照 `D:\MPS\mps-web\src\engine.js` 逐段核对，不得放宽断言。）

- [ ] **Step 2.5: 提交**

```bash
git add backend/app/mps/kernel.py backend/tests/mps/test_kernel_calc.py
git commit -m "feat(kernel): calc_order 主体移植（官方算例对齐 + 双档参数化）"
```

---

### Task 3: 上下文装载（DB → 内核输入）

**Files:**
- Create: `backend/app/mps/context.py`
- Create: `backend/tests/mps/test_kernel_context.py`

- [ ] **Step 3.1: 编写失败测试（含 CHK-CALC-004 数据流联动）**

创建 `backend/tests/mps/test_kernel_context.py`：

```python
"""上下文装载：种子库 → 内核输入；主数据变更后重算结果联动变化（CHK-CALC-004）。"""
from sqlalchemy import select

from app.models.mps import ProcessMaster, SystemParam
from app.mps.context import load_ctx
from app.mps.kernel import calc_order
from app.seed.loader import load_mps_seed


async def test_load_ctx_from_seed(sqlite_session):
    await load_mps_seed(sqlite_session)
    ctx = await load_ctx(sqlite_session)
    assert "M02-2D" in ctx["proc_map"] and len(ctx["route_map"]["M02-2D"]) == 5
    assert ctx["wc_map"]["模块级|DB"]["modes"][1]["flux_base"] == 6000
    assert ctx["params"]["week_days"] == 6
    assert ctx["params"]["round_mode"] == "ceil"
    assert ctx["params"]["use_peak"] == "mean"


async def test_calc_with_seeded_data_matches_official(sqlite_session):
    await load_mps_seed(sqlite_session)
    ctx = await load_ctx(sqlite_session)
    order = {"order_no": "W0-000", "product": "模块-01", "code": "M02-2D", "order_type": "常规",
             "first_flag": "否", "water_vapor": "有", "qty": 1000, "due_date": "2026-12-31",
             "features": {"N_die": 60, "N_wire": 60}}
    r = calc_order(order, ctx)
    assert r["input_qty"] == 1052 and r["batch"]["batch_cycle"] == 16 and r["delivery"]["days"] == 17


async def test_chk_calc_004_data_flow_linkage(sqlite_session):
    """主数据修改 → 重装载 → 结果变化（上游改下游刷新）。"""
    await load_mps_seed(sqlite_session)
    ctx1 = await load_ctx(sqlite_session)
    order = {"order_no": "L", "product": "模块-01", "code": "M02-2D", "order_type": "常规",
             "first_flag": "否", "water_vapor": "有", "qty": 1000, "features": {"N_die": 60, "N_wire": 60}}
    t1 = calc_order(order, ctx1)["bottleneck"]["throughput"]

    wc = (await sqlite_session.execute(
        select(ProcessMaster).where(ProcessMaster.level == "模块级", ProcessMaster.op == "DB",
                                    ProcessMaster.mode == "自动DB")
    )).scalar_one()
    wc.flux_base = 3000
    await sqlite_session.commit()

    ctx2 = await load_ctx(sqlite_session)
    t2 = calc_order(order, ctx2)["bottleneck"]["throughput"]
    assert t1 == 100.0 and t2 == pytest.approx(50.0)  # 3000÷60
```

（如文件缺 `import pytest` 请补上。）

- [ ] **Step 3.2: 运行确认失败**

`... -m pytest tests/mps/test_kernel_context.py -v` → FAIL（app.mps.context 不存在）。

- [ ] **Step 3.3: 创建 `backend/app/mps/context.py`**

```python
"""内核上下文装载：数据库 → 内核输入 dict（proc_map/route_map/wc_map/params）。

参数解析遵循 consts 约定：数值键一律转 float/int，枚举键保留字符串。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mps import ProcessMaster, ProcessRoute, ProcessSet, SystemParam
from app.mps.kernel import nz

_NUMERIC_PARAM_KEYS = (
    "week_days", "peak_factor", "exclude_braze_yield",
    "cf_db_1", "cf_db_2", "cf_db_3", "cf_wb_1", "cf_wb_2", "cf_wb_3",
    "vapor_cap_cut", "order_buffer_days", "reference_batch", "wb_auto_flux_override",
)


async def load_params(session: AsyncSession) -> dict:
    """系统参数：数值键转数值，枚举键保留字符串。"""
    rows = (await session.execute(select(SystemParam))).scalars().all()
    params: dict = {}
    for row in rows:
        key = row.key
        if key in _NUMERIC_PARAM_KEYS:
            params[key] = nz(row.value, 0)
        else:
            params[key] = row.value
    return params


async def load_ctx(session: AsyncSession) -> dict:
    """装载核算上下文：成套工艺 / 路线 / 工序主数据 / 参数。"""
    proc_map = {p.code: _proc_dict(p) for p in (await session.execute(select(ProcessSet))).scalars().all()}

    route_map: dict[str, list[dict]] = {}
    for r in (await session.execute(select(ProcessRoute))).scalars().all():
        route_map.setdefault(r.code, []).append(_route_dict(r))

    wc_map: dict[str, dict] = {}
    for w in (await session.execute(select(ProcessMaster))).scalars().all():
        key = f"{w.level}|{w.op}"
        wc_map.setdefault(key, {"modes": []})["modes"].append(_wc_mode_dict(w))

    return {"proc_map": proc_map, "route_map": route_map, "wc_map": wc_map,
            "params": await load_params(session)}


def _proc_dict(p: ProcessSet) -> dict:
    return {"code": p.code, "name": p.name, "arch": p.arch, "owner": p.owner,
            "subpart_mode": p.subpart_mode, "subpart_cycle": p.subpart_cycle,
            "ramp_days": p.ramp_days, "yield_ref": p.yield_ref, "cycle_ref": p.cycle_ref,
            "urgent_ref": p.urgent_ref, "ratio_ref": p.ratio_ref, "route_text": p.route_text}


def _route_dict(r: ProcessRoute) -> dict:
    return {"code": r.code, "seq": r.seq, "step_raw": r.step_raw, "step_std": r.step_std,
            "level": r.level, "cycle": r.cycle, "yield_inspect": r.yield_inspect,
            "yield_overall": r.yield_overall, "feature": r.feature,
            "cf_field": r.cf_field, "cf_trigger": r.cf_trigger}


def _wc_mode_dict(w: ProcessMaster) -> dict:
    return {"mode": w.mode, "cycle": w.cycle, "flux_base": w.flux_base, "flux_peak": w.flux_peak,
            "unit": w.unit, "feature": w.feature, "split_threshold": w.split_threshold}
```

- [ ] **Step 3.4: 运行确认通过**

`... -m pytest tests/mps/test_kernel_context.py -v` → 预期 3 passed。

- [ ] **Step 3.5: 提交**

```bash
git add backend/app/mps/context.py backend/tests/mps/test_kernel_context.py
git commit -m "feat(kernel): 上下文装载（DB→内核输入）与数据流联动"
```

---

### Task 4: 周负荷与产线瓶颈移植

**Files:**
- Create: `backend/app/mps/load.py`
- Create: `backend/tests/mps/test_kernel_load.py`

- [ ] **Step 4.1: 编写失败测试**

创建 `backend/tests/mps/test_kernel_load.py`：

```python
"""周负荷（weeklyLoad 移植）与产线瓶颈（lineBottleneck 移植）。"""
import pytest

from app.mps.load import line_bottleneck, weekly_load

P = {"week_days": 6, "peak_factor": 1.1, "use_peak": "mean"}


def _results():
    # 构造两个工单结果（字段依赖与 mps-web 结果同构）
    def mk(order_no, input_qty, steps):
        return {"order": {"order_no": order_no, "product": "P"}, "input_qty": input_qty,
                "steps": steps, "bottleneck": next((s for s in steps if s.get("is_bottleneck")), None),
                "batch": {"batch_cycle": 10, "bottleneck_days": 3}}

    db_semi = {"seq": 1, "step_std": "DB", "level": "模块级", "mode": "半自动DB", "wc_key": "模块级|DB",
               "feature": "DB-芯片数N_die", "feature_key": "N_die", "usage": 60, "missing": False,
               "flux_base": 2000, "unit": "只芯片/天", "is_bottleneck": True}
    wb = {"seq": 2, "step_std": "WB", "level": "模块级", "mode": "半自动WB", "wc_key": "模块级|WB",
          "feature": "WB-键合线数N_wire", "feature_key": "N_wire", "usage": 100, "missing": False,
          "flux_base": 4500, "unit": "根丝/天", "is_bottleneck": False}
    miss = {"seq": 3, "step_std": "SMT", "level": "模块级", "mode": "/", "wc_key": "模块级|SMT",
            "feature": "SMT-贴装元件数N_smt", "feature_key": "N_smt", "usage": None, "missing": True,
            "flux_base": 2400, "unit": "只/天", "is_bottleneck": False}
    return [mk("A", 100, [db_semi, wb]), mk("B", 100, [dict(db_semi), dict(miss)])]


def test_weekly_load_and_judge():
    rows = weekly_load(_results(), {"params": dict(P)})
    d = {r["key"]: r for r in rows}
    # 模块级|DB|半自动DB：load=(100+100)×60=12000；available=2000×6=12000 → 恰 1.0 不属超载
    assert d["模块级|DB|半自动DB"]["load"] == pytest.approx(12000)
    assert d["模块级|DB|半自动DB"]["available"] == pytest.approx(12000)
    assert d["模块级|DB|半自动DB"]["judge"] == "偏紧"   # rate==1.0 → 不是 >1
    # 模块级|WB|半自动WB：load=100×100=10000；available=4500×6=27000
    assert d["模块级|WB|半自动WB"]["load_rate"] == pytest.approx(10000 / 27000)
    # 缺特征订单进入 missing_orders 且不累计负荷
    smt = d["模块级|SMT|/"]
    assert smt["load"] == 0 and smt["missing_orders"] == ["B"]


def test_weekly_load_peak_mode():
    rows = weekly_load(_results(), {"params": {**P, "use_peak": "peak"}})
    d = {r["key"]: r for r in rows}
    assert d["模块级|DB|半自动DB"]["available"] == pytest.approx(2000 * 1.1 * 6)


def test_judge_thresholds():
    rows = weekly_load(_results(), {"params": dict(P)})
    d = {r["key"]: r for r in rows}
    assert d["模块级|DB|半自动DB"]["judge"] == "偏紧"     # =1.00
    # <0.85 正常：构造更大的可用（改 use_peak 峰值 → 13200 > 12000）
    rows2 = weekly_load(_results(), {"params": {**P, "use_peak": "peak"}})
    d2 = {r["key"]: r for r in rows2}
    assert d2["模块级|DB|半自动DB"]["judge"] == "正常"    # 12000/13200≈0.909 → 偏紧？
```

**注意**：上面最后一条断言需按实际算术校正（12000/13200≈0.909 应判"偏紧"，实现按 0.85 阈值）。执行者请用真实算术核对后修正断言（不得放宽逻辑，只修正期望值）：`available=13200 → rate≈0.909 → "偏紧"`；"正常"案例请另构造（如 load<0.85×available 的参数组合）。

- [ ] **Step 4.2: 运行确认失败** → `ModuleNotFoundError: app.mps.load`。

- [ ] **Step 4.3: 创建 `backend/app/mps/load.py`**

（1:1 移植 `schedule.js` 的 `weeklyLoad`（375-410 行）与 `lineBottleneck`（414-432 行）；`nz` 从 kernel 复用）

```python
"""周负荷与产线瓶颈（移植自 mps-web src/schedule.js weeklyLoad / lineBottleneck）。"""
from app.mps.kernel import nz


def weekly_load(results: list[dict], opts: dict) -> list[dict]:
    """周负荷 = Σ(投料量 × 单只特征用量)；周可用 = 基准通量 × 周工作天数。

    判定：rate>1 超载 / ≥0.85 偏紧 / <0.85 正常；缺通量为 "缺通量"。
    """
    p = opts.get("params") or {}
    week_days = nz(p.get("week_days"), 6)
    use_peak = str(p.get("use_peak") or "mean") == "peak"
    agg: dict[str, dict] = {}
    for r in results:
        if r.get("error"):
            continue
        for s in r["steps"]:
            if not s.get("wc_key"):
                continue
            key = f"{s['wc_key']}|{s['mode']}"
            if key not in agg:
                agg[key] = {
                    "key": key, "level": s.get("level"), "op": s.get("step_std"), "mode": s.get("mode"),
                    "feature": s.get("feature"), "feature_key": s.get("feature_key"), "unit": s.get("unit"),
                    "flux_base": s.get("flux_base"), "load": 0, "orders": [], "missing_orders": [],
                }
            a = agg[key]
            a["flux_base"] = max(a["flux_base"] or 0, s.get("flux_base") or 0)
            if s.get("missing") or not s.get("usage"):
                a["missing_orders"].append(r["order"]["order_no"])
                continue
            a["load"] += r["input_qty"] * s["usage"]
            a["orders"].append({"order_no": r["order"]["order_no"], "qty": r["input_qty"],
                                "usage": s["usage"], "amount": r["input_qty"] * s["usage"]})
    rows = []
    for a in agg.values():
        flux = (a["flux_base"] * nz(p.get("peak_factor"), 1.1)) if use_peak else a["flux_base"]
        available = flux * week_days
        rate = (a["load"] / available) if available > 0 else None
        rows.append({**a, "week_days": week_days, "flux_used": flux, "available": available,
                     "load_rate": rate,
                     "judge": "缺通量" if rate is None else ("超载" if rate > 1 else ("偏紧" if rate >= 0.85 else "正常"))})
    rows.sort(key=lambda x: x["load_rate"] or 0, reverse=True)
    return rows


def line_bottleneck(results: list[dict], load_rows: list[dict]) -> list[dict]:
    """产线瓶颈 = 承担工单最多的约束工序（按负荷率、命中次数排序）。"""
    cnt: dict[str, dict] = {}
    for r in results:
        if r.get("error") or not r.get("bottleneck"):
            continue
        s = next((x for x in r["steps"] if x.get("is_bottleneck")), None)
        if not s:
            continue
        key = f"{s['wc_key']}|{s['mode']}"
        if key not in cnt:
            cnt[key] = {"key": key, "level": s.get("level"), "op": s.get("step_std"), "mode": s.get("mode"),
                        "hits": 0, "orders": [], "total_days": 0}
        c = cnt[key]
        c["hits"] += 1
        c["orders"].append({"order_no": r["order"]["order_no"], "product": r["order"].get("product"),
                            "code": r["order"]["code"], "throughput": s.get("throughput"),
                            "batch": r["batch"]["batch_cycle"]})
        c["total_days"] += r["batch"].get("bottleneck_days") or 0
    rows = []
    for c in cnt.values():
        load = next((l for l in load_rows if l["key"] == c["key"]), None)
        rows.append({**c, "load_rate": load["load_rate"] if load else None,
                     "judge": load["judge"] if load else None})
    rows.sort(key=lambda x: (-(x["load_rate"] or 0), -x["hits"]))
    return rows
```

- [ ] **Step 4.4: 修正测试期望值后运行通过**

按 Step 4.1 注记用真实算术核对"判定边界"断言（只改期望值）。`... -m pytest tests/mps/test_kernel_load.py -v` → 预期 3 passed；全量回归 `... -m pytest tests -q`。

- [ ] **Step 4.5: 提交**

```bash
git add backend/app/mps/load.py backend/tests/mps/test_kernel_load.py
git commit -m "feat(kernel): 周负荷与产线瓶颈移植（判定阈值含边界）"
```

---

### Task 5: 官方周负荷算例复原（M01-2DS）与疑点双档补齐

**Files:**
- Create: `backend/tests/mps/test_kernel_official_load.py`
- 可能需要：`backend/tests/mps/test_kernel_doubts.py`

- [ ] **Step 5.1: 复原 M01-2DS 周负荷算例数据（调查步）**

读取 `backend/.tmp/mps-extract/封测中心产线成套工艺计算逻辑说明书-V1.6.md`（若不存在，先运行 `python tools/extract_mps_docs.py`）中 §九第二段与表6；再读 V1.7 周计划工作表提取文本，确定"同周"案例的**完整订单集合**与各订单特征值。目标：复现三条负荷率 **2.64 / 3.08 / 0.88**（判定：超载/超载/偏紧）。
- 若文中仅给 M01-2DS 单订单（500只/首单，N_smt=24、N_die=60、N_wire=300）而数字对不上单订单推算（94860÷36000 等三数来自不同分母），说明算例混合多订单——从 V1.7 提取文本中寻找其余参与订单（如示例区其它行）。
- 完成判据：给出参与订单清单与推算过程（写入测试注释），三条率用 `pytest.approx(abs=0.01)` 断言。

- [ ] **Step 5.2: 编写官方算例测试**

创建 `backend/tests/mps/test_kernel_official_load.py`（用 `sqlite_session` + `load_mps_seed` + `load_ctx` + `calc_order`/`weekly_load` 组合；订单数据按 Step 5.1 复原结果写入）：

```python
"""官方周负荷算例（CHK-CALC-003）：M01-2DS 同周三条负荷率 2.64/3.08/0.88。

参与订单（来自 V1.6 §九 第二段 / V1.7 周计划示例，复原过程见注释）：
<执行者在此写入复原出的订单清单与推算过程>
"""
import pytest

from app.mps.context import load_ctx
from app.mps.kernel import calc_order
from app.mps.load import weekly_load
from app.seed.loader import load_mps_seed

ORDERS = [
    # <执行者按复原结果填充>
]


async def test_chk_calc_003_m01_2ds_weekly_load(sqlite_session):
    await load_mps_seed(sqlite_session)
    ctx = await load_ctx(sqlite_session)
    results = [calc_order(o, ctx) for o in ORDERS]
    rows = {r["key"]: r for r in weekly_load(results, {"params": ctx["params"]})}
    assert rows["模块级|DB|自动DB"]["load_rate"] == pytest.approx(2.64, abs=0.01)
    assert rows["模块级|WB|自动WB"]["load_rate"] == pytest.approx(3.08, abs=0.01)
    assert rows["模块级|SMT|/"]["load_rate"] == pytest.approx(0.88, abs=0.01)
    assert rows["模块级|DB|自动DB"]["judge"] == "超载"
    assert rows["模块级|WB|自动WB"]["judge"] == "超载"
    assert rows["模块级|SMT|/"]["judge"] == "偏紧"
```

若复原证明逻辑书数字含未公开的其它订单口径（无法复现），**停下报告 BLOCKED** 并附复算明细；不得修改断言硬凑。

- [ ] **Step 5.3: 疑点双档测试补齐**

创建 `backend/tests/mps/test_kernel_doubts.py`（对既有内核用参数双档验证；引用 check-list 编号）：

```python
"""疑点双档（走 system_param）：FLUX-015A/B、DELIVERY-003A/B、005A/B、CYCLE-009A/B。"""
（复用 test_kernel_calc 的 _ctx_m02_2d/_order 构造逻辑——通过 import 或本地复制最小构造）

- test_chk_flux_015a_wb_auto_12000：wb_auto_flux_override=0 → WB 自动通量 12000（主数据口径）
- test_chk_flux_015b_wb_auto_20000：wb_auto_flux_override=20000 → WB 步 throughput=20000÷N_wire、瓶颈可能切换
- （DELIVERY-003A/B、005A/B、CYCLE-009A/B 已在 Task 2 覆盖，此处引用即可，不重复）
```

- [ ] **Step 5.4: 运行 + 全量回归**

`... -m pytest tests/mps -q`；`... -m pytest tests -q`（预期 ≥60 passed, 1 skipped）。

- [ ] **Step 5.5: 更新 check-list 状态 + 提交**

- 将本次通过条目状态由"待实现"改为"通过"（保留双档疑点条目状态为"阻塞(疑点)"但补注"已实现双档"）；
- 提交：`git add backend/tests/mps/... docs/checklists/...; git commit -m "test(kernel): 官方周负荷算例复原 + 疑点双档 + 清单状态更新"`。

---

### Task 6: 内核收尾（对照抽查 + 文档）

**Files:**
- Modify: `docs/superpowers/plans/2026-10-14-mps-rework-plan1-execution-log.md`（或另建计划 2 执行记录）
- Create: `backend/app/mps/__init__.py` 导出（如需要）

- [ ] **Step 6.1: 与 mps-web 逐段对照抽查**

挑 3 段（周期段、通量段、交付段），将 `kernel.py` 与 `engine.js` 对应行逐句比对（执行者用 diff 思路人工核对），在提交信息或报告中说明核对结果；发现偏差即修正。

- [ ] **Step 6.2: 全量回归 + 清单穷尽性对照**

`pytest tests -q` 全绿；check-list CALC/CYCLE/YIELD/FLUX/DELIVERY/LOAD 各条目逐一核对其测试用例是否存在且通过（填一张核对表放入执行报告）。

- [ ] **Step 6.3: 提交 + 报告**

```bash
git add -A
git commit -m "docs: 计划2 核算内核收尾（对照抽查与清单核对）"
```

---

## 完成定义（本计划结束时）

1. `app/mps/kernel.py`/`load.py`/`context.py` 与 `engine.js`/`weeklyLoad`/`lineBottleneck` 逐段对齐（Task 6 对照抽查）；
2. 官方算例通过：M02-2D（T=6/4、1052、16、11、17、12/14）与 M01-2DS 周负荷（2.64/3.08/0.88）——或 BLOCKED 并附明细；
3. check-list 中 CALC/CYCLE/YIELD/FLUX/DELIVERY/LOAD 条目：测试存在且通过（双档疑点保持"阻塞"状态但双档已实现）；
4. 全量测试绿灯（PG 跳过项照旧）；
5. 每任务独立提交；计划文件与实现镜像。

## 后续计划衔接

- 计划 3（排产内核）：消费本内核结果 + `order_operations` 分解；`schedule.js` 解码层/优先级/策略/GA 在此落地；
- 计划 4（明道云）：`weeklyLoad` 缺参提示等可作为回写字段来源；
- 计划 5（前端）：本内核结果 dict 直接驱动六视图。

## Self-Review 记录

- **规格覆盖**：check-list CALC(4)/CYCLE(10)/YIELD(6)/FLUX(部分属排产分流的 010/011 已覆盖；014-017/018 已在 Task 1/2/5)、DELIVERY(10)/LOAD(10) → Tasks 1~5 均映射；COL 列解读类中"周期三列/成品率列/批量四口径"由参数双档覆盖（003/005），其余列属数据/文档类计划 1 已覆盖。
- **占位符扫描**：Task 5 的 ORDERS 列表标注"执行者按复原结果填充"——这是**调查型步骤的明确产物要求**（附完成判据与 BLOCKED 路径），非 TBD 占位；Task 4 测试中边界断言标注需按实际算术校正（已给出算术与正确处理方式）。
- **类型一致性**：结果 dict 键（`cycle.base`/`bottleneck.throughput`/`batch.batch_cycle`/`delivery.latest_start_date` 等）在 kernel→load→测试间一致；`nz/ceil_int` 定义于 kernel，load/conftest 复用（单一来源）。
- **已知风险**：Task 5 官方周负荷算例依赖数据复原（V1.7 同行示例区），设 BLOCKED 路径；Task 2 期望值（0.9507210075/1.052/1052/16/11/17）源自 V1.6 表6 与 mps-web verify 基线，若不符按 engine.js 逐段核对后修正实现或报告。
