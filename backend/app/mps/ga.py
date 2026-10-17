"""GA 序列搜索核心（DEAP；设计 D11 默认求解器；新实现，无 JS 对照）。

染色体 = 待排序列的**索引排列**（`list(range(n))` 的重排，索引映射回 passed 列表）：
DEAP `tools.cxOrdered` 要求整数基因，不能直接用结果 dict 作基因（探针实证）。

- 适应度 = aps.objective(aps_metrics(decode(genome)))，最小化；
- 种群首部注入种子序列（策略序/GT 序，按 order_no 映射为索引）；无种子时真值基准取输入序；
- 随机流隔离：`random.seed(seed)` 前保存 `random.getstate()`、结束 `setstate` 恢复；
- 参数优先级：opts > `ctx["params"]`（ga_population/ga_generations/ga_seed）> 常量默认（30/20/42）；
- 目标权重缺省取 `aps.DEFAULT_WEIGHTS`（solver 恒显式传入；独立调用兜底）；
- creator 全局单例守卫（重复导入/多测试复用不报错）；`tools.HallOfFame(1)` 内部 deepcopy 保管最优。
"""
import copy
import random

from deap import algorithms, base, creator, tools

from app.mps.aps import DEFAULT_WEIGHTS, aps_metrics, objective
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
    weights = dict(opts.get("weights") or DEFAULT_WEIGHTS)
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
