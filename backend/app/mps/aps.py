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
