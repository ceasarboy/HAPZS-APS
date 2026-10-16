"""排产解码移植测试（① 账本分配/opWork；② 定序排产/甘特/护栏）。"""
import pytest

from app.mps.dates import diff_days
from app.mps.schedule import alloc_earliest, op_work, order_opts, resource_key


def test_order_opts_defaults():
    o = order_opts({"P": {"setup_days": 1.5, "due_buffer_days": 3, "week_days": 5}})
    assert o["setupDiff"] == 1.5 and o["due_buffer_days"] == 3 and o["week_days"] == 5
    o2 = order_opts()
    assert o2["setupDiff"] == 0.5 and o2["due_buffer_days"] == 0 and o2["week_days"] == 6


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
            "模块级|调试": {"modes": [
                {"mode": "/", "flux_base": 10000, "flux_peak": 11000, "split_threshold": 1, "unit": "套/天"},
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


def _mk_results():
    from app.mps.kernel import calc_order

    ctx = _ctx_min()
    orders = [
        {"order_no": "B", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
         "water_vapor": "有", "qty": 5, "priority": 200, "features": {"N_die": 60, "N_wire": 60}},
        {"order_no": "A", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
         "water_vapor": "有", "qty": 1000, "priority": 100, "due_date": "2026-09-30",
         "features": {"N_die": 60, "N_wire": 60}},
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
    # SCHED-009 附属：due 链（gap/judge/最新投料）自洽
    p1 = planned[1]["plan"]
    assert p1["judge"] == "满足" and p1["start_date"] < p1["latest_start_date"]
    assert p1["gap_days"] == diff_days(p1["deliver_date"], "2026-09-30")
    assert planned[0]["plan"]["gap_days"] is None          # B 无交期
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
    r3, _ = _mk_results()
    out3 = schedule_process_constrained(r3, "2026-06-01", {})
    assert [r["order"]["order_no"] for r in out3["planned"]] == \
           [r["order"]["order_no"] for r in out["planned"]]      # 确定性


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
    first_step = next(b for b in lane["bars"] if b["kind"] == "step")
    assert sub["to"] <= first_step["from"]                # 前置条先于主体
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
    assert "顺延" in b2["plan"]["rationale"]


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
    # 修正留痕（2026-10-16，Node 实证）：WC 条目缺失时 kernel 将 step.mode 置 "/"（与 engine.js 一致），
    # 调度层无 WC 数据可回推模式，护栏资源键只能是 "模块级|DB|/"；原稿预期 "自动DB" 与夹具不自洽
    assert out["warnings"][0]["res"] == "模块级|DB|/"
    assert out["planned"][0]["order"]["order_no"] == "D"          # 计划仍产出
