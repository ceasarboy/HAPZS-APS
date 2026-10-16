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
