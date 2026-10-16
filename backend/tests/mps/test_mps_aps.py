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
