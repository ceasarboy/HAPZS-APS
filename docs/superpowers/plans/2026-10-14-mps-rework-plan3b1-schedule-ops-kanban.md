# MPS 改造 计划 3B1/6：排产解码与工序需求 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移植 mps-web 的 **排产解码层**（`schedule.js`：`scheduleProcessConstrained`/`allocEarliest`/`opWork`/`ganttChart` 与非容量时间线分支）与**工序级需求分解**（设计 D12：自动分解+手工追加/返工试制）及**日任务看板**（`kanban.js`），为 3B2（APS/GA/批次落库）提供确定性执行内核。

**Architecture:** `app/mps/schedule.py`（纯函数解码器，消费计划 2/3A 的 kernel/priority/strategy 产物）+ `app/mps/operations.py`（工序级需求：分解/手工追加/手工条合并）+ `app/mps/kanban.py`（看板数据）。全部纯函数，不碰 DB（落库归 3B2 service）。

**Tech Stack:** Python 3.13.5（内嵌 `offline\runtime\python\python.exe`）、pytest；沿用 kernel 结果 dict 契约与 tests/mps 夹具风格。

**唯一移植参照（只读）：** `D:\MPS\mps-web\src\schedule.js`（1-483 行，重点 176-243 解码核心 + 245-370 定序排产 + 434-481 甘特）与 `src\kanban.js`（121 行）。

**check-list 覆盖（3B1 负责）：** CHK-SCHED-001/002/003/004/005/007/008/009 的实现与测试（SCHED-006 在 Task 3；SCHED-010 归 3B2；清单回写统一在 3B2 收尾）。

**结果契约（3B2/看板消费）：** 解码后每条结果追加/更新：`plan{start_date,finish_date,deliver_date,latest_start_date,gap_days,judge,kit_date,kit_adjusted,kit_note,kit_risk,resource_constrained,strategy_id,strategy_name,rationale}`；`gantt.bars[].{from,to,busy_days,setup_days,res}`；返回 `{planned, ledger, capViolations, fluxOf, strategy}`。

---

### Task 1: schedule.py 第一批（账本分配核心）

**Files:**
- Create: `backend/app/mps/schedule.py`
- Create: `backend/tests/mps/test_mps_schedule.py`

- [ ] **Step 1.1: 编写失败测试（allocEarliest 语义 + opWork）**

```python
"""排产解码①：alloc_earliest 账本语义 / op_work（含手工条扩展）。"""
import pytest

from app.mps.schedule import alloc_earliest, op_work, order_opts, resource_key


def test_order_opts_defaults():
    o = order_opts({"P": {"setup_days": 1.5, "due_buffer_days": 3}})
    assert o["setupDiff"] == 1.5 and o["due_buffer_days"] == 3
    o2 = order_opts()
    assert o2["setupDiff"] == 0.5 and o2["due_buffer_days"] == 0


def test_alloc_earliest_basic_and_daily_spread():
    ledger = {}
    a = alloc_earliest(ledger, "R1", 0, 63120, 6000)
    assert a["dayNeeded"] == 11 and a["start"] == 0 and a["end"] == 11
    assert ledger["R1"][0]["used"] == pytest.approx(63120 / 11)
    # 第二单同资源：0~10 日均已放 5738.18/天，放不下 360 → 顺延到 day11（该日为空）
    b = alloc_earliest(ledger, "R1", 0, 360, 6000)
    assert b["start"] == 11 and b["dayNeeded"] == 1
    assert ledger["R1"][11]["used"] == pytest.approx(360)


def test_alloc_earliest_scan_gap_and_capacity_fit():
    ledger = {}
    alloc_earliest(ledger, "R1", 0, 6000, 6000)          # day0 满
    c = alloc_earliest(ledger, "R1", 0, 6000, 6000)      # 应顺延到 day1
    assert c["start"] == 1 and c["end"] == 2
    # ceil 容差（1e-9）：微超可忽略，naive ceil 会误判为 4 天
    d = alloc_earliest(ledger, "R2", 0, 3 * 6000 + 1e-6, 6000)
    assert d["dayNeeded"] == 3


def test_alloc_earliest_nooverlap_policy():
    ledger = {}
    a = alloc_earliest(ledger, "R1", 0, 3000, 3000, policy="nooverlap")
    assert ledger["R1"][0]["slots"] == [1]            # nooverlap 记录占用区间端点
    b = alloc_earliest(ledger, "R1", 0, 3000, 3000, policy="nooverlap")
    assert b["start"] >= a["end"]                     # 容量打满顺延（slots 同步记录）
    assert ledger["R1"][1]["slots"] == [2]
    alloc_earliest(ledger, "R2", 0, 3000, 3000)       # 默认策略不记 slots
    assert ledger["R2"][0]["slots"] == []


def test_alloc_earliest_zero_amount():
    r = alloc_earliest({}, "R1", 3, 0, 100)
    assert r == {"start": 3, "end": 3, "span": 0, "dayNeeded": 0}


def _ctx_min():
    return {
        "proc_map": {"M02-2D": {"code": "M02-2D", "ramp_days": 1, "subpart_mode": None, "subpart_cycle": 0}},
        "route_map": {"M02-2D": [
            {"code": "M02-2D", "seq": 1, "step_raw": "DB", "step_std": "DB", "level": "模块级",
             "cycle": 1, "yield_overall": 0.97, "feature": "DB-芯片数N_die", "cf_field": "DB胶水类型Y_die"},
            {"code": "M02-2D", "seq": 2, "step_raw": "WB", "step_std": "WB", "level": "模块级",
             "cycle": 1, "yield_overall": 0.98, "feature": "WB-键合线数N_wire", "cf_field": "WB引线类型Y_wire"},
        ]},
        "wc_map": {
            "模块级|DB": {"modes": [
                {"mode": "半自动DB", "flux_base": 2000, "flux_peak": 2200, "split_threshold": 20, "unit": "只芯片/天"},
                {"mode": "自动DB", "flux_base": 6000, "flux_peak": 6600, "split_threshold": 20, "unit": "只芯片/天"},
            ]},
            "模块级|WB": {"modes": [
                {"mode": "半自动WB", "flux_base": 4500, "flux_peak": 4950, "split_threshold": 20, "unit": "根丝/天"},
                {"mode": "自动WB", "flux_base": 12000, "flux_peak": 13200, "split_threshold": 20, "unit": "根丝/天"},
            ]},
        },
        "params": {"week_days": 6, "peak_factor": 1.1, "use_peak": "mean", "exclude_braze_yield": 1,
                   "cf_db_1": 1, "cf_db_2": 0.9, "cf_db_3": 0.8, "cf_wb_1": 1, "cf_wb_2": 0.95, "cf_wb_3": 0.9,
                   "vapor_cap_cut": 1, "order_buffer_days": 1, "reference_batch": 1000,
                   "round_mode": "ceil", "ramp_trigger": "first_flag", "wb_auto_flux_override": 0},
    }


def _calc(qty=1000):
    from app.mps.kernel import calc_order

    o = {"order_no": "A", "product": "P", "code": "M02-2D", "order_type": "常规",
         "first_flag": "否", "water_vapor": "有", "qty": qty, "features": {"N_die": 60, "N_wire": 60}}
    return calc_order(o, _ctx_min())


# 夹具口径（执行修正留痕 2026-10-14）：2 工序 DB0.97×WB0.98=0.9506 → 放量比≈1.052 → Q=⌈1000×1.05197⌉=1052
# （原稿 WB=0.99 得 yRatio 0.9603→Q=1042，与全计划 1052 类断言矛盾；已用 Node engine.js 实证并修正）


def test_op_work_from_step_and_manual():
    r = _calc()
    w = op_work(r, r["gantt"]["bars"][0])
    assert w["key"] == "模块级|DB|自动DB"
    assert w["amt"] == pytest.approx(1052 * 60) and w["flux"] == 6000
    manual = {"kind": "step", "seq": 2.5, "step_std": "调试", "level": "模块级",
              "mode": "/", "usage": 1, "flux": 10000, "manual": True}
    wm = op_work(r, manual)
    assert wm["key"] == "模块级|调试|/" and wm["flux"] == 10000
    assert wm["amt"] == pytest.approx(1052)


def test_resource_key_and_subpart():
    r = _calc()
    assert resource_key(r, r["gantt"]["bars"][0]) == "模块级|DB|自动DB"
    assert resource_key(r, {"kind": "subpart", "seq": 0, "step_std": "前置分部件"}) == "前置分部件|M02-2D"
    assert resource_key(r, {"kind": "step", "seq": 99, "step_std": "X"}) is None
```

- [ ] **Step 1.2: 运行确认失败** → `ModuleNotFoundError: app.mps.schedule`

- [ ] **Step 1.3: 创建 `backend/app/mps/schedule.py`（第一批）**

```python
"""排产解码层（移植自 mps-web src/schedule.js；纯函数，不写库）。

- alloc_earliest：按日产能账本找"最早可排时段"（整批占用、顺延、可选 nooverlap）
- op_work：单工单在资源上的工作量（特征量）；含 [扩展] 手工追加条（返工/试制）
- 与 JS 的已知微观差异：顺延扫描上限同 3650；`Math.floor(from)||0` → `max(0, int(from_) or 0)`
  （None/NaN 时 JS 归 0、Python 抛错，真实调用方均为数值）；subpart 分支对缺失 process
  防御性兜底（JS 直接抛错）；nooverlap 判别为 JS 同源死分支（day_free 恒 > i，保留同构）。
"""
from datetime import date  # noqa: F401（第二批基日缺省用）

from app.mps import priority as prio  # noqa: F401（JS 同源占位，上游亦未使用；保留同构）
from app.mps.dates import add_days, diff_days, to_str  # noqa: F401
from app.mps.kernel import ceil_int, nz


def order_opts(opts=None) -> dict:
    """构造传给 orderFn 的排序选项（注入可调参数：换线天数/交期缓冲）。"""
    o = dict(opts or {})
    p = o.get("P") or {}
    if o.get("setupDiff") is None:
        o["setupDiff"] = nz(p.get("setup_days"), 0.5)
    o["due_buffer_days"] = nz(p.get("due_buffer_days"), 0)
    return o


def resource_key(r, bar):
    """资源键 `${level}|${op}|${mode}`；前置分部件 `前置分部件|${code}`。"""
    if bar.get("kind") == "subpart":
        return f"前置分部件|{(r.get('process') or {}).get('code', '')}"
    step = next((s for s in r["steps"]
                 if s.get("seq") == bar.get("seq") and s.get("step_std") == bar.get("step_std")), None)
    if not step:
        return None
    return f"{step['level']}|{step['step_std']}|{step['mode']}"


op_key = resource_key  # 与 JS 两份同构函数等价（上游亦无调用方，保留同构占位）


def op_work(r, bar):
    """单工单在资源上的工作量（特征量）。手工追加条 [扩展] 直接取 usage/flux。"""
    if bar.get("manual"):
        usage = bar.get("usage")
        if usage is None or usage <= 0:
            return None
        return {"amt": r["input_qty"] * usage, "flux": max(1e-9, nz(bar.get("flux"), 0)),
                "key": f"{bar['level']}|{bar['step_std']}|{bar['mode']}"}
    step = next((s for s in r["steps"]
                 if s.get("seq") == bar.get("seq") and s.get("step_std") == bar.get("step_std")
                 and s.get("mode") == bar.get("mode")), None)
    if not step or step.get("missing") or not step.get("usage") or step["usage"] <= 0:
        return None
    return {"amt": r["input_qty"] * step["usage"], "flux": max(1e-9, nz(step.get("flux_base"), 0)),
            "key": f"{step['level']}|{step['step_std']}|{step['mode']}"}


def alloc_earliest(ledger: dict, key: str, from_, amt, flux, policy=None) -> dict:
    """按日产能账本分配：自 from_（相对天偏移）起找连续 dayNeeded 天满足
    used[i]+daily ≤ flux 的时段；整批占用。返回 {start, end, span, dayNeeded}（[start,end) 独占）。
    """
    rows = ledger.setdefault(key, [])

    def grow(to):
        while len(rows) <= to:
            rows.append({"used": 0.0, "slots": []})

    day_needed = ceil_int(amt / flux)
    if day_needed <= 0:
        return {"start": from_, "end": from_, "span": 0, "dayNeeded": 0}
    daily = amt / day_needed

    def day_free(i):
        pend = [s for s in rows[i]["slots"] if s > i] if i < len(rows) else []
        return min(pend) if pend else float("inf")

    def fits(start):
        grow(start + day_needed - 1)
        for i in range(start, start + day_needed):
            if rows[i]["used"] + daily > flux + 1e-9:
                return False
            # JS 同源死分支（day_free 恒 > i，保留同构）
            if policy == "nooverlap" and day_free(i) <= i:
                return False
        return True

    start = max(0, int(from_) or 0)
    limit = from_ + 3650
    while start <= limit and not fits(start):
        start += 1
    end = start + day_needed
    grow(end - 1)
    for i in range(start, end):
        rows[i]["used"] += daily
        if policy == "nooverlap":
            rows[i]["slots"] = rows[i]["slots"] + [end]
    return {"start": start, "end": end, "span": day_needed, "dayNeeded": day_needed}
```

- [ ] **Step 1.4: 运行确认通过** → 定向（预期 7 passed）；全量（预期 146 passed）
- [ ] **Step 1.5: 提交** `feat(mps): 排产解码①——账本分配 alloc_earliest 与 op_work（含手工条扩展）`

---

### Task 2: schedule.py 第二批（定序排产 + 甘特）

**Files:**
- Modify: `backend/app/mps/schedule.py`（追加 `schedule`/`schedule_process_constrained`/`gantt_chart`）
- Modify: `backend/tests/mps/test_mps_schedule.py`（追加）

- [ ] **Step 2.1: 追加失败测试（SCHED-001/002/003/004/005/007/008/009）**

```python
def _mk_results():
    from app.mps.kernel import calc_order

    ctx = _ctx_min()
    orders = [
        {"order_no": "B", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
         "water_vapor": "有", "qty": 5, "priority": 200, "features": {"N_die": 60, "N_wire": 60}},
        {"order_no": "A", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
         "water_vapor": "有", "qty": 1000, "priority": 100, "features": {"N_die": 60, "N_wire": 60}},
    ]
    return [calc_order(o, ctx) for o in orders], ctx


def test_schedule_default_equivalence():
    """capacity 缺省 True → schedule() 等价 schedule_process_constrained().planned。"""
    from app.mps.schedule import schedule, schedule_process_constrained

    r1, _ = _mk_results()
    a = schedule(r1, {"base_date": "2026-06-01", "sequenceOrder": ["B", "A"]})
    r2, _ = _mk_results()
    b = schedule_process_constrained(r2, "2026-06-01", {"sequenceOrder": ["B", "A"]})["planned"]
    assert [(r["order"]["order_no"], r["plan"]["start_date"]) for r in a] == \
           [(r["order"]["order_no"], r["plan"]["start_date"]) for r in b]


def test_schedule_process_constrained_full_contract():
    from app.mps.schedule import schedule_process_constrained

    results, _ = _mk_results()
    out = schedule_process_constrained(results, "2026-06-01", {"sequenceOrder": ["B", "A"]})
    planned, ledger = out["planned"], out["ledger"]
    assert out["capViolations"] == []                              # SCHED-008
    # SCHED-001：同单工序串行（bar.to ≤ 下一 bar.from）
    for r in planned:
        bars = [b for b in r["gantt"]["bars"] if b.get("kind") == "step"]
        for i in range(len(bars) - 1):
            assert bars[i]["to"] <= bars[i + 1]["from"], r["order"]["order_no"]
    # SCHED-003：B(5 只)走半自动、A(1000 只)走自动（按实际批量）
    b_db = next(b for b in planned[0]["gantt"]["bars"] if b["kind"] == "step")
    a_db = next(b for b in planned[1]["gantt"]["bars"] if b["kind"] == "step")
    assert b_db["res"] == "模块级|DB|半自动DB"
    assert a_db["res"] == "模块级|DB|自动DB"
    # 账本数值：B 占半自动池 day0=360；A 在自动池（与半自动互不影响）day0 起每天 63120/11
    assert ledger["模块级|DB|半自动DB"][0]["used"] == pytest.approx(360)
    assert ledger["模块级|DB|自动DB"][0]["used"] == pytest.approx(63120 / 11)
    # A 的 DB 工序整批 11 天；开工即 2026-06-01（同键资源池无他人占用）
    assert a_db["from"] == "2026-06-01" and a_db["busy_days"] == 11
    # 计划字段
    assert planned[1]["plan"]["start_date"] == "2026-06-01"
    assert out["strategy"]["id"] in ("priority", "due", "util", "setup", "bottleneck")


def test_sched_004_kit_gate():
    from app.mps.kernel import calc_order
    from app.mps.schedule import schedule_process_constrained

    results, ctx = _mk_results()
    order_c = {"order_no": "C", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
               "water_vapor": "有", "qty": 1000, "kit_date": "2026-06-05", "features": {"N_die": 60, "N_wire": 60}}
    r = calc_order(order_c, ctx)
    out = schedule_process_constrained([r], "2026-06-01", {})
    bars = [b for b in out["planned"][0]["gantt"]["bars"] if b.get("kind") == "step"]
    assert all(b["from"] >= "2026-06-05" for b in bars)            # 齐套门槛
    assert out["planned"][0]["plan"]["kit_adjusted"] is True


def test_sched_009_strategy_order_and_deterministic():
    from app.mps.schedule import schedule_process_constrained

    results, _ = _mk_results()
    # 无 sequenceOrder → 策略 orderFn（默认 priority：A(100) 先于 B(200)）
    out = schedule_process_constrained(results, "2026-06-01", {})
    assert out["planned"][0]["order"]["order_no"] == "A"
    assert out["strategy"]["id"] == "priority"
    out2 = schedule_process_constrained(results, "2026-06-01", {"strategy": "due"})
    assert out2["strategy"]["id"] == "due"


def test_sched_005_subpart_and_gantt_chart():
    from app.mps.kernel import calc_order
    from app.mps.schedule import gantt_chart, schedule_process_constrained

    results, ctx = _mk_results()
    ctx2 = {**ctx, "proc_map": {**ctx["proc_map"],
                                "M02-2D": {**ctx["proc_map"]["M02-2D"], "subpart_mode": "前置", "subpart_cycle": 2}}}
    order = {"order_no": "D", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
             "water_vapor": "有", "qty": 1000, "features": {"N_die": 60, "N_wire": 60}}
    out = schedule_process_constrained([calc_order(order, ctx2)], "2026-06-01", {})
    gantt = gantt_chart(out["planned"], {"base_date": "2026-06-01"})
    lane = gantt["lanes"][0]
    sub = next(b for b in lane["bars"] if b["kind"] == "subpart")
    assert sub["res"] == "前置分部件|M02-2D" and sub["from"] == "2026-06-01"
    assert gantt["horizon_days"] >= 1


def test_sched_007_setup_days():
    """换型（同资源键跨工艺族）：两单同为半自动档以共享资源池。"""
    from app.mps.kernel import calc_order
    from app.mps.schedule import schedule_process_constrained

    _, ctx = _mk_results()
    o1 = {"order_no": "B", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
          "water_vapor": "有", "qty": 5, "features": {"N_die": 60, "N_wire": 60}}
    o2 = {"order_no": "B2", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
          "water_vapor": "有", "qty": 10, "features": {"N_die": 60, "N_wire": 60}}
    r1, r2 = calc_order(o1, ctx), calc_order(o2, ctx)
    r1["aps"] = {"family": "F1", "type": "批产"}
    r2["aps"] = {"family": "F2", "type": "批产"}
    out = schedule_process_constrained([r1, r2], "2026-06-01",
                                       {"sequenceOrder": ["B", "B2"], "setup": True, "setupDiff": 2.0})
    b2 = out["planned"][1]
    b2_db = next(b for b in b2["gantt"]["bars"] if b["kind"] == "step")
    # B 用半自动 DB 至 day1 结束（offset 1）；B2 同键跨族 → 最早 from = 1 + 2 = offset3 → 2026-06-04
    assert b2_db["setup_days"] == 2.0
    assert b2_db["from"] == "2026-06-04"
    assert out["capViolations"] == []


def test_missing_wc_flux_guard():
    """缺 WC 主数据（日产能≈0）→ 跳过产能分配并记 warnings（护栏偏离 JS，已留痕）。"""
    from app.mps.kernel import calc_order
    from app.mps.schedule import schedule_process_constrained

    _, ctx = _mk_results()
    ctx2 = {**ctx, "wc_map": {k: v for k, v in ctx["wc_map"].items() if k != "模块级|DB"}}
    order = {"order_no": "D", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
             "water_vapor": "有", "qty": 1000, "features": {"N_die": 60, "N_wire": 60}}
    out = schedule_process_constrained([calc_order(order, ctx2)], "2026-06-01", {})
    assert len(out["warnings"]) == 1                              # 不漫游挂死（否则 grow 6.3e13 行）
    assert out["warnings"][0]["res"] == "模块级|DB|自动DB"
    assert out["planned"][0]["order"]["order_no"] == "D"          # 计划仍产出
```

**注意**：`schedule()` 返回 `planned` 列表（无容量分支不作为本批测试目标；护栏语义见 Step 2.3）。

- [ ] **Step 2.2: 运行确认失败**

- [ ] **Step 2.3: 追加实现到 `backend/app/mps/schedule.py`**

按 `schedule.js` 245-370 行逐字移植 `schedule_process_constrained`（要点与差异已在计划 3 基线明确）：
- `strat = strategy.getStrategy(opts.strategy, opts.P)` → `from app.mps import strategy as strategy_mod`；`sorted` 分支（sequenceOrder Map）与 `strat["orderFn"](results, order_opts(opts))`；
- `alloc_policy = "nooverlap" if strat["allocPolicy"] == "nooverlap" else ("nooverlap" if opts.get("setup") else strat["allocPolicy"])`；
- 循环内：`fam = (r.get("aps") or {}).get("family") if opts.get("setup") else None`；`ordered = [b for b in r["gantt"]["bars"] if b.get("kind") != "subpart"]` 排序 `(earliest_start, seq)`；`kit_offset = max(0, diff_days(base, kit)) if kit else 0`；
- `base_from = max(kit_offset, bar["earliest_start"], cursor)`；setup 逻辑同 js:294-298；`alloc = alloc_earliest(...)`；`deferredNote` 文案 `f"因 {step_label} 产能已满，整批顺延至 {add_days(base, alloc['start'])}"`（`step_label = "/".join(w["key"].split("|")[1:])`）；
- `bar["from"] = add_days(base, alloc["start"])`、`bar["to"] = add_days(base, alloc["end"])`、`bar["busy_days"] = alloc["span"]`、`bar["setup_days"] = setup_days`、`bar["res"] = w["key"]`；`cursor = alloc["end"]`；`last_family[key] = fam`、`last_end[key] = alloc["end"]`；
- `first_start`（含 subpart 条）→ `start`；`last_bar_end` → `finish = add_days(last_bar_end, -1)`（无则 `add_days(start, batch)`）；`deliver/latest/gap/judge/kit_*` 与 `rationale`（js:334-354 文案逐字）；
- `cap_violations` 核算（js:358-368：对每个 key 取首个含该资源 step 的 planned 行求 flux，逐日核验 `used > flux + 1e-9`）；
- **护栏 [扩展]（偏离 JS，已留痕）**：`w = op_work(r, bar)`；`if not w: continue`；`if w["flux"] <= 1e-9: warnings.append({"order_no": r["order"]["order_no"], "step": bar.get("step_std"), "res": w["key"], "reason": "缺少工作中心主数据（日产能为 0），已跳过产能分配"}); continue`（否则 `ceil_int(amt/1e-9)` → grow 6.3e13 行挂死；JS 同病）；
- `first_start`/`finish` 计算仅取有 `from` 的 bar（护栏跳过的条无 from）；无任何 bar 有 from 时回退 `base`；
- 返回 `{"planned": planned, "ledger": ledger, "capViolations": cap_violations, "fluxOf": flux_of, "warnings": warnings, "strategy": {...}}`。

`schedule(results, opts)`（js:72-174）：`capacity` 缺省 True → 返回 `schedule_process_constrained(...)["planned"]`；否则移植非容量时间线分支（timeline 错开、setup 区间、kit 门、plan 字段；理由文案同 js）。

`gantt_chart(results, opts)`（js:436-481）：逐字移植（lanes/bars 含 setup 条、horizon 计算 `max(1, need + 2)`；`res` 回退 `bar.get("res") or resource_key(r, b)`）。

- [ ] **Step 2.4: 运行确认通过**（预期 7 passed；全量 153 passed, 1 skipped。手算基准：B（5 只）走半自动池 day0=360；A（1000 只）在**自动池**（与半自动互不影响）从 06-01 起 11 天；setup 用例两单同为半自动档，B2 跨族最早 06-04）
- [ ] **Step 2.5: 提交** `feat(mps): 排产解码②——定序排产/甘特/硬约束核验`

---

### Task 3: operations.py（工序级需求分解与返工追加）

**Files:**
- Create: `backend/app/mps/operations.py`
- Modify: `backend/tests/mps/test_mps_schedule.py`（集成测试）或新建 `backend/tests/mps/test_mps_operations.py`

- [ ] **Step 3.1: 编写失败测试（SCHED-006 + 手工条集成）**

```python
"""工序级需求：分解/手工追加/手工条合并与排产集成（SCHED-006）。"""
import pytest
from sqlalchemy import select

from app.models.mps import OrderOperation
from app.mps.kernel import calc_order
from app.mps.operations import add_manual_operation, decompose, merge_manual_bars, sync_order_operations
from app.mps.schedule import schedule_process_constrained


def _calc_pair():
    from tests.mps.test_mps_schedule import _ctx_min  # 复用最小 ctx

    o = {"order_no": "A", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
         "water_vapor": "有", "qty": 1000, "features": {"N_die": 60, "N_wire": 60}}
    return calc_order(o, _ctx_min()), _ctx_min()


def test_decompose_from_steps():
    r, _ = _calc_pair()
    rows = decompose(r)
    assert [x["seq"] for x in rows] == [1, 2]
    assert rows[0]["op"] == "DB" and rows[0]["mode"] == "自动DB"
    assert rows[0]["qty"] == 1052 and rows[0]["feature_key"] == "N_die"
    assert rows[1]["depends_on_seq"] == 1 and rows[0]["depends_on_seq"] is None
    assert all(x["source"] == "auto" for x in rows)


def test_merge_manual_bars_after_seq():
    r, ctx = _calc_pair()
    ops = [{"after_seq": 1, "level": "模块级", "op": "调试", "mode": None, "usage": 1}]
    merged = merge_manual_bars(r, ops, ctx)
    mb = merged[-1]
    assert mb["manual"] is True and mb["level"] == "模块级"
    assert mb["earliest_start"] == 0               # 前道条（DB, seq=1）earliest_start=0
    assert mb["seq"] == 1.5                        # 排序保持在前道条之后
    assert mb["flux"] == 10000 and mb["mode"] == "/"


async def test_sched_006_rework_extra_operation(sqlite_session):
    r, ctx = _calc_pair()
    merged = merge_manual_bars(r, [{"after_seq": 1, "level": "模块级", "op": "调试", "mode": None, "usage": 1}], ctx)
    out = schedule_process_constrained([r], "2026-06-01", {})
    bars = [b for b in out["planned"][0]["gantt"]["bars"] if b.get("kind") == "step"]
    manual_bar = next(b for b in bars if b.get("manual"))
    assert manual_bar["res"] == "模块级|调试|/"     # 参与资源占用
    assert "模块级|调试|/" in out["ledger"]         # 占用产能账本
    assert out["capViolations"] == []


async def test_sync_and_manual_persistence(sqlite_session):
    r, ctx = _calc_pair()
    o = Order(order_no="O-1", product="P", code="M02-2D", qty=1000, features={"N_die": 60, "N_wire": 60})
    sqlite_session.add(o)
    await sqlite_session.commit()
    n = await sync_order_operations(sqlite_session, o.id, r)
    assert n == 2
    await add_manual_operation(sqlite_session, o.id, level="模块级", op="调试", mode=None,
                               qty=1052, usage=1, after_seq=1, note="返工调试")
    rows = (await sqlite_session.execute(select(OrderOperation).order_by(OrderOperation.seq))).scalars().all()
    assert [(x.seq, x.source) for x in rows] == [(1, "auto"), (2, "auto"), (3, "manual")]
    assert rows[2].depends_on_id == rows[0].id     # 挂在 seq=1 之后（自动行）
    n2 = await sync_order_operations(sqlite_session, o.id, r)   # 重同步：auto 重建、manual 保留
    assert n2 == 2
    rows2 = (await sqlite_session.execute(select(OrderOperation).order_by(OrderOperation.seq))).scalars().all()
    assert [x.source for x in rows2].count("manual") == 1
```

**注意**：`decompose` 输出列表的 `seq` 用工序 seq；`sync` 持久化时 auto 行按 seq 从 1 连续重排（插入 manual 行后 auto 行 seq 不变、manual 行 seq 取"前道 seq+1 后的小数"不可行——**本实现约定**：manual 行 `seq = max(已有 seq)+1`（追加在末位），依赖关系由 `depends_on_id` 表达；`merge_manual_bars` 的定位以 `after_seq` 为准。执行者按此约定实现并保持测试断言（如与实现冲突，先核对本约定）。

- [ ] **Step 3.2: 运行确认失败**

- [ ] **Step 3.3: 创建 `backend/app/mps/operations.py`**

```python
"""工序级需求（设计 D12）：产品工单按路线自动分解；手工追加（返工/试制）参与排产。

- decompose：从核算结果的 steps 生成工序级需求（自动行）
- sync_order_operations：auto 行删除重建（depends_on_id 按 seq 链）；manual 行保留
- add_manual_operation：手工追加工序需求（挂在指定 seq 的 auto 行之后）
- merge_manual_bars：把手工行转换为解码层可消费的 extra bars（[扩展] manual 标记）
"""
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mps import OrderOperation
from app.mps.kernel import nz, pick_mode


def decompose(calc_result) -> list[dict]:
    rows = []
    prev = None
    for s in calc_result.get("steps", []):
        rows.append({
            "seq": s.get("seq"), "level": s.get("level"), "op": s.get("step_std"),
            "mode": s.get("mode"), "qty": calc_result.get("input_qty"),
            "unit": s.get("unit"), "feature_key": s.get("feature_key"),
            "feature_usage": s.get("usage"), "source": "auto",
            "depends_on_seq": prev, "note": None,
        })
        prev = s.get("seq")
    return rows


async def sync_order_operations(session: AsyncSession, order_id: str, calc_result) -> int:
    """重建该单自动工序需求（manual 行保留），返回插入行数。"""
    await session.execute(
        delete(OrderOperation).where(OrderOperation.order_id == order_id, OrderOperation.source == "auto"))
    rows = decompose(calc_result)
    by_seq: dict = {}
    for row in rows:
        op = OrderOperation(order_id=order_id, seq=row["seq"], level=row["level"], op=row["op"],
                            mode=row["mode"], qty=row["qty"], unit=row["unit"],
                            feature_key=row["feature_key"], feature_usage=row["feature_usage"],
                            source="auto", note=None)
        session.add(op)
        await session.flush()
        by_seq[row["seq"]] = op.id
        if row["depends_on_seq"] is not None:
            op.depends_on_id = by_seq.get(row["depends_on_seq"])
    await session.commit()
    return len(rows)


async def add_manual_operation(session: AsyncSession, order_id: str, *, level: str, op: str,
                               mode=None, qty=None, usage=None, after_seq=None, note=None) -> OrderOperation:
    """手工追加工序需求（返工/试制）；seq 追加在末位，依赖由 depends_on_id 表达。"""
    max_seq = (await session.execute(
        select(OrderOperation.seq).where(OrderOperation.order_id == order_id)
        .order_by(OrderOperation.seq.desc()).limit(1))).scalar() or 0
    dep_id = None
    if after_seq is not None:
        dep_id = (await session.execute(
            select(OrderOperation.id).where(OrderOperation.order_id == order_id,
                                            OrderOperation.seq == after_seq).limit(1))).scalar()
    rec = OrderOperation(order_id=order_id, seq=int(max_seq) + 1, level=level, op=op, mode=mode,
                         qty=qty, feature_usage=usage, source="manual",
                         depends_on_id=dep_id, note=note)
    session.add(rec)
    await session.commit()
    return rec


def merge_manual_bars(calc_result, manual_ops: list[dict], ctx: dict) -> list[dict]:
    """手工工序需求 → 解码层 bars（追加进 calc_result['gantt']['bars']）并返回 bars 列表。

    manual_ops 每项：{after_seq, level, op, mode?, usage}
    - flux 按订单实际批量分流从主数据解析（缺主数据 → flux None → 解码时跳过并告警）
    - seq 取前道条 seq + 0.5（排序保持其后）；earliest_start 取前道条同值
    """
    bars = calc_result["gantt"]["bars"]
    qty = calc_result["input_qty"]
    p = ctx["params"]
    use_peak = str(p.get("use_peak") or "mean") == "peak"
    for m in manual_ops:
        wc = ctx["wc_map"].get(f"{m['level']}|{m['op']}")
        picked = pick_mode(wc, qty) if wc else None
        flux = None
        mode = m.get("mode")
        if picked:
            mode = mode or picked["mode_name"]
            flux = nz(picked["mode"].get("flux_peak"), 0) if use_peak else nz(picked["mode"].get("flux_base"), 0)
        pred = next((b for b in bars
                     if b.get("kind") == "step" and b.get("seq") == m.get("after_seq")), None)
        bar = {"kind": "step", "seq": (pred["seq"] + 0.5) if pred else (max(
                   [b.get("seq") or 0 for b in bars if b.get("kind") == "step"] or [0]) + 1),
               "step_std": m["op"], "step_raw": m["op"], "level": m["level"], "mode": mode or "/",
               "usage": m.get("usage"), "flux": flux, "manual": True,
               "earliest_start": pred["earliest_start"] if pred else 0,
               "is_bottleneck": False, "throughput": None}
        bars.append(bar)
    return bars
```

- [ ] **Step 3.4: 运行确认通过**（预期 4 passed；全量 157 passed, 1 skipped）
- [ ] **Step 3.5: 提交** `feat(mps): 工序级需求分解与返工追加（operations）`

---

### Task 4: kanban.py（日任务看板）

**Files:**
- Create: `backend/app/mps/kanban.py`
- Create: `backend/tests/mps/test_mps_kanban.py`

- [ ] **Step 4.1: 编写失败测试**

```python
"""日任务看板（kanban.js 移植）：任务展开/筛选/状态分级/汇总。"""
from app.mps.kanban import build_kanban, parse_res


def test_parse_res():
    assert parse_res("模块级|DB|自动DB") == {"level": "模块级", "op": "DB", "mode": "自动DB"}
    assert parse_res("前置分部件|M02-2D") == {"level": "前置", "op": "分部件", "mode": "M02-2D"}
    assert parse_res(None) is None


def _fixture():
    planned = [{
        "order": {"order_no": "A", "product": "P", "code": "M02-2D", "kit_date": "2026-06-01", "due_date": "2026-06-20"},
        "input_qty": 1052, "plan": {"judge": "满足", "strategy_name": "优先级", "kit_risk": False},
        "gantt": {"bars": [
            {"kind": "step", "seq": 1, "step_std": "DB", "res": "模块级|DB|自动DB",
             "from": "2026-06-01", "to": "2026-06-12", "busy_days": 11},
            {"kind": "step", "seq": 2, "step_std": "WB", "res": "模块级|WB|自动WB",
             "from": "2026-06-12", "to": "2026-06-18", "busy_days": 6},
        ]},
    }]
    ledger = {"模块级|DB|自动DB": [{"used": 5738.18, "slots": []}] * 11 + [],
              "模块级|WB|自动WB": [{"used": 0, "slots": []}] * 17}
    flux_of = {"模块级|DB|自动DB": 6000, "模块级|WB|自动WB": 12000}
    return planned, ledger, flux_of


def test_build_kanban_tasks_and_status():
    planned, ledger, flux_of = _fixture()
    kb = build_kanban(planned, ledger, flux_of, {"base_date": "2026-06-01", "date": "2026-06-02"})
    assert kb["ok"] is True and kb["summary"]["task_count"] == 1
    t = kb["tasks"][0]
    assert t["res"] == "模块级|DB|自动DB" and t["order_no"] == "A"
    assert t["load_rate"] == pytest.approx(round(5738.18 / 6000, 3))
    assert t["status"] == "正常" and t["warnings"] == []


def test_build_kanban_overload_and_filters():
    planned, ledger, flux_of = _fixture()
    ledger["模块级|DB|自动DB"][1] = {"used": 7000, "slots": []}
    kb = build_kanban(planned, ledger, flux_of, {"base_date": "2026-06-01", "date": "2026-06-02"})
    assert kb["tasks"][0]["status"] == "超负荷"
    assert kb["summary"]["overload_count"] == 1
    kb2 = build_kanban(planned, ledger, flux_of, {"base_date": "2026-06-01", "date": "2026-06-02", "level": "组件级"})
    assert kb2["tasks"] == [] and kb2["summary"]["task_count"] == 0
    assert kb["filters"]["levels"] == ["模块级"] and kb["groups"][0]["res"] == "模块级|DB|自动DB"
```

**注意**：测试顶部需 `import pytest`。

- [ ] **Step 4.2: 运行确认失败**

- [ ] **Step 4.3: 创建 `backend/app/mps/kanban.py`**（按 `kanban.js` 121 行逐字移植：`parse_res`、`build_kanban`（任务展开/筛选/状态优先级 超负荷>延期>缺料>正常/汇总/分组排序 `max_load_rate` 降序）、`_empty_summary`）

- [ ] **Step 4.4: 运行确认通过**（预期 3 passed；`test_build_kanban_tasks_and_status` 的高负荷日需按 `qIdx` 命中 day1——执行者按日期窗口核对）
- [ ] **Step 4.5: 提交** `feat(mps): 日任务看板移植（kanban）`

---

### Task 5: 3B1 收尾（对照抽查 + 执行记录）

- [ ] **Step 5.1: 对照抽查**：`schedule.py` ↔ `schedule.js` 挑三段（alloc_earliest 207-243、schedule_process_constrained 250-370、gantt_chart 436-481）逐行核对；`operations.py` 为扩展模块（对照设计 D12 检查语义）；`kanban.py` ↔ kanban.js 全量核对。报告结论。
- [ ] **Step 5.2: 全量回归**（预期 160 passed, 1 skipped）
- [ ] **Step 5.3: 执行记录**：更新计划 3 执行记录（3B1 节：摘要/决策/教训；SCHED 清单回写统一留待 3B2 收尾）并提交。

---

## 完成定义（3B1 结束时）

1. `schedule.py`（解码器 + 甘特）与 `schedule.js` 逐段对齐（Task 5 抽查）；`operations.py`/`kanban.py` 就绪；
2. SCHED-001/002/003/004/005/006/007/008/009 测试全绿；
3. 全量测试绿灯（160 passed, 1 skipped）；每任务独立提交。

## 后续衔接（3B2）

- `aps.py`（gate/启发式/局部搜索/指标/评估）→ `ga.py`（DEAP 求解核心 + PARAM_DEFS 增 ga_population/ga_generations/ga_seed）→ `solver.py`（模式门面：ga 默认/确定性基准/heuristic；CP-SAT 延后留痕）→ `schedule_service.py`（载单/运行/批次与分配落库/订单回写，SCHED-010）→ SCHED 清单回写与计划 3 最终审查。
- 3B2 须消费的回调契约：`schedule_process_constrained(results, base, opts)`、`gantt_chart(planned, {"base_date": ...})`、`ledger/fluxOf`（周负荷与看板共用）、`merge_manual_bars`。

## Self-Review 记录

- 规格覆盖：SCHED-001~009 全部映射（010 归 3B2）；operations 覆盖 D12/SCHED-006。
- 占位符扫描：无 TBD；Task 2 的警示"如与实现冲突核对手算"给出具体手算值（06-02/63120/11），非含糊表述。
- 类型一致性：`ledger[key][i].used/slots`、`bars[].from/to/res/busy_days/setup_days`、`plan{}` 字段与 kanban/3B2 消费一致；`op_work` 返回 `{amt, flux, key}` 三键贯穿。
