"""求解门面（solver）：模式契约/确定性等价（CHK-SCHED-009）/复现/异常文案。"""
import pytest

from app.mps.schedule import schedule_process_constrained
from app.mps.solver import MODES, solve
from tests.mps.test_mps_aps import BASE, gate_fixture, improve_fixture, seq_fixture


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


def test_solve_improved_branch_heuristic_and_ga():
    """improved=True 分支：GT 序非最优夹具（策略序=GT 序 15.0475 → 最优 4.1475）下
    heuristic 出 (已改进) 后缀、GA 找到更优排列（3B2 质量跟进）。"""
    results, ctx = improve_fixture()
    out = solve(results, ctx, {"base_date": BASE, "mode": "heuristic", "iterations": 200, "seed": 42})
    assert out["method"] == "heuristic+local-search(已改进)"
    assert out["sequence"] == ["WO-R", "WO-B"]
    assert out["solver"]["improved"] is True
    assert out["solver"]["baseline_objective"] == pytest.approx(15.0475)
    assert out["solver"]["objective"] == pytest.approx(4.1475)
    results2, ctx2 = improve_fixture()
    out2 = solve(results2, ctx2, {"base_date": BASE, "mode": "ga", "population": 8, "generations": 3})
    assert out2["sequence"] == ["WO-R", "WO-B"]
    assert out2["solver"]["improved"] is True
    assert out2["solver"]["baseline_objective"] == pytest.approx(15.0475)
    assert out2["solver"]["objective"] == pytest.approx(4.1475)


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
