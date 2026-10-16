# MPS 改造 计划 3B2/6：APS 门面 · GA 求解 · 排产落库 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 移植 mps-web 的 **APS 门面层**（`aps.js`：产能闸值门控/成组启发式定序 GT/指标/局部搜索/运行编排）并新建 **GA 求解核心**（DEAP 序列搜索，设计 D11 默认求解器）与 **求解门面**（`solver.py`：ga 默认 / deterministic 确定性基准 / heuristic / cp_sat 延后留痕）及 **排产落库服务**（`schedule_service.py`：载单 → 求解 → 批次与每日分配落库 → 订单回写，CHK-SCHED-010），补齐计划 3 的 SCHED 全部条目并回写 check-list。

**Architecture:** `app/mps/aps.py`（纯函数移植，消费 kernel 结果 dict）→ `app/mps/ga.py`（DEAP 求解核心，新，设计 D11）→ `app/mps/solver.py`（模式门面，新增；统一 apsRun 形状 + solver 元信息 + decode 出口）→ `app/mps/schedule_service.py`（唯一碰 DB 的排产模块：批次/分配/回写，单事务）。

**Tech Stack:** Python 3.13.5（内嵌 `offline\runtime\python\python.exe`）、pytest（asyncio_mode=auto）；新增依赖 `deap==1.4.4`（已装入内嵌运行时实测可用）；沿用 tests/mps 夹具风格与 SQLite 临时库夹具（`sqlite_session`）。

**唯一移植参照（只读）：** `F:\MPS\mps-web\src\aps.js`（207 行）。GA/solver/service 为本系统新实现（设计 D11/D12 与 3B1 契约），无 JS 对照。

**check-list 覆盖（3B2 负责）：** CHK-SCHED-008/009/010 的实现与测试；CHK-SCHED-001~007 为 3B1 已实现，本计划 Task 5 统一回写状态与实测测试路径（接收自 3B1 移交项）。

**结果契约（API/前端消费）：**

- `solver.solve(results, ctx, opts)` → `{method, solver{mode,seed,population,generations,improved,objective,baseline_objective}, strategy{id,name,allocPolicy,objective,desc}, strategyMetrics, gate{passed,blocked,warned,counts}, sequence[order_no], schedule[planned], load, lineBottleneck, metrics, baseline{metrics,delta}, params, gantt, decode{ledger,fluxOf,capViolations}, warnings}`
- `schedule_service.run_schedule(session, base_date, opts)` → `{batch_id, batch_no, base_date, solver_mode, strategy_id, kpi, solver, order_count, allocation_rows, warnings}`
- 落库：`schedule_batch`（batch_no/params_snapshot/kpi）、`schedule_allocation`（按日分配明细：resource_key/work_date/qty/operation_id）、`orders` 回写 16 字段。

**探针实证（2026-10-16，本计划所有断言值均由此产出）：** 临时探针 `probe_aps.py`/`probe_ga.py`/`probe_service.py`/`probe_ops.py`（`C:\Users\17970\AppData\Local\Temp\opencode\`，仅作证据不入库）。要点：

- 探针发现并修正移植 bug：`aps_sequence_heuristic` 族内排序键在 DB 直读路径会得到 `datetime.date` 对象，与字符串哨兵 `"9999"` 不可比（JS 恒为字符串）→ 统一 `str()` 归一（本计划 Task 1 代码已含）。
- `tools.cxOrdered` 要求整数基因 → GA 染色体必须为**索引排列**（`list(range(n))` 的重排，索引映射回 passed 列表），不能用结果 dict 作基因。
- DEAP `tools.HallOfFame.insert` 内部 `deepcopy`；GA 以 `random.seed` 前保存 `random.getstate()`、后 `setstate` 恢复，实测全局随机流不受污染。
- `run_ga`（5 单/2 族夹具，pop8/gen3/seed42）两次运行结果一致 `[WO-4,WO-2,WO-5,WO-3,WO-1]`、objective==baseline==6.003333205390996（无改进）；`seed=0 → None`；pop2/gen0 时最优=第一个种子序列。
- `solve` deterministic 与直接 `schedule_process_constrained` 输出逐条相等（equal=True）；heuristic 复现一致；cp_sat→NotImplementedError、未知模式→ValueError、空 passed→ValueError（文案见测试）。
- `run_schedule` 实跑：batch_no `SCH-20260601-001/002` 递增、deterministic 32 行分配（A 27 + B 5）、按日 qty 合计=1.052×60 特征量口径、订单回写 16 字段实测值全部取得（见 Task 4 测试断言）。
- `sync_order_operations` 重同步后手工行 `depends_on_id` 指向已删除的旧自动行（悬挂）——探针实证该 3B1 移交缺陷，Task 4 修复（重挂到新自动行 id）。

**基线：** `166 passed, 1 skipped`（本计划前，实测 27.3s；内嵌 Python + `python -m pytest tests -q`，workdir=backend）。

---

### Task 1: aps.py（aps.js 逐字移植）+ 序启发式 date 归一修复

**Files:**
- Create: `backend/app/mps/aps.py`
- Create: `backend/tests/mps/test_mps_aps.py`

- [x] **Step 1.1: 编写失败测试**（夹具与断言值均来自探针实测）

```python
"""APS 门面：门控/成组启发式/指标/评估/局部搜索/编排（移植 aps.js）。"""
import random

import pytest

from app.mps.aps import (
    DEFAULT_WEIGHTS, aps_evaluate, aps_gate, aps_optimize, aps_run,
    aps_sequence_heuristic, derive_family, derive_type, objective,
)
from app.mps.kernel import calc_order
from tests.mps.test_mps_schedule import _ctx_min

BASE = "2026-06-01"


def _ctx_two_fam():
    ctx = _ctx_min()
    ctx["proc_map"]["M04-CP"] = {"code": "M04-CP", "ramp_days": 0, "subpart_mode": None, "subpart_cycle": 0}
    ctx["route_map"]["M04-CP"] = [
        {"code": "M04-CP", "seq": 1, "step_raw": "测试", "step_std": "测试", "level": "模块级",
         "cycle": 1, "yield_overall": 0.99, "feature": "工单产品数量N", "cf_field": None},
        {"code": "M04-CP", "seq": 2, "step_raw": "DB", "step_std": "DB", "level": "模块级",
         "cycle": 1, "yield_overall": 0.97, "feature": "DB-芯片数N_die", "cf_field": "DB胶水类型Y_die"},
    ]
    ctx["wc_map"]["模块级|测试"] = {"modes": [
        {"mode": "/", "flux_base": 9999, "flux_peak": 10999, "split_threshold": 1, "unit": "套/天"}]}
    return ctx


def gate_fixture():
    """门控夹具：A/E/B（E=首单研发）+ 错误行 X；E/B 合计超 DB 半自动周产能 → 通报。"""
    ctx = _ctx_min()
    # _ctx_min 的 route 为 DB/WB 两工序；qty=500 → Q=526（yRatio 1/0.9506）
    specs = [
        {"order_no": "A", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
         "water_vapor": "有", "qty": 500, "priority": 100, "due_date": "2026-09-30",
         "kit_date": "2026-06-01", "features": {"N_die": 60, "N_wire": 60}},
        {"order_no": "E", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "首单",
         "water_vapor": "有", "qty": 500, "priority": 120, "kit_date": "2026-06-01",
         "features": {"N_die": 60, "N_wire": 60}},
        {"order_no": "B", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
         "water_vapor": "有", "qty": 2000, "priority": 130, "kit_date": "2026-06-01",
         "features": {"N_die": 60, "N_wire": 60}},
    ]
    results = [calc_order(s, ctx) for s in specs]
    results.append({"error": "未找到成套工艺：M99", "order": {"order_no": "X", "qty": 1, "priority": 100}})
    return results, ctx


def seq_fixture():
    """定序夹具：5 单 2 族（M02 批产3+研发1，M04 批产1），全部齐套、门控零通报。"""
    ctx = _ctx_two_fam()
    specs = [
        {"order_no": "WO-2", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
         "water_vapor": "有", "qty": 200, "priority": 100, "due_date": "2026-09-01",
         "kit_date": "2026-06-01", "features": {"N_die": 60, "N_wire": 60}},
        {"order_no": "WO-5", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
         "water_vapor": "有", "qty": 100, "priority": 120, "due_date": "2026-10-01",
         "kit_date": "2026-06-01", "features": {"N_die": 60, "N_wire": 60}},
        {"order_no": "WO-4", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
         "water_vapor": "有", "qty": 150, "priority": 150, "due_date": "2026-08-01",
         "kit_date": "2026-06-01", "features": {"N_die": 60, "N_wire": 60}},
        # 研发单 priority=50：策略序（priority orderFn）与 GT 启发式序刻意不同，供 solver/GA 测试区分
        {"order_no": "WO-3", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "首单",
         "water_vapor": "有", "qty": 5, "priority": 50, "due_date": "2026-06-01",
         "kit_date": "2026-06-01", "features": {"N_die": 60, "N_wire": 60}},
        {"order_no": "WO-1", "product": "P", "code": "M04-CP", "order_type": "常规", "first_flag": "否",
         "water_vapor": "无", "qty": 10, "priority": 300, "due_date": "2026-07-01",
         "kit_date": "2026-06-01", "features": {"N_die": 60}},
    ]
    return [calc_order(s, ctx) for s in specs], ctx


def test_derive_family_and_type():
    assert derive_family({"code": "M02-2D"}) == "M02"
    assert derive_family({}, {"code": "M04-CP"}) == "M04"
    assert derive_family({"code": ""}) == "NA"
    assert derive_type({"first_flag": "首单"}) == "研发"
    assert derive_type({"first_flag": "复线"}) == "研发"
    assert derive_type({"first_flag": "否"}) == "批产"
    assert derive_type({}) == "批产"


def test_aps_gate_warn_mode():
    results, ctx = gate_fixture()
    g = aps_gate(results, ctx, {"base_date": BASE})
    assert [r["order"]["order_no"] for r in g["passed"]] == ["A", "E", "B"]
    assert [w["order_no"] for w in g["warned"]] == ["E", "B"]
    assert g["blocked"] == []
    assert g["warned"][0]["reasons"] == ["产能闸值超 1.0"]
    assert g["warned"][0]["family"] == "M02" and g["warned"][0]["type"] == "研发"
    qty = {r["order"]["order_no"]: r["input_qty"] for r in results if not r.get("error")}
    assert qty == {"A": 526, "E": 526, "B": 2104}
    assert g["passed"][0]["aps"] == {"family": "M02", "type": "批产"}   # 警告仍放行并注入 aps
    assert g["passed"][1]["aps"]["type"] == "研发"


def test_aps_gate_block_mode():
    results, ctx = gate_fixture()
    g = aps_gate(results, ctx, {"base_date": BASE, "gate_mode": "block"})
    assert [r["order"]["order_no"] for r in g["passed"]] == ["A"]
    assert [b["order_no"] for b in g["blocked"]] == ["E", "B"]
    assert g["warned"] == []
    assert set(g["blocked"][0]) == {"order_no", "product", "code", "family", "type", "qty", "reasons"}
    blocked_rows = [r for r in results if not r.get("error") and r["order"]["order_no"] in ("E", "B")]
    assert all("aps" not in r for r in blocked_rows)                    # 被拦者不注入 aps
    assert {"total": len(results), "passed": len(g["passed"]),
            "blocked": len(g["blocked"]), "warned": len(g["warned"])} == \
        {"total": 4, "passed": 1, "blocked": 2, "warned": 0}


def test_aps_sequence_heuristic_grouping():
    results, ctx = seq_fixture()
    g = aps_gate(results, ctx, {"base_date": BASE})
    assert (len(g["passed"]), g["blocked"], g["warned"]) == (5, [], [])
    seq = aps_sequence_heuristic(g["passed"])
    assert [r["order"]["order_no"] for r in seq] == ["WO-2", "WO-5", "WO-4", "WO-3", "WO-1"]
    # 批产先于研发（族内）；族序按最早交期（M02:06-01 < M04:07-01）
    aps_of = {r["order"]["order_no"]: r["aps"] for r in seq}
    assert aps_of["WO-3"] == {"family": "M02", "type": "研发"}
    assert aps_of["WO-1"] == {"family": "M04", "type": "批产"}


def test_aps_metrics_and_evaluate_setup_switch():
    results, ctx = seq_fixture()
    seq = aps_sequence_heuristic(aps_gate(results, ctx, {"base_date": BASE})["passed"])
    ev = aps_evaluate(seq, ctx, {"base_date": BASE, "setup": False})
    assert ev["metrics"] == {
        "tardiness": 4, "maxLate": 4, "setupTotal": 0.0, "onTime": 4, "lateN": 1,
        "imbalance": pytest.approx(0.3033332053909957), "makespan": 7, "overloadWC": 0}
    plan = {r["order"]["order_no"]: r["plan"] for r in ev["planned"]}
    assert (plan["WO-3"]["start_date"], plan["WO-3"]["finish_date"], plan["WO-3"]["gap_days"]) == \
        ("2026-06-01", "2026-06-02", -4)
    assert (plan["WO-2"]["gap_days"], plan["WO-5"]["gap_days"], plan["WO-4"]["gap_days"],
            plan["WO-1"]["gap_days"]) == (87, 115, 52, 27)
    ev2 = aps_evaluate(seq, ctx, {"base_date": BASE, "setup": True, "setupDiff": 0.5})
    assert ev2["metrics"]["setupTotal"] == 0.5
    sb = next(b for r in ev2["planned"] for b in r["gantt"]["bars"] if b.get("setup_days"))
    assert (sb["res"], sb["from"], sb["to"], sb["setup_days"]) == \
        ("模块级|DB|半自动DB", "2026-06-02", "2026-06-03", 0.5)
    assert objective(ev2["metrics"], DEFAULT_WEIGHTS) == pytest.approx(6.003333205390996)


def test_aps_optimize_reproducible():
    results, ctx = seq_fixture()
    passed = aps_gate(results, ctx, {"base_date": BASE})["passed"]
    o1 = aps_optimize(passed, ctx, {"base_date": BASE, "setup": True, "setupDiff": 0.5,
                                    "iterations": 50, "rng": random.Random(42)})
    results2, ctx2 = seq_fixture()
    passed2 = aps_gate(results2, ctx2, {"base_date": BASE})["passed"]
    o2 = aps_optimize(passed2, ctx2, {"base_date": BASE, "setup": True, "setupDiff": 0.5,
                                      "iterations": 50, "rng": random.Random(42)})
    assert [r["order"]["order_no"] for r in o1["seq"]] == \
        [r["order"]["order_no"] for r in o2["seq"]] == ["WO-2", "WO-5", "WO-4", "WO-3", "WO-1"]
    assert o1["improved"] is False
    assert o1["objective"] == pytest.approx(6.003333205390996)


def test_aps_run_default_and_setup_strategy():
    results, ctx = seq_fixture()
    run = aps_run(results, ctx, {"base_date": BASE})
    assert run["method"] == "heuristic(GT)"
    assert run["strategy"] == {"id": "priority", "name": "订单优先级优先", "desc": "默认全序排产"}
    assert run["sequence"] == ["WO-2", "WO-5", "WO-4", "WO-3", "WO-1"]
    assert run["gate"]["counts"] == {"total": 5, "passed": 5, "blocked": 0, "warned": 0}
    results2, ctx2 = seq_fixture()
    run2 = aps_run(results2, ctx2, {"base_date": BASE, "strategy": "setup"})
    assert run2["method"] == "strategy(换线换模最少（GT 成组）)"
    assert run2["sequence"] == ["WO-3", "WO-4", "WO-2", "WO-5", "WO-1"]
    assert run2["strategy"]["id"] == "setup" and run2["strategy"]["allocPolicy"] == "nooverlap"
    assert run2["strategy"]["objective"] == {"tardy": 1, "setup": 4, "imbal": 1, "makespan": 0.1}
    assert run2["strategyMetrics"]["onTimeRate"] == 80.0
    assert run2["baseline"]["delta"]["setupTotal"] == 0.5
    assert run2["gantt"]["base_date"] == "2026-06-01" and run2["gantt"]["horizon_days"] == 124
    assert [l["order_no"] for l in run2["gantt"]["lanes"]] == ["WO-3", "WO-4", "WO-2", "WO-5", "WO-1"]


def test_aps_run_optimize_mode():
    results, ctx = seq_fixture()
    run = aps_run(results, ctx, {"base_date": BASE, "strategy": "priority", "method": "optimize",
                                 "iterations": 30, "rng": random.Random(7)})
    assert run["method"] == "heuristic+local-search"
    assert run["sequence"] == ["WO-2", "WO-5", "WO-4", "WO-3", "WO-1"]
    assert run["metrics"] == {
        "tardiness": 4, "maxLate": 4, "setupTotal": 0.5, "onTime": 4, "lateN": 1,
        "imbalance": pytest.approx(0.3033332053909957), "makespan": 7, "overloadWC": 0}
    assert run["lineBottleneck"][0]["key"] == "模块级|DB|自动DB"
    assert run["gantt"]["horizon_days"] == 124
```

- [x] **Step 1.2: 运行确认失败**

```powershell
$env:PYTHONIOENCODING="utf-8"; & "F:\aps-hap\offline\runtime\python\python.exe" -m pytest tests/mps/test_mps_aps.py -q
```
预期：collection error `ModuleNotFoundError: No module named 'app.mps.aps'`。

- [x] **Step 1.3: 创建 `backend/app/mps/aps.py`**（按 `aps.js` 207 行移植；含探针实证的 date 归一修复）

```python
"""APS 门面层（移植自 mps-web src/aps.js；纯计算，不写库）。

职责：门控（warn/block 产能闸值）、成组启发式定序（GT）、指标/目标函数、
邻域交换局部搜索、运行编排（策略定序 → 评估 → 周负荷/线瓶颈）。

移植约定（与 JS 的 micro 差异，均已经 3B2 探针实证）：
- JS `Math.random` → 注入 `rng`（缺省模块级 random）；`aps_optimize` 可传 `random.Random(seed)` 复现；
- `ctx.P` → `ctx["params"]`；`prio.cmpResult` → `prio.cmp_result`；`Math.round(x*1000)/1000` → `dates.js_round`；
- 启发式族内交期排序键兼容 `datetime.date`（DB 直读）与字符串（夹具），统一 `str()` 归一
  （JS 恒为字符串；探针实测直读 DB 时 date 与 "9999" 哨兵不可比，2026-10-16 修复）；
- `aps_evaluate`/`aps_optimize` 对输入序 `copy.deepcopy`（JS 展开语义），保证入参不被改动；
- reasons 文案 `产能闸值超 {cap_threshold}`：Python 渲染默认值 `1.0`（JS 模板渲染 `1`）——纯文案
  micro 差异，测试锁定 `1.0`。
"""
import copy
import random
from datetime import date
from functools import cmp_to_key

from app.mps import priority as prio
from app.mps import strategy as strategy_mod
from app.mps.dates import diff_days, js_round, to_str
from app.mps.kernel import nz
from app.mps.load import line_bottleneck, weekly_load
from app.mps.schedule import gantt_chart, schedule

DEFAULT_WEIGHTS = {"tardy": 1, "setup": 2, "imbal": 1, "makespan": 0.1}


def derive_family(order, proc=None) -> str:
    """工艺族：工艺代号前缀（M02-2D → M02）；缺码回退 NA。"""
    code = (order or {}).get("code") or (proc or {}).get("code") or ""
    fam = str(code).split("-")[0]
    return fam or "NA"


def derive_type(order) -> str:
    """订单类型：首单/复线/变更首件 → 研发，其余 → 批产。"""
    f = str((order or {}).get("first_flag") or "否")
    return "研发" if f in ("首单", "复线", "变更首件") else "批产"


def aps_gate(results, ctx, opts=None) -> dict:
    """APS 门控：按全序排定后累计周产能账本，超闸值（cap_threshold）标记 reasons。

    warn（默认）：超闸值仍放行（记入 warned，且继续累计账本）；
    block：超闸值硬拦截（不入账本）；缺齐套时间一律记 reasons。错误行不参与。
    """
    opts = opts or {}
    p = ctx["params"]
    cap_threshold = nz(opts.get("cap_threshold"), 1.0)
    mode = opts.get("gate_mode") or "warn"
    week_days = nz(p.get("week_days"), 6)
    use_peak = str(p.get("use_peak") or "mean") == "peak"
    peak_factor = nz(p.get("peak_factor"), 1.1)
    load_acc: dict = {}
    blocked, warned, passed = [], [], []
    seq = sorted((r for r in results if not r.get("error")), key=cmp_to_key(prio.cmp_result))
    for r in seq:
        fam = derive_family(r.get("order"), r.get("process"))
        type_ = derive_type(r.get("order"))
        kit_ok = bool((r.get("order") or {}).get("kit_date"))
        cap_hit = False
        adds: dict = {}
        for s in r["steps"]:
            if not s.get("wc_key"):
                continue
            key = f"{s['wc_key']}|{s.get('mode')}"
            add = r["input_qty"] * (s.get("usage") or 0)
            adds[key] = add
            cur = load_acc.get(key, 0)
            flux = nz(s.get("flux_base"), 0) * (peak_factor if use_peak else 1)
            avail = flux * week_days
            if avail > 0 and (cur + add) / avail > cap_threshold:
                cap_hit = True
        reasons = []
        if not kit_ok:
            reasons.append("齐套未到(缺物料齐套时间)")
        if cap_hit:
            reasons.append(f"产能闸值超 {cap_threshold}")
        if reasons:
            item = {"order_no": r["order"]["order_no"], "product": r["order"]["product"],
                    "code": r["process"]["code"], "family": fam, "type": type_,
                    "qty": r["order"]["qty"], "reasons": reasons}
            if mode == "block":
                blocked.append(item)
                continue
            warned.append(item)
        for k in adds:
            load_acc[k] = load_acc.get(k, 0) + adds[k]
        r["aps"] = {"family": fam, "type": type_}
        passed.append(r)
    return {"passed": passed, "blocked": blocked, "warned": warned}


def aps_sequence_heuristic(passed) -> list:
    """成组启发式（GT）：族序按族内最早交期；族内批产先于研发，再按全序 comparator。"""
    groups: dict = {}
    for r in passed:
        groups.setdefault(r["aps"]["family"], []).append(r)

    def fam_key(fam):
        return min((str(r["order"].get("due_date") or "9999") for r in groups[fam]), default="9999")

    fams = sorted(groups.keys(), key=fam_key)

    def cmp(x, y):
        tx = 0 if x["aps"]["type"] == "批产" else 1
        ty = 0 if y["aps"]["type"] == "批产" else 1
        if tx != ty:
            return tx - ty
        return prio.cmp_result(x, y)

    seq: list = []
    for fam in fams:
        seq.extend(sorted(groups[fam], key=cmp_to_key(cmp)))
    return seq


def aps_metrics(planned, ctx, opts=None) -> dict:
    """指标：拖期/最大迟到/换型合计/准时/失衡（load_rate 标准差）/跨度/超载工序数。"""
    opts = opts or {}
    base = opts.get("base_date")
    p = ctx["params"]
    tardiness = 0
    max_late = 0
    setup_total = 0.0
    on_time = 0
    late_n = 0
    for r in planned:
        if r.get("error"):
            continue
        gap = (r.get("plan") or {}).get("gap_days")
        late = -gap if (gap is not None and gap < 0) else 0
        if late > max_late:
            max_late = late
        tardiness += late
        if gap is not None and gap >= 0:
            on_time += 1
        elif gap is not None:
            late_n += 1
        for b in r["gantt"]["bars"]:
            if b.get("setup_days"):
                setup_total += b["setup_days"]
    load = weekly_load(planned, {"params": p})
    rates = [x for x in (l.get("load_rate") for l in load) if x is not None and x > 0]
    mean = sum(rates) / len(rates) if rates else 0
    imbalance = (sum((b - mean) ** 2 for b in rates) / (len(rates) or 1)) ** 0.5
    fin = [(diff_days(base, (r.get("plan") or {}).get("finish_date")) or 0)
           for r in planned if not r.get("error")]
    makespan = max(fin) if fin else 0
    return {"tardiness": tardiness, "maxLate": max_late, "setupTotal": setup_total,
            "onTime": on_time, "lateN": late_n, "imbalance": imbalance, "makespan": makespan,
            "overloadWC": len([l for l in load if l.get("judge") == "超载"])}


def aps_evaluate(seq, ctx, opts=None) -> dict:
    """按给定序列解码（schedule 序列分支）并计算指标；入参序深拷贝不改动。"""
    opts = opts or {}
    work = copy.deepcopy(seq)
    planned = schedule(work, {
        "base_date": opts.get("base_date"), "sequence": True,
        "sequenceOrder": [r["order"]["order_no"] for r in work],
        "setup": bool(opts.get("setup")), "setupDiff": nz(opts.get("setupDiff"), 0.5),
        "strategy": opts.get("strategy") or "priority",
    })
    return {"planned": planned, "metrics": aps_metrics(planned, ctx, opts)}


def objective(m, w) -> float:
    """加权目标：tardy×1 + setup×2 + imbal×1 + makespan×0.1（权重可由策略 objective 覆盖）。"""
    return (w["tardy"] * m["tardiness"] + w["setup"] * m["setupTotal"]
            + w["imbal"] * m["imbalance"] + w["makespan"] * m["makespan"])


def aps_optimize(passed, ctx, opts=None) -> dict:
    """邻域交换局部搜索：从 GT 启发式序出发，迭代随机交换，恶化也接受（轨迹式），记录全局最优。"""
    opts = opts or {}
    rng = opts.get("rng") or random
    w = dict(DEFAULT_WEIGHTS)
    w.update(opts.get("weights") or {})
    cur = aps_sequence_heuristic(passed)
    best = list(cur)
    best_eval = aps_evaluate(best, ctx, opts)
    best_obj = objective(best_eval["metrics"], w)
    iters = max(1, int(nz(opts.get("iterations"), 200)))
    improved = False
    for _ in range(iters):
        if len(cur) < 2:
            break
        i = int(rng.random() * len(cur))
        j = int(rng.random() * len(cur))
        if i == j:
            continue
        cand = list(cur)
        cand[i], cand[j] = cand[j], cand[i]
        ev = aps_evaluate(cand, ctx, opts)
        obj = objective(ev["metrics"], w)
        if obj < best_obj - 1e-9:
            best_obj = obj
            best = cand
            best_eval = ev
            improved = True
        cur = cand
    return {"seq": best, "eval": best_eval, "improved": improved, "objective": best_obj}


def aps_run(results, ctx, opts=None) -> dict:
    """编排：门控 → 策略/启发式/局部搜索定序 → 评估 → 周负荷/线瓶颈 → 基准对比 → 甘特。"""
    opts = opts or {}
    p = ctx["params"]
    base = opts.get("base_date") or to_str(date.today())
    o = {"base_date": base, "setup": opts.get("setup") is not False,
         "setupDiff": nz(opts.get("setupDiff"), 0.5), "setupSame": nz(opts.get("setupSame"), 0)}
    strat = strategy_mod.get_strategy(opts["strategy"], p) if opts.get("strategy") else None
    weights = strat["objective"] if strat else opts.get("weights")
    gate = aps_gate(results, ctx, opts)
    passed = gate["passed"]
    if opts.get("method") == "optimize" or opts.get("optimize") is True:
        opt = aps_optimize(passed, ctx, {"base_date": base, "weights": weights,
                                         "iterations": nz(opts.get("iterations"), 200),
                                         "strategy": opts.get("strategy"), "rng": opts.get("rng"),
                                         "setup": o["setup"], "setupDiff": o["setupDiff"]})
        seq, eval_res = opt["seq"], opt["eval"]
        used_method = "heuristic+local-search" + ("(已改进)" if opt["improved"] else "")
    else:
        seq = strat["orderFn"](passed, o) if strat else aps_sequence_heuristic(passed)
        eval_res = aps_evaluate(seq, ctx, {**o, "strategy": opts.get("strategy")})
        used_method = f"strategy({strat['name']})" if strat else "heuristic(GT)"
    load = weekly_load(eval_res["planned"], {"params": p})
    lb = line_bottleneck(eval_res["planned"], load)
    base_eval = aps_evaluate(list(passed), ctx, {"base_date": base, "setup": False})
    starts = [r["plan"]["start_date"] for r in eval_res["planned"]
              if not r.get("error") and (r.get("plan") or {}).get("start_date")]
    gantt_base = min(starts) if starts else base
    aps_gantt = gantt_chart(eval_res["planned"], {"base_date": gantt_base})
    return {
        "method": used_method,
        "strategy": ({"id": strat["id"], "name": strat["name"], "allocPolicy": strat["allocPolicy"],
                      "objective": strat["objective"], "desc": strat["desc"]}
                     if strat else {"id": "priority", "name": "订单优先级优先", "desc": "默认全序排产"}),
        "strategyMetrics": strategy_mod.strategy_metrics(eval_res["planned"], load),
        "gate": {
            "passed": [{"order_no": r["order"]["order_no"], "family": r["aps"]["family"],
                        "type": r["aps"]["type"]} for r in gate["passed"]],
            "blocked": gate["blocked"], "warned": gate["warned"],
            "counts": {"total": len(results), "passed": len(gate["passed"]),
                       "blocked": len(gate["blocked"]), "warned": len(gate["warned"])},
        },
        "sequence": [r["order"]["order_no"] for r in seq],
        "schedule": eval_res["planned"],
        "load": load, "lineBottleneck": lb, "metrics": eval_res["metrics"],
        "baseline": {"metrics": base_eval["metrics"], "delta": {
            "setupTotal": js_round((eval_res["metrics"]["setupTotal"] - base_eval["metrics"]["setupTotal"]) * 1000) / 1000,
            "tardiness": eval_res["metrics"]["tardiness"] - base_eval["metrics"]["tardiness"],
            "imbalance": js_round((eval_res["metrics"]["imbalance"] - base_eval["metrics"]["imbalance"]) * 1000) / 1000,
        }},
        "params": p,
        "gantt": aps_gantt,
    }
```

- [x] **Step 1.4: 运行确认通过**（预期：本文件 8 passed；全量 174 passed, 1 skipped）

```powershell
$env:PYTHONIOENCODING="utf-8"; & "F:\aps-hap\offline\runtime\python\python.exe" -m pytest tests/mps/test_mps_aps.py -q
$env:PYTHONIOENCODING="utf-8"; & "F:\aps-hap\offline\runtime\python\python.exe" -m pytest tests -q
```

- [x] **Step 1.5: 提交** `feat(mps): APS 门面移植（aps.js：门控/GT 启发式/局部搜索/编排）`

---

### Task 2: ga.py（DEAP 序列搜索核心）+ PARAM_DEFS 增补

**Files:**
- Create: `backend/app/mps/ga.py`
- Create: `backend/tests/mps/test_mps_ga.py`
- Modify: `backend/app/mps/consts.py`（PARAM_DEFS +3）
- Modify: `backend/app/mps/context.py`（`_NUMERIC_PARAM_KEYS` +3）
- Modify: `backend/tests/mps/test_consts.py`（快照 16→19）
- Modify: `backend/requirements.txt`（+`deap==1.4.4`）

- [x] **Step 2.1: 编写失败测试**

```python
"""GA 序列搜索（DEAP）：索引排列染色体/种子/复现性/随机隔离/参数优先级（设计 D11）。"""
import random

import pytest

from app.mps import strategy as strategy_mod
from app.mps.aps import aps_gate, aps_sequence_heuristic
from app.mps.ga import run_ga
from tests.mps.test_mps_aps import BASE, seq_fixture


def _passed_and_ctx():
    results, ctx = seq_fixture()
    return aps_gate(results, ctx, {"base_date": BASE})["passed"], ctx


def _opts(**over):
    o = {"base_date": BASE, "strategy": "priority", "weights": dict(strategy_mod.get_strategy("priority")["objective"]),
         "setup": True}
    o.update(over)
    return o


def test_run_ga_contract_pop8_gen3_seed42():
    passed, ctx = _passed_and_ctx()
    out = run_ga(passed, ctx, _opts(population=8, generations=3, seed=42))
    assert out["sequence"] == ["WO-4", "WO-2", "WO-5", "WO-3", "WO-1"]
    assert out["objective"] == pytest.approx(6.003333205390996)
    assert out["baseline_objective"] == pytest.approx(6.003333205390996)
    assert out["improved"] is False
    assert (out["seed"], out["population"], out["generations"]) == (42, 8, 3)
    assert sorted(out["genome"]) == [0, 1, 2, 3, 4]                     # 索引排列
    assert out["sequence"] == [passed[i]["order"]["order_no"] for i in out["genome"]]


def test_run_ga_reproducible_and_global_random_state_isolated():
    passed1, ctx1 = _passed_and_ctx()
    passed2, ctx2 = _passed_and_ctx()
    before = random.getstate()
    out1 = run_ga(passed1, ctx1, _opts(population=8, generations=3, seed=42))
    after = random.getstate()
    out2 = run_ga(passed2, ctx2, _opts(population=8, generations=3, seed=42))
    assert out1["sequence"] == out2["sequence"] == ["WO-4", "WO-2", "WO-5", "WO-3", "WO-1"]
    assert out1["objective"] == out2["objective"]
    assert before == after                                              # 不污染全局随机流


def test_run_ga_seed_zero_none_and_gen0_best_is_first_seed():
    passed, ctx = _passed_and_ctx()
    strat_seq = strategy_mod.order_by_priority(list(passed))
    gt_seq = aps_sequence_heuristic(passed)
    out = run_ga(passed, ctx, _opts(population=2, generations=0, seed=0,
                                    seeds=[strat_seq, gt_seq]))
    assert out["seed"] is None                                          # 0 → 不固定
    assert [r["order"]["order_no"] for r in strat_seq] == ["WO-3", "WO-2", "WO-5", "WO-4", "WO-1"]
    assert out["sequence"] == [r["order"]["order_no"] for r in strat_seq]  # 0 代 → 最优=第一个种子
    assert out["objective"] == pytest.approx(6.003333205390996)
    assert out["baseline_objective"] == pytest.approx(6.003333205390996)
    assert out["improved"] is False


def test_run_ga_defaults_floor_and_param_override():
    passed, ctx = _passed_and_ctx()
    out = run_ga(passed, ctx, _opts(population=1, generations=-5, seed=42))
    assert (out["population"], out["generations"]) == (2, 0)            # 下限守卫
    out2 = run_ga(passed, ctx, _opts())                                 # 无覆盖 → 默认 30/20/42
    assert (out2["population"], out2["generations"], out2["seed"]) == (30, 20, 42)
    ctx3 = _passed_and_ctx()[1]
    ctx3["params"] = {**ctx3["params"], "ga_population": 4, "ga_generations": 1, "ga_seed": 7}
    out3 = run_ga(passed, ctx3, _opts())
    assert (out3["population"], out3["generations"], out3["seed"]) == (4, 1, 7)


def test_run_ga_without_seeds_baseline_is_input_order():
    passed, ctx = _passed_and_ctx()
    out = run_ga(passed, ctx, _opts(population=2, generations=0, seed=42))
    assert out["baseline_objective"] == pytest.approx(6.003333205390996)  # 输入序（优先序）目标；GT 序另见种子用例
    assert sorted(out["genome"]) == [0, 1, 2, 3, 4]
```

同时修改 `backend/tests/mps/test_consts.py`：

```python
def test_param_defs_unique_and_defaults():
    keys = [p["key"] for p in PARAM_DEFS]
    assert len(keys) == len(set(keys))
    defs = {p["key"]: p for p in PARAM_DEFS}
    assert defs["week_days"]["value"] == "6"
    assert defs["peak_factor"]["value"] == "1.1"
    assert defs["order_buffer_days"]["value"] == "1"
    assert defs["reference_batch"]["value"] == "1000"
    assert defs["round_mode"]["value"] == "ceil"
    assert defs["ramp_trigger"]["value"] == "first_flag"
    assert defs["wb_auto_flux_override"]["value"] == "0"
    assert defs["ga_population"]["value"] == "30"
    assert defs["ga_generations"]["value"] == "20"
    assert defs["ga_seed"]["value"] == "42"


def test_param_defs_key_snapshot():
    assert {p["key"] for p in PARAM_DEFS} == {
        "week_days", "peak_factor", "use_peak", "exclude_braze_yield", "wb_auto_flux_override",
        "cf_db_1", "cf_db_2", "cf_db_3", "cf_wb_1", "cf_wb_2", "cf_wb_3",
        "vapor_cap_cut", "order_buffer_days", "reference_batch", "round_mode", "ramp_trigger",
        "ga_population", "ga_generations", "ga_seed",
    }
```

- [x] **Step 2.2: 运行确认失败**

```powershell
$env:PYTHONIOENCODING="utf-8"; & "F:\aps-hap\offline\runtime\python\python.exe" -m pytest tests/mps/test_mps_ga.py tests/mps/test_consts.py -q
```
预期：ga 文件 collection error（无 `app.mps.ga`）；test_consts 两个快照/默认值断言失败（16≠19、缺 ga_*）。

- [x] **Step 2.3: 实现**

1) `backend/requirements.txt` 末行追加：

```
deap==1.4.4
```

2) `backend/app/mps/consts.py` PARAM_DEFS 追加（置于 `ramp_trigger` 之后，组名"求解"；文件头注释同步改"后 8 项"）：

```python
    {"key": "ga_population", "value": "30", "label": "GA 种群规模", "group": "求解", "hint": "候选解数量下限 2；0 代次仅评估种子"},
    {"key": "ga_generations", "value": "20", "label": "GA 迭代代数", "group": "求解", "hint": "世代数；0=仅评估初始种群（含种子）"},
    {"key": "ga_seed", "value": "42", "label": "GA 随机种子", "group": "求解", "hint": "固定随机流复现结果；0=不固定（每次随机）"},
```

3) `backend/app/mps/context.py` `_NUMERIC_PARAM_KEYS` 追加三个键：

```python
_NUMERIC_PARAM_KEYS = (
    "week_days", "peak_factor", "exclude_braze_yield",
    "cf_db_1", "cf_db_2", "cf_db_3", "cf_wb_1", "cf_wb_2", "cf_wb_3",
    "vapor_cap_cut", "order_buffer_days", "reference_batch", "wb_auto_flux_override",
    "ga_population", "ga_generations", "ga_seed",
)
```

4) 创建 `backend/app/mps/ga.py`：

```python
"""GA 序列搜索核心（DEAP；设计 D11 默认求解器；新实现，无 JS 对照）。

染色体 = 待排序列的**索引排列**（`list(range(n))` 的重排，索引映射回 passed 列表）：
DEAP `tools.cxOrdered` 要求整数基因，不能直接用结果 dict 作基因（探针实证）。

- 适应度 = aps.objective(aps_metrics(decode(genome)))，最小化；
- 种群首部注入种子序列（策略序/GT 序，按 order_no 映射为索引）；无种子时真值基准取输入序；
- 随机流隔离：`random.seed(seed)` 前保存 `random.getstate()`、结束 `setstate` 恢复；
- 参数优先级：opts > `ctx["params"]`（ga_population/ga_generations/ga_seed）> 常量默认（30/20/42）；
- creator 全局单例守卫（重复导入/多测试复用不报错）；`tools.HallOfFame(1)` 内部 deepcopy 保管最优。
"""
import copy
import random

from deap import algorithms, base, creator, tools

from app.mps.aps import aps_metrics, objective
from app.mps.kernel import nz
from app.mps.schedule import schedule_process_constrained


def _ensure_creator():
    if not hasattr(creator, "MPSFitnessMin"):
        creator.create("MPSFitnessMin", base.Fitness, weights=(-1.0,))
    if not hasattr(creator, "MPSIndividual"):
        creator.create("MPSIndividual", list, fitness=creator.MPSFitnessMin)


def run_ga(passed, ctx, opts=None) -> dict:
    """DEAP 序列搜索：返回 {genome, sequence, objective, baseline_objective, improved, seed, population, generations}。"""
    opts = opts or {}
    p = ctx["params"]
    base_date = opts.get("base_date")
    population = max(2, int(nz(opts.get("population"), nz(p.get("ga_population"), 30))))
    generations = max(0, int(nz(opts.get("generations"), nz(p.get("ga_generations"), 20))))
    seed_raw = int(nz(opts.get("seed"), nz(p.get("ga_seed"), 42)))
    seed = seed_raw if seed_raw > 0 else None
    weights = dict(opts["weights"])
    decode_opts = {"strategy": opts.get("strategy"), "P": p,
                   "setup": opts.get("setup") is not False,
                   "setupDiff": nz(opts.get("setupDiff"), 0.5)}

    def decode(genome):
        work = [copy.deepcopy(passed[i]) for i in genome]
        return schedule_process_constrained(work, base_date, {
            **decode_opts,
            "sequenceOrder": [r["order"]["order_no"] for r in work], "sequence": True})

    def evaluate(genome):
        out = decode(genome)
        m = aps_metrics(out["planned"], ctx, {"base_date": base_date})
        return (objective(m, weights),)

    _ensure_creator()
    toolbox = base.Toolbox()
    toolbox.register("evaluate", evaluate)
    toolbox.register("select", tools.selTournament, tournsize=3)
    toolbox.register("mate", tools.cxOrdered)
    toolbox.register("mutate", tools.mutShuffleIndexes, indpb=0.2)

    idx = {r["order"]["order_no"]: i for i, r in enumerate(passed)}
    n = len(passed)
    state = random.getstate()
    if seed is not None:
        random.seed(seed)
    try:
        seeds = [[idx[r["order"]["order_no"]] for r in s]
                 for s in (opts.get("seeds") or []) if s]
        baseline = list(seeds[0]) if seeds else list(range(n))
        pop_list = [list(s) for s in seeds]
        while len(pop_list) < population:
            g = list(range(n))
            random.shuffle(g)
            pop_list.append(g)
        pop_list = pop_list[:population]
        pop = [creator.MPSIndividual(g) for g in pop_list]
        hof = tools.HallOfFame(1)
        algorithms.eaSimple(pop, toolbox, cxpb=0.5, mutpb=0.2, ngen=generations,
                            halloffame=hof, verbose=False)
        best = list(hof[0])
        best_obj = hof[0].fitness.values[0]
        baseline_obj = evaluate(baseline)[0]
    finally:
        random.setstate(state)
    return {"genome": best, "sequence": [passed[i]["order"]["order_no"] for i in best],
            "objective": best_obj, "baseline_objective": baseline_obj,
            "improved": best_obj < baseline_obj - 1e-9,
            "seed": seed, "population": population, "generations": generations}
```

- [x] **Step 2.4: 运行确认通过**（预期：本文件 5 passed；test_consts 6 passed；全量 179 passed, 1 skipped）

- [x] **Step 2.5: 提交** `feat(mps): GA 序列搜索核心（DEAP）与 ga_* 参数`

---

### Task 3: solver.py（模式门面）+ week_days 透传修复

**Files:**
- Create: `backend/app/mps/solver.py`
- Create: `backend/tests/mps/test_mps_solver.py`
- Modify: `backend/app/mps/strategy.py`（order_by_priority 透传）
- Modify: `backend/app/mps/schedule.py`（order_opts 注入）
- Modify: `backend/app/mps/aps.py`（aps_run 注入 week_days，一致性）
- Modify: `backend/tests/mps/test_mps_strategy.py`（+1 测试）
- Modify: `backend/tests/mps/test_mps_schedule.py`（test_order_opts_defaults 扩断言）

- [x] **Step 3.1: 编写失败测试**

新建 `backend/tests/mps/test_mps_solver.py`：

```python
"""求解门面（solver）：模式契约/确定性等价（CHK-SCHED-009）/复现/异常文案。"""
import pytest

from app.mps.schedule import schedule_process_constrained
from app.mps.solver import MODES, solve
from tests.mps.test_mps_aps import BASE, gate_fixture, seq_fixture


def _summary(planned):
    return [(r["order"]["order_no"], r["plan"]["start_date"], r["plan"]["finish_date"],
             r["plan"]["gap_days"]) for r in planned]


def test_chk_sched_008_ga_mode_contract():
    results, ctx = seq_fixture()
    out = solve(results, ctx, {"base_date": BASE, "population": 8, "generations": 3})
    assert out["method"] == "ga(DEAP 序列搜索)"
    assert out["solver"] == {"mode": "ga", "seed": 42, "population": 8, "generations": 3,
                             "improved": False,
                             "baseline_objective": pytest.approx(6.003333205390996),
                             "objective": pytest.approx(6.003333205390996)}
    assert out["sequence"] == ["WO-3", "WO-2", "WO-5", "WO-4", "WO-1"]
    assert sorted(out["sequence"]) == ["WO-1", "WO-2", "WO-3", "WO-4", "WO-5"]
    assert out["strategy"]["id"] == "priority"
    assert set(out["strategy"]) == {"id", "name", "allocPolicy", "objective", "desc"}
    assert out["gate"]["counts"] == {"total": 5, "passed": 5, "blocked": 0, "warned": 0}
    assert set(out["decode"]) == {"ledger", "fluxOf", "capViolations"}
    assert out["decode"]["capViolations"] == []
    assert len(out["decode"]["ledger"]) == 5
    assert out["warnings"] == []
    assert out["solver"]["objective"] <= out["solver"]["baseline_objective"] + 1e-9


def test_chk_sched_009_deterministic_equals_direct_call():
    results_a, ctx_a = seq_fixture()
    out = solve(results_a, ctx_a, {"base_date": BASE, "mode": "deterministic", "strategy": "priority"})
    results_b, ctx_b = seq_fixture()
    direct = schedule_process_constrained(results_b, BASE, {"strategy": "priority", "P": ctx_b["params"]})
    assert _summary(out["schedule"]) == _summary(direct["planned"])
    assert _summary(out["schedule"]) == [
        ("WO-3", "2026-06-01", "2026-06-02", -4),
        ("WO-2", "2026-06-01", "2026-06-05", 87),
        ("WO-5", "2026-06-04", "2026-06-06", 115),
        ("WO-4", "2026-06-06", "2026-06-08", 52),
        ("WO-1", "2026-06-01", "2026-06-02", 27),
    ]
    assert out["method"] == "deterministic(策略正排:订单优先级优先)"
    assert out["solver"]["mode"] == "deterministic"
    assert out["solver"]["seed"] is None and out["solver"]["population"] is None
    assert out["solver"]["objective"] == pytest.approx(5.003333205390996)
    assert out["solver"]["baseline_objective"] == pytest.approx(5.003333205390996)
    assert out["metrics"]["setupTotal"] == 0.0        # deterministic 不传 setup → 解码默认关
    assert out["warnings"] == [] and out["decode"]["capViolations"] == []


def test_solve_ga_reproducible_seed():
    results1, ctx1 = seq_fixture()
    out1 = solve(results1, ctx1, {"base_date": BASE, "population": 8, "generations": 3})
    results2, ctx2 = seq_fixture()
    out2 = solve(results2, ctx2, {"base_date": BASE, "population": 8, "generations": 3})
    assert out1["sequence"] == out2["sequence"] == ["WO-3", "WO-2", "WO-5", "WO-4", "WO-1"]
    assert out1["solver"]["objective"] == out2["solver"]["objective"]


def test_solve_heuristic_mode_reproducible():
    results, ctx = seq_fixture()
    out = solve(results, ctx, {"base_date": BASE, "mode": "heuristic", "iterations": 50, "seed": 42})
    assert out["method"] == "heuristic+local-search"
    assert out["sequence"] == ["WO-2", "WO-5", "WO-4", "WO-3", "WO-1"]
    assert out["solver"] == {"mode": "heuristic", "seed": 42, "population": None, "generations": None,
                             "improved": False,
                             "baseline_objective": pytest.approx(6.003333205390996),
                             "objective": pytest.approx(6.003333205390996)}
    results2, ctx2 = seq_fixture()
    out2 = solve(results2, ctx2, {"base_date": BASE, "mode": "heuristic", "iterations": 50, "seed": 42})
    assert out["sequence"] == out2["sequence"]
    assert out["solver"]["objective"] == out2["solver"]["objective"]


def test_solve_mode_exceptions():
    assert MODES == ("ga", "deterministic", "heuristic", "cp_sat")
    ctx = seq_fixture()[1]
    with pytest.raises(NotImplementedError) as ei:
        solve([], ctx, {"mode": "cp_sat"})
    assert str(ei.value) == "CP-SAT 延后（设计 D11，非验收基准）"
    with pytest.raises(ValueError) as ei2:
        solve([], ctx, {"mode": "nope"})
    assert str(ei2.value) == "未知求解模式：nope"
    results, ctx2 = gate_fixture()
    lone = [r for r in results if not r.get("error") and r["order"]["order_no"] == "E"]
    lone[0]["order"]["kit_date"] = ""
    with pytest.raises(ValueError) as ei3:
        solve(lone, ctx2, {"base_date": BASE, "gate_mode": "block"})
    assert str(ei3.value) == "无待排工单（gate 通过列表为空）"
```

`test_mps_strategy.py` 追加（文件末尾）：

```python
def test_order_by_priority_week_days_tiebreak():
    """week_days 透传：瓶颈负荷率档位相同时按编号兜底（3B2 修复，探针实证）。"""
    from app.mps.strategy import order_by_priority

    a = _r("A", due="2026-07-01")            # 同优先级/同交期/同交期天数，仅瓶颈负荷不同
    a["input_qty"] = 500
    a["bottleneck"] = {"throughput": 100}
    b = _r("B", due="2026-07-01")
    b["input_qty"] = 1000
    b["bottleneck"] = {"throughput": 100}
    # week_days=6：B(⌈1000/100⌉/6=1.0) 先于 A(5/6≈0.833)
    assert [x["order"]["order_no"] for x in order_by_priority([a, b], {"week_days": 6})] == ["B", "A"]
    # week_days=3：两者均 clamp 至 1.0 → 退到编号兜底 A 先
    assert [x["order"]["order_no"] for x in order_by_priority([a, b], {"week_days": 3})] == ["A", "B"]
    # 缺省等价 6（与 3A 口径一致）
    assert [x["order"]["order_no"] for x in order_by_priority([a, b])] == ["B", "A"]
```

`test_mps_schedule.py` 修改 `test_order_opts_defaults`：

```python
def test_order_opts_defaults():
    o = order_opts({"P": {"setup_days": 1.5, "due_buffer_days": 3, "week_days": 5}})
    assert o["setupDiff"] == 1.5 and o["due_buffer_days"] == 3 and o["week_days"] == 5
    o2 = order_opts()
    assert o2["setupDiff"] == 0.5 and o2["due_buffer_days"] == 0 and o2["week_days"] == 6
```

- [x] **Step 3.2: 运行确认失败**

```powershell
$env:PYTHONIOENCODING="utf-8"; & "F:\aps-hap\offline\runtime\python\python.exe" -m pytest tests/mps/test_mps_solver.py tests/mps/test_mps_strategy.py tests/mps/test_mps_schedule.py -q
```
预期：solver 文件 collection error（无 `app.mps.solver`）；strategy 新测试失败（`week_days=3` 断言不成立）；schedule `test_order_opts_defaults` 失败（无 `week_days` 键）。

- [x] **Step 3.3: 实现**

1) `backend/app/mps/strategy.py`：

```python
def order_by_priority(results, opts=None) -> list:
    """订单优先级优先（默认）：全序 comparator（置顶→优先级→交期→…）。

    week_days 透传（3B2 修复）：影响第 7 级瓶颈负荷率档位；缺省回 6（3A 口径）。
    """
    return prio.sort_results(results, week_days=prio._num((opts or {}).get("week_days"), 6))
```

2) `backend/app/mps/schedule.py` `order_opts`：

```python
def order_opts(opts=None) -> dict:
    """构造传给 orderFn 的排序选项（注入可调参数：换线天数/交期缓冲/周工作天数）。"""
    o = dict(opts or {})
    p = o.get("P") or {}
    if o.get("setupDiff") is None:
        o["setupDiff"] = nz(p.get("setup_days"), 0.5)
    o["due_buffer_days"] = nz(p.get("due_buffer_days"), 0)
    o["week_days"] = nz(p.get("week_days"), 6)
    return o
```

3) `backend/app/mps/aps.py` `aps_run` 的 `o` 注入（与 order_opts 同口径，3B2 传递项②）：

```python
    o = {"base_date": base, "setup": opts.get("setup") is not False,
         "setupDiff": nz(opts.get("setupDiff"), 0.5), "setupSame": nz(opts.get("setupSame"), 0),
         "week_days": nz(p.get("week_days"), 6)}
```

4) 创建 `backend/app/mps/solver.py`：

```python
"""求解门面：ga（默认，设计 D11）/ deterministic（确定性基准，验收对照）/ heuristic（局部搜索）/
cp_sat（延后留痕）四模式；统一 apsRun 形状 + solver 元信息 + decode 出口，供服务/前端消费。

- deterministic：仅传 strategy/P（+显式 setup/setupDiff 透传），与直接调用
  `schedule_process_constrained(results, base, {"strategy": sid, "P": p})` 逐条等价（CHK-SCHED-009）；
- ga：策略序与 GT 序作种子，run_ga 搜索后以最终序列解码；objective ≤ baseline_objective 恒成立；
- heuristic：aps_optimize 局部搜索（可注入 rng 复现）；cp_sat 抛 NotImplementedError（D11 决策）。
"""
import copy
import random
from datetime import date

from app.mps import aps
from app.mps import strategy as strategy_mod
from app.mps.dates import to_str
from app.mps.ga import run_ga
from app.mps.kernel import nz
from app.mps.load import line_bottleneck, weekly_load
from app.mps.schedule import gantt_chart, schedule_process_constrained

MODES = ("ga", "deterministic", "heuristic", "cp_sat")


def _decode_seq(seq, base, seq_opts, setup) -> dict:
    """按最终序列解码（深拷贝，逐条等价于直接调用）。"""
    work = copy.deepcopy(list(seq))
    return schedule_process_constrained(work, base, {
        **seq_opts, "setup": setup,
        "sequenceOrder": [r["order"]["order_no"] for r in work], "sequence": True})


def solve(results, ctx, opts=None) -> dict:
    """按模式求解：返回 apsRun 形状 + solver 元信息 + decode{ledger,fluxOf,capViolations} + warnings。"""
    opts = opts or {}
    mode = opts.get("mode") or "ga"
    if mode not in MODES:
        raise ValueError(f"未知求解模式：{mode}")
    if mode == "cp_sat":
        raise NotImplementedError("CP-SAT 延后（设计 D11，非验收基准）")
    p = ctx["params"]
    base = opts.get("base_date") or to_str(date.today())
    strat = strategy_mod.get_strategy(opts.get("strategy") or "priority", p)
    weights = dict(strat["objective"])
    if opts.get("weights"):
        weights.update(opts["weights"])
    gate = aps.aps_gate(results, ctx, opts)
    passed = gate["passed"]
    if not passed:
        raise ValueError("无待排工单（gate 通过列表为空）")

    eval_setup = opts.get("setup") is not False
    seq_opts = {"strategy": strat["id"], "P": p, "setupDiff": nz(opts.get("setupDiff"), 0.5)}

    if mode == "deterministic":
        det_opts = {"strategy": strat["id"], "P": p}
        if "setup" in opts:
            det_opts["setup"] = opts["setup"]
        if "setupDiff" in opts:
            det_opts["setupDiff"] = opts["setupDiff"]
        decode_out = schedule_process_constrained(passed, base, det_opts)
        planned = decode_out["planned"]
        method = f"deterministic(策略正排:{strat['name']})"
        solver_info = {"mode": "deterministic", "seed": None, "population": None,
                       "generations": None, "improved": False}
    elif mode == "ga":
        strat_seq = strat["orderFn"](list(passed), {"base_date": base,
                                                    "week_days": nz(p.get("week_days"), 6),
                                                    "setupDiff": seq_opts["setupDiff"]})
        gt_seq = aps.aps_sequence_heuristic(passed)
        ga_out = run_ga(passed, ctx, {
            "base_date": base, "strategy": strat["id"], "weights": weights,
            "seeds": [strat_seq, gt_seq], "setup": eval_setup,
            "setupDiff": seq_opts["setupDiff"],
            "population": opts.get("population"), "generations": opts.get("generations"),
            "seed": opts.get("seed")})
        decode_out = _decode_seq([passed[i] for i in ga_out["genome"]], base, seq_opts, eval_setup)
        planned = decode_out["planned"]
        method = "ga(DEAP 序列搜索)"
        solver_info = {"mode": "ga", "seed": ga_out["seed"], "population": ga_out["population"],
                       "generations": ga_out["generations"], "improved": ga_out["improved"],
                       "baseline_objective": ga_out["baseline_objective"]}
    else:
        seed_raw = int(nz(opts.get("seed"), nz(p.get("ga_seed"), 42)))
        seed = seed_raw if seed_raw > 0 else None
        rng = opts.get("rng") or (random.Random(seed) if seed is not None else None)
        gt_seq = aps.aps_sequence_heuristic(passed)
        base_eval_gt = aps.aps_evaluate(gt_seq, ctx, {"base_date": base, "setup": eval_setup,
                                                      "strategy": strat["id"],
                                                      "setupDiff": seq_opts["setupDiff"]})
        base_obj = aps.objective(base_eval_gt["metrics"], weights)
        opt = aps.aps_optimize(passed, ctx, {
            "base_date": base, "setup": eval_setup, "setupDiff": seq_opts["setupDiff"],
            "strategy": strat["id"], "weights": weights,
            "iterations": nz(opts.get("iterations"), 200), "rng": rng})
        decode_out = _decode_seq(opt["seq"], base, seq_opts, eval_setup)
        planned = decode_out["planned"]
        method = "heuristic+local-search" + ("(已改进)" if opt["improved"] else "")
        solver_info = {"mode": "heuristic", "seed": seed, "population": None, "generations": None,
                       "improved": opt["improved"], "baseline_objective": base_obj}

    metrics = aps.aps_metrics(planned, ctx, {"base_date": base})
    solver_info["objective"] = aps.objective(metrics, weights)
    if solver_info.get("baseline_objective") is None:
        solver_info["baseline_objective"] = solver_info["objective"]

    load = weekly_load(planned, {"params": p})
    lb = line_bottleneck(planned, load)
    base_eval = aps.aps_evaluate(list(gate["passed"]), ctx, {"base_date": base, "setup": False})
    starts = [r["plan"]["start_date"] for r in planned
              if not r.get("error") and (r.get("plan") or {}).get("start_date")]
    gantt_base = min(starts) if starts else base
    return {
        "method": method,
        "solver": solver_info,
        "strategy": {"id": strat["id"], "name": strat["name"], "allocPolicy": strat["allocPolicy"],
                     "objective": strat["objective"], "desc": strat["desc"]},
        "strategyMetrics": strategy_mod.strategy_metrics(planned, load),
        "gate": {
            "passed": [{"order_no": r["order"]["order_no"], "family": r["aps"]["family"],
                        "type": r["aps"]["type"]} for r in gate["passed"]],
            "blocked": gate["blocked"], "warned": gate["warned"],
            "counts": {"total": len(results), "passed": len(gate["passed"]),
                       "blocked": len(gate["blocked"]), "warned": len(gate["warned"])},
        },
        "sequence": [r["order"]["order_no"] for r in planned],
        "schedule": planned,
        "load": load, "lineBottleneck": lb, "metrics": metrics,
        "baseline": {"metrics": base_eval["metrics"], "delta": {
            "setupTotal": (metrics["setupTotal"] - base_eval["metrics"]["setupTotal"]),
            "tardiness": metrics["tardiness"] - base_eval["metrics"]["tardiness"],
            "imbalance": (metrics["imbalance"] - base_eval["metrics"]["imbalance"]),
        }},
        "params": p,
        "gantt": gantt_chart(planned, {"base_date": gantt_base}),
        "decode": {"ledger": decode_out["ledger"], "fluxOf": decode_out["fluxOf"],
                   "capViolations": decode_out["capViolations"]},
        "warnings": decode_out["warnings"],
    }
```

- [x] **Step 3.4: 运行确认通过**（预期：solver 5 passed、strategy 9 passed、schedule 14 passed；全量 185 passed, 1 skipped）

- [x] **Step 3.5: 提交** `feat(mps): 求解门面（ga/deterministic/heuristic）与 week_days 透传修复`

---

### Task 4: schedule_service.py（排产落库）+ operations 依赖重挂修复

**Files:**
- Create: `backend/app/mps/schedule_service.py`
- Create: `backend/tests/mps/test_mps_schedule_service.py`
- Modify: `backend/app/mps/operations.py`（`sync_order_operations` 手工行 depends 重挂）
- Modify: `backend/tests/mps/test_mps_operations.py`（+1 测试）

- [x] **Step 4.1: 编写失败测试**

新建 `backend/tests/mps/test_mps_schedule_service.py`（断言值全部来自探针实跑）：

```python
"""排产服务：批次/每日分配落库与订单回写（CHK-SCHED-010）。"""
from datetime import date

import pytest
from sqlalchemy import func, select

from app.models.mps import Order, ScheduleAllocation, ScheduleBatch
from app.mps.context import load_ctx
from app.mps.kernel import calc_order
from app.mps.operations import add_manual_operation, sync_order_operations
from app.mps.schedule_service import order_to_dict, run_schedule
from app.seed.loader import load_mps_seed


def _mk_order(no, qty, prio=100, due=None):
    return Order(order_no=no, product="P-" + no, code="M02-2D", order_type="常规", first_flag="否",
                 water_vapor="有", qty=qty, due_date=due, kit_date=date(2026, 6, 1), priority=prio,
                 features={"N_die": 60, "N_wire": 60})


async def _seed_orders(session):
    await load_mps_seed(session)
    a = _mk_order("WO-A", 1000, 100, date(2026, 9, 30))
    b = _mk_order("WO-B", 5, 50)
    session.add_all([a, b])
    await session.commit()
    ctx = await load_ctx(session)
    for o in (a, b):                                    # 预同步工序需求 → 分配行可关联 operation_id
        await sync_order_operations(session, o.id, calc_order(order_to_dict(o), ctx))
    return a, b


async def test_chk_sched_010_batch_result_persistence(sqlite_session):
    a, b = await _seed_orders(sqlite_session)
    r1 = await run_schedule(sqlite_session, "2026-06-01",
                            {"mode": "deterministic", "strategy": "priority"})
    assert r1["batch_no"] == "SCH-20260601-001"
    assert r1["solver_mode"] == "deterministic" and r1["strategy_id"] == "priority"
    assert r1["order_count"] == 2 and r1["allocation_rows"] == 32 and r1["warnings"] == []
    assert r1["kpi"] == {"tardiness": 0, "maxLate": 0, "setupTotal": 0.0, "onTime": 1, "lateN": 0,
                         "imbalance": pytest.approx(0.5653581678004794), "makespan": 26, "overloadWC": 1}

    batch = (await sqlite_session.execute(select(ScheduleBatch))).scalar_one()
    assert batch.batch_no == "SCH-20260601-001" and batch.base_date == date(2026, 6, 1)
    assert batch.solver_mode == "deterministic" and batch.strategy_id == "priority"
    assert batch.params_snapshot["week_days"] == 6.0 and batch.status == "完成"
    assert batch.kpi["makespan"] == 26

    total = (await sqlite_session.execute(select(func.count()).select_from(ScheduleAllocation))).scalar()
    assert total == 32
    a_rows = (await sqlite_session.execute(
        select(ScheduleAllocation).where(ScheduleAllocation.order_id == a.id))).scalars().all()
    assert len(a_rows) == 27 and all(x.operation_id is not None for x in a_rows)
    sums = {}
    for x in a_rows:
        sums[x.resource_key] = sums.get(x.resource_key, 0.0) + x.qty
    assert sums["模块级|DB|自动DB"] == pytest.approx(1052 * 60)
    assert sums["模块级|WB|自动WB"] == pytest.approx(1052 * 60)
    assert sums["模块级|调试|/"] == pytest.approx(1052)
    assert sums["模块级|终检|/"] == pytest.approx(1052)
    assert sums["模块级|封盖|/"] == pytest.approx(1052)
    db_day1 = [x for x in a_rows if x.resource_key == "模块级|DB|自动DB"
               and x.work_date == date(2026, 6, 1)]
    assert len(db_day1) == 1 and db_day1[0].qty == pytest.approx(63120 / 11)

    await sqlite_session.refresh(a)
    await sqlite_session.refresh(b)
    assert a.input_qty == 1052 and a.yield_ratio == pytest.approx(1.0518332845401022)
    assert a.y_full == pytest.approx(0.9507210074999999)
    assert a.cycle_single == 6.0 and a.cycle_batch == 16.0
    assert a.adopted_flux == 100.0 and a.bottleneck_op == "DB" and a.ramp_applied == 0
    assert a.delivery_cycle == 17.0 and a.latest_start_date == date(2026, 9, 13)
    assert a.plan_start_date == date(2026, 6, 1) and a.plan_finish_date == date(2026, 6, 27)
    assert a.gap_days == 104 and a.judge == "满足" and a.strategy_id == "priority"
    assert b.input_qty == 6 and b.latest_start_date is None
    assert b.plan_start_date == date(2026, 6, 1) and b.plan_finish_date == date(2026, 6, 5)
    assert b.gap_days is None and b.judge == "无交期"

    r2 = await run_schedule(sqlite_session, "2026-06-01",
                            {"population": 4, "generations": 1, "seed": 42})
    assert r2["batch_no"] == "SCH-20260601-002" and r2["solver_mode"] == "ga"
    assert r2["allocation_rows"] == 32
    n = (await sqlite_session.execute(select(func.count()).select_from(ScheduleBatch))).scalar()
    assert n == 2


async def test_run_schedule_manual_operation_participates(sqlite_session):
    """D12：手工追加工序经服务端并入排产，分配行关联到手工工序行（探针实测）。"""
    a, b = await _seed_orders(sqlite_session)
    manual = await add_manual_operation(sqlite_session, a.id, level="模块级", op="调试", mode=None,
                                        qty=1052, usage=1, after_seq=5, note="返工调试")
    r = await run_schedule(sqlite_session, "2026-06-01", {"mode": "deterministic"})
    assert r["allocation_rows"] == 37                        # 32 自动 + 5（手工条 1052/250=5 天）
    a_rows = (await sqlite_session.execute(
        select(ScheduleAllocation).where(ScheduleAllocation.order_id == a.id))).scalars().all()
    m_rows = sorted([x for x in a_rows if x.operation_id == manual.id], key=lambda x: x.work_date)
    assert len(m_rows) == 5
    assert m_rows[0].work_date == date(2026, 6, 28) and m_rows[0].resource_key == "模块级|调试|/"
    assert all(x.qty == pytest.approx(1052 / 5) for x in m_rows)
    sums = {}
    for x in a_rows:
        sums[x.resource_key] = sums.get(x.resource_key, 0.0) + x.qty
    assert sums["模块级|调试|/"] == pytest.approx(2104)       # 自动 1052 + 手工 1052


async def test_run_schedule_requires_orders(sqlite_session):
    await load_mps_seed(sqlite_session)
    with pytest.raises(ValueError) as ei:
        await run_schedule(sqlite_session, "2026-06-01", {"mode": "deterministic"})
    assert str(ei.value) == "无待排工单（orders.status='正常' 为空）"
```

`test_mps_operations.py` 追加：

```python
async def test_sync_rehang_manual_dependency(sqlite_session):
    """重同步后手工行依赖重挂到新自动行（3B2 修复；修复前指向已删除旧行=悬挂，探针实证）。"""
    r, _ = _calc_pair()
    o = Order(order_no="O-3", product="P", code="M02-2D", qty=100, features={"N_die": 60, "N_wire": 60})
    sqlite_session.add(o)
    await sqlite_session.commit()
    await sync_order_operations(sqlite_session, o.id, r)
    await add_manual_operation(sqlite_session, o.id, level="模块级", op="调试", mode=None,
                               qty=1052, usage=1, after_seq=2, note="返工调试")
    rows1 = (await sqlite_session.execute(
        select(OrderOperation).order_by(OrderOperation.seq))).scalars().all()
    manual1 = rows1[-1]
    assert manual1.seq == 3 and manual1.source == "manual"
    assert manual1.depends_on_id == rows1[1].id            # 挂在 seq=2 自动行之后
    old_seq2_id = rows1[1].id
    await sync_order_operations(sqlite_session, o.id, r)   # 重同步：auto 删除重建
    rows2 = (await sqlite_session.execute(
        select(OrderOperation).order_by(OrderOperation.seq))).scalars().all()
    manual2 = rows2[-1]
    assert manual2.source == "manual" and manual2.seq == 3
    assert manual2.depends_on_id == rows2[1].id            # 重挂到新 seq=2 自动行
    assert manual2.depends_on_id != old_seq2_id
```

- [x] **Step 4.2: 运行确认失败**

```powershell
$env:PYTHONIOENCODING="utf-8"; & "F:\aps-hap\offline\runtime\python\python.exe" -m pytest tests/mps/test_mps_schedule_service.py tests/mps/test_mps_operations.py -q
```
预期：service 文件 collection error（无 `app.mps.schedule_service`）；operations 新测试失败（`manual2.depends_on_id == rows2[1].id` 不成立——仍指向旧行）。

- [x] **Step 4.3: 实现**

1) `backend/app/mps/operations.py` `sync_order_operations` 修复（重建前快照手工行目标 seq，重建后重挂；目标不存在→置 None）：

```python
async def sync_order_operations(session: AsyncSession, order_id: str, calc_result) -> int:
    """重建该单自动工序需求（manual 行保留），返回插入行数。

    3B2 修复：重建前快照 manual 行 depends_on_id 指向旧行的 seq，重建后按 seq 映射到新自动行 id；
    旧目标不存在（路线变更等）→ 置 None（避免悬挂）。罕见的手工→手工依赖会清空（按需再挂）。
    """
    if calc_result.get("error") or "steps" not in calc_result:
        raise ValueError("calc_result 无效（含 error 或缺少 steps），拒绝重建工序需求")
    old_rows = (await session.execute(
        select(OrderOperation.id, OrderOperation.seq)
        .where(OrderOperation.order_id == order_id))).all()
    seq_by_id = {r.id: r.seq for r in old_rows}
    manuals = (await session.execute(
        select(OrderOperation).where(OrderOperation.order_id == order_id,
                                     OrderOperation.source == "manual"))).scalars().all()
    manual_target_seq = {m.id: seq_by_id.get(m.depends_on_id) for m in manuals if m.depends_on_id}
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
    for m in manuals:
        tgt = manual_target_seq.get(m.id)
        if tgt is not None:
            m.depends_on_id = by_seq.get(tgt)
    await session.commit()
    return len(rows)
```

2) 创建 `backend/app/mps/schedule_service.py`：

```python
"""排产服务：载单 → 手工条并入 → 求解 → 批次/每日分配落库 → 订单回写（CHK-SCHED-010；唯一碰 DB 的排产模块）。

- 单事务提交：ScheduleBatch + ScheduleAllocation×N + orders 回写一并 commit；
- batch_no 规则 `SCH-{YYYYMMDD}-{序号:03d}`（序号=同前缀最大+1，天然单调）；
- D12：该单 manual 工序行（depends_on_id → 前道 seq）经 merge_manual_bars 并入甘特参与排产；
  分配行按 manual 行顺序（seq 升序）与手工条一一关联 operation_id；
- 分配行：每条 step 条（不含 setup 条）按日拆分：busy_days 逐日一条，
  qty=amt/busy_days（amt=op_work 工作量）；自动条 operation_id 按 (order_id, seq) 关联工序需求；
  同资源逐日按 bars 顺序 append（执行层 FIFO）。
- 本函数不同步工序需求（调用方按需先行 sync_order_operations；手工行/自动行均从库读）。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mps import Order, OrderOperation, ScheduleAllocation, ScheduleBatch
from app.mps.context import load_ctx
from app.mps.dates import add_days, to_date
from app.mps.kernel import calc_order, nz
from app.mps.operations import merge_manual_bars
from app.mps.schedule import op_work
from app.mps.solver import solve


def order_to_dict(o: Order) -> dict:
    """DB 订单 → 内核输入 dict（calc_order/gate/回写消费）。"""
    return {
        "id": o.id, "order_no": o.order_no, "product": o.product, "code": o.code,
        "order_type": o.order_type, "first_flag": o.first_flag, "water_vapor": o.water_vapor,
        "qty": o.qty, "due_date": o.due_date, "kit_date": o.kit_date, "priority": o.priority,
        "features": o.features or {}, "remark": o.remark, "status": o.status,
        "prio_level": o.prio_level, "prio_score": o.prio_score, "prio_source": o.prio_source,
        "prio_manual": o.prio_manual, "pinned": o.pinned, "pinned_at": o.pinned_at,
        "sort_no": o.sort_no,
    }


async def run_schedule(session: AsyncSession, base_date, opts=None) -> dict:
    """载入正常工单 → 求解 → 落库批次/分配并回写订单；返回批次摘要。"""
    opts = dict(opts or {})
    ctx = await load_ctx(session)
    orders = (await session.execute(
        select(Order).where(Order.status == "正常").order_by(Order.order_no))).scalars().all()
    if not orders:
        raise ValueError("无待排工单（orders.status='正常' 为空）")
    results = [calc_order(order_to_dict(o), ctx) for o in orders]

    op_rows = (await session.execute(
        select(OrderOperation).where(OrderOperation.order_id.in_([o.id for o in orders]))
        .order_by(OrderOperation.order_id, OrderOperation.seq))).scalars().all()
    seq_by_id = {row.id: row.seq for row in op_rows}
    ops_by_order: dict = {}
    manual_rows_by_order: dict = {}
    for row in op_rows:
        ops_by_order.setdefault(row.order_id, {})[row.seq] = row.id
        if row.source == "manual":
            manual_rows_by_order.setdefault(row.order_id, []).append(row)
    for o, r in zip(orders, results):                        # D12：手工追加工序并入甘特参与排产
        mrows = manual_rows_by_order.get(o.id, [])
        if mrows:
            merge_manual_bars(r, [{"after_seq": seq_by_id.get(m.depends_on_id), "level": m.level,
                                   "op": m.op, "mode": m.mode, "usage": m.feature_usage}
                                  for m in mrows], ctx)

    out = solve(results, ctx, {**opts, "base_date": base_date})
    planned = out["schedule"]

    prefix = f"SCH-{to_date(base_date).strftime('%Y%m%d')}-"
    last = (await session.execute(
        select(ScheduleBatch.batch_no).where(ScheduleBatch.batch_no.like(prefix + "%"))
        .order_by(ScheduleBatch.batch_no.desc()).limit(1))).scalar()
    seq_no = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    batch_no = f"{prefix}{seq_no:03d}"
    batch = ScheduleBatch(
        batch_no=batch_no, base_date=to_date(base_date), solver_mode=out["solver"]["mode"],
        strategy_id=out["strategy"]["id"], params_snapshot=ctx["params"], kpi=out["metrics"])
    session.add(batch)
    await session.flush()

    by_no = {o.order_no: o for o in orders}
    alloc_rows = 0
    for r in planned:
        o = by_no[r["order"]["order_no"]]
        op_ids = ops_by_order.get(o.id, {})
        mrows = manual_rows_by_order.get(o.id, [])
        manual_bars = [b for b in r["gantt"]["bars"] if b.get("manual")]
        manual_ids = [m.id for m in mrows] if len(manual_bars) == len(mrows) else []
        m_at = 0
        for bar in r["gantt"]["bars"]:
            if bar.get("kind") != "step":
                continue
            if bar.get("manual"):
                op_id = manual_ids[m_at] if m_at < len(manual_ids) else None
                m_at += 1
            else:
                seq_val = bar.get("seq")
                op_id = op_ids.get(seq_val) if isinstance(seq_val, int) else None
            res = bar.get("res")
            busy = int(nz(bar.get("busy_days"), 0))
            if not res or busy <= 0 or not bar.get("from"):
                continue
            w = op_work(r, bar)
            if not w:
                continue
            per_day = w["amt"] / busy
            for i in range(busy):
                session.add(ScheduleAllocation(
                    batch_id=batch.id, order_id=o.id, operation_id=op_id, resource_key=res,
                    work_date=to_date(add_days(bar["from"], i)), qty=per_day))
                alloc_rows += 1

    for r in planned:
        o = by_no[r["order"]["order_no"]]
        bn = r.get("bottleneck") or {}
        plan = r["plan"]
        o.input_qty = r["input_qty"]
        o.yield_ratio = r["ratio"]["used"]
        o.y_full = r["yield"]["full"]
        o.cycle_single = r["cycle"]["used"]
        o.cycle_batch = r["batch"]["batch_cycle"]
        o.adopted_flux = bn.get("throughput")
        o.bottleneck_op = bn.get("step_std")
        o.ramp_applied = int(r["ramp"]["used"])
        o.delivery_cycle = r["delivery"]["days"]
        o.latest_start_date = to_date(r["delivery"]["latest_start_date"])
        o.plan_start_date = to_date(plan["start_date"])
        o.plan_finish_date = to_date(plan["finish_date"])
        o.gap_days = plan["gap_days"]
        o.judge = plan["judge"]
        o.strategy_id = plan["strategy_id"]
    await session.commit()
    return {"batch_id": batch.id, "batch_no": batch_no, "base_date": base_date,
            "solver_mode": out["solver"]["mode"], "strategy_id": out["strategy"]["id"],
            "kpi": out["metrics"], "solver": out["solver"], "order_count": len(planned),
            "allocation_rows": alloc_rows, "warnings": out["warnings"]}
```

- [x] **Step 4.4: 运行确认通过**（预期：service 3 passed、operations 8 passed；全量 189 passed, 1 skipped）

- [x] **Step 4.5: 提交** `feat(mps): 排产落库服务（批次/每日分配/订单回写）与工序依赖重挂修复`

---

### Task 5: 3B2 收尾（SCHED 清单回写 + 执行记录 + 计划 3 最终审查）

- [x] **Step 5.1: check-list 回写**：`docs/checklists/mps-logic-checklist.md` L92-101 的 CHK-SCHED-001~010 十行：前 4 列（编号/规则/来源/预期）保持；**第 5 列（测试用例）与第 6 列（状态）按下表更新**。注意目标表列序为「…｜测试用例｜状态」（测试用例在前、状态在后，勿写反）；第 5 列原预设的 `tests/mps/test_kernel_sched.py::...` 为编制期占位，一律替换为下表实测文件路径：

| 条目 | 第 5 列（测试用例·实测文件） | 第 6 列（状态） |
| --- | --- | --- |
| CHK-SCHED-001 | `tests/mps/test_mps_schedule.py::test_schedule_process_constrained_full_contract` | 通过（2026-10-16 回写） |
| CHK-SCHED-002 | `tests/mps/test_mps_schedule.py::test_alloc_earliest_basic_and_daily_spread`、`test_alloc_earliest_scan_gap_and_capacity_fit` | 通过（2026-10-16 回写） |
| CHK-SCHED-003 | `tests/mps/test_mps_schedule.py::test_schedule_process_constrained_full_contract`（按实际批量半分/自动断言） | 通过（2026-10-16 回写） |
| CHK-SCHED-004 | `tests/mps/test_mps_schedule.py::test_sched_004_kit_gate` | 通过（2026-10-16 回写） |
| CHK-SCHED-005 | `tests/mps/test_mps_schedule.py::test_sched_005_subpart_and_gantt_chart` | 通过（2026-10-16 回写） |
| CHK-SCHED-006 | `tests/mps/test_mps_operations.py::test_sched_006_rework_extra_operation` | 通过（2026-10-16 回写） |
| CHK-SCHED-007 | `tests/mps/test_mps_schedule.py::test_sched_007_setup_days` | 通过（2026-10-16 回写） |
| CHK-SCHED-008 | `tests/mps/test_mps_solver.py::test_chk_sched_008_ga_mode_contract`、`tests/mps/test_mps_schedule.py::test_schedule_process_constrained_full_contract`（capViolations） | 通过（2026-10-16 回写） |
| CHK-SCHED-009 | `tests/mps/test_mps_solver.py::test_chk_sched_009_deterministic_equals_direct_call`、`tests/mps/test_mps_schedule.py::test_sched_009_strategy_order_and_deterministic` | 通过（2026-10-16 回写） |
| CHK-SCHED-010 | `tests/mps/test_mps_schedule_service.py::test_chk_sched_010_batch_result_persistence` | 通过（2026-10-16 回写） |

- [x] **Step 5.2: 全量回归**（预期 189 passed, 1 skipped）：

```powershell
$env:PYTHONIOENCODING="utf-8"; & "F:\aps-hap\offline\runtime\python\python.exe" -m pytest tests -q
```

- [x] **Step 5.3: 执行记录**：`docs/superpowers/plans/2026-10-14-mps-rework-plan3-execution-log.md` 追加 3B2 节（摘要：4 模块 23 测试；决策：GA 索引排列/确定性默认关 setup/CP-SAT 延后/D12 手工条服务管道接入（run_schedule 读 manual 行 → merge_manual_bars）；教训：date 归一 bug、cxOrdered 整数基因、HallOfFame deepcopy、手工条 operation_id 按 append 顺序关联（免对象身份依赖）、PowerShell 中文乱码用 utf-8 环境变量与文件落盘读回；移交修复：operations 依赖重挂、week_days 透传）并提交。

- [x] **Step 5.4: 计划 3 最终审查**：核对 3A/3B1/3B2 三份计划自查项；确认 SCHED 十条全绿、无遗留"待实现"；向用户提交最终报告（计划含 Task 提交清单、测试计数演进 166→174→179→185→189、探针证据摘要、开放问题：`ga_*` 参数页是否需前端展示、deap 版本升级策略）。

---

## 完成定义（3B2 结束时）

1. `aps.py` 与 `aps.js` 语义对齐（date 归一为已留痕移植修正）；GA/solver/service 按本计划契约实现；
2. CHK-SCHED-008/009/010 测试全绿，001~007 状态回写完成；
3. 全量测试绿灯（189 passed, 1 skipped）；每任务独立提交；
4. 计划 3 执行记录含 3B2 节与全部移交修复留痕。

## 后续衔接（计划 4/5）

- API 层（FastAPI 路由）调用 `run_schedule`（含前端"排产运行"入口与批次历史/对比查询）；
- 看板/甘特前端消费 `solver.solve` 返回的 `gantt/decode.ledger`（与 3B1 `build_kanban` 共享账本契约）；
- `ga_*` 参数页展示（PARAM_DEFS group="求解" 自动出现在参数管理页）。

## Self-Review 记录

- 规格覆盖：D11（GA 默认/CP-SAT 延后/确定性基准）、D12（工序需求与手工条参与分配）、SCHED-008/009/010 全映射；3B1 移交两项修复（依赖重挂、week_days 透传）已入 Task 3/4。
- 占位符扫描：无 TBD；所有测试断言值为探针实测（date 归一 bug 即由探针捕获并已修正入 Task 1 代码）。
- 类型一致性：`planned[].gantt.bars[].{from,to,busy_days,setup_days,res,seq}`、`plan{}`、`decode{ledger,fluxOf,capViolations}`、`solver{}`、`batch_no` 规则在测试与代码中一致；`run_schedule` 与 `solver.solve` 键名一致（solver_mode/strategy_id/kpi/solver/warnings）。
- 计数一致性：166 → +8（174）→ +5（179）→ +6（185）→ +4（189）；test_consts/test_mps_schedule 为修改既有测试不增计数。
