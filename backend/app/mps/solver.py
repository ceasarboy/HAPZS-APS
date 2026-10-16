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
