"""排产解码层（移植自 mps-web src/schedule.js；纯函数，不写库）。

- alloc_earliest：按日产能账本找"最早可排时段"（整批占用、顺延、可选 nooverlap）
- op_work：单工单在资源上的工作量（特征量）；含 [扩展] 手工追加条（返工/试制）
- schedule_process_constrained：工序级有限产能正排（定序 + 逐日账本 + 换型 + 齐套门槛 + 硬约束核验）
- schedule：入口；capacity 缺省 True 走正排，False 走时间线错开（兼容/对照）
- gantt_chart：相对天数 → 绝对日期甘特（含换型条）
- [扩展] 护栏（偏离 JS，已留痕）：缺工作中心主数据时 op_work 得 flux=1e-9，JS 会因此
  grow 6.3e13 行挂死；此处跳过产能分配、记 warnings 并继续。
- 与 JS 的已知微观差异：顺延扫描上限同 3650；`Math.floor(from)||0` → `max(0, int(from_) or 0)`
  （None/NaN 时 JS 归 0、Python 抛错，真实调用方均为数值）；subpart 分支对缺失 process
  防御性兜底（JS 直接抛错）；nooverlap 判别为 JS 同源死分支（day_free 恒 > i，保留同构）；
  `sequenceOrder: []` 空数组时 Python 走策略排序、JS 保原序（调用方不传空数组）；
  base 缺省 `date.today()`（本地时区）vs JS UTC。
- 与 JS 的已知行为偏差（计划 3B1 Task2 留痕）：
  ① kit_adjusted 取 kit_offset > 0（分配已强制 start ≥ kit；JS `diffDays(start, kit) < 0`
     为边界死分支恒假，齐套门槛实际生效时也应标注调整）；
  ② gantt 无 from/to 的条在有界产能模式下按 base 回退（JS 按 plan.start_date，前置分部件
     会与首道工序重叠；本实现要求前置分部件完成于首道工序开工前）；
  ③ cap 核验对无 steps 对应的资源键（[扩展] 手工条）回退 fluxOf（JS 取不到 step 得 1e-9 会误报超载）。
"""
import math
from datetime import date

from app.mps import priority as prio  # noqa: F401（JS 同源占位，上游亦未使用；保留同构）
from app.mps import strategy as strategy_mod
from app.mps.dates import add_days, diff_days, to_str
from app.mps.kernel import ceil_int, nz


def order_opts(opts=None) -> dict:
    """构造传给 orderFn 的排序选项（注入可调参数：换线天数/交期缓冲/周工作天数）。"""
    o = dict(opts or {})
    p = o.get("P") or {}
    if o.get("setupDiff") is None:
        o["setupDiff"] = nz(p.get("setup_days"), 0.5)
    o["due_buffer_days"] = nz(p.get("due_buffer_days"), 0)
    o["week_days"] = nz(p.get("week_days"), 6)
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


def _judge(due, gap) -> str:
    """交期判定（js 两分支同式）：无交期 / 零裕量（gap==0）/ 满足 / 延期。"""
    if not due:
        return "无交期"
    if gap is not None and gap < 0:
        return "延期"
    return "零裕量" if gap == 0 else "满足"


def _ordered_results(results, opts, strat):
    """工单处理顺序：显式 sequenceOrder 优先，否则所选策略 orderFn（js 两分支同式）。"""
    seq = opts.get("sequenceOrder")
    if seq:
        idx = {str(o): i for i, o in enumerate(seq)}
        return sorted(results, key=lambda r: idx.get(str((r.get("order") or {}).get("order_no")), 1e9))
    return strat["orderFn"](results, order_opts(opts))


def schedule_process_constrained(results, base, opts=None) -> dict:
    """工序级有限产能正排（js:245-370 移植）。

    以 (级别|工序|模式) 为资源逐日核算产能；超产能整批顺延；同工单内工序按
    (earliest_start, seq) 串行；opts.setup 时同资源跨工艺族插入换型。
    返回 {planned, ledger, capViolations, fluxOf, warnings, strategy}。
    """
    opts = opts or {}
    strat = strategy_mod.get_strategy(opts.get("strategy"), opts.get("P"))
    sorted_ = _ordered_results(results, opts, strat)

    ledger: dict = {}
    flux_of: dict = {}        # 资源键 -> 日产能（供看板/负荷率使用）
    warnings: list = []       # [扩展] 护栏告警（缺主数据跳过的工序）
    last_family: dict = {}    # 资源上一单工艺族（换型建模）
    last_end: dict = {}       # 资源上一单结束日（换型建模）
    planned: list = []
    cap_violations: list = []  # 逐日核算：占用量 > 日产能（修正后应恒为空）

    # 分配策略：换型场景强制 nooverlap（配合序列依赖换型建模），其余用策略自带 allocPolicy
    alloc_policy = "nooverlap" if (strat["allocPolicy"] == "nooverlap" or opts.get("setup")) else strat["allocPolicy"]

    for r in sorted_:
        if r.get("error"):
            continue
        fam = (r.get("aps") or {}).get("family") if opts.get("setup") else None
        start0 = base

        # 逐工序分配：串行保证同工单内部依赖（每道工序起点 ≥ 前道工序占用结束点）
        ordered = sorted((b for b in r["gantt"]["bars"] if b.get("kind") != "subpart"),
                         key=lambda b: (nz(b.get("earliest_start"), 0), nz(b.get("seq"), 0)))
        # 物料齐套时间：上线不得早于齐套日，作为分配起点参与产能占用（与账本一致）
        kit = r["order"].get("kit_date")
        kit_offset = max(0, diff_days(start0, kit) or 0) if kit else 0
        cursor = kit_offset
        deferred_note = None  # 排产理由：首个因产能已满而整批顺延的工序
        for bar in ordered:
            w = op_work(r, bar)
            if not w:
                continue
            # [扩展] 护栏：缺 WC 主数据（flux≈0）→ 跳过分配并告警（JS 同病会 grow 6.3e13 行挂死）
            if w["flux"] <= 1e-9:
                warnings.append({"order_no": r["order"]["order_no"], "step": bar.get("step_std"),
                                 "res": w["key"], "reason": "缺少工作中心主数据（日产能为 0），已跳过产能分配"})
                continue
            flux_of[w["key"]] = w["flux"]
            base_from = max(kit_offset, bar["earliest_start"], cursor)
            from_ = base_from
            setup_days = 0
            if (opts.get("setup") and fam and last_family.get(w["key"]) is not None
                    and last_family.get(w["key"]) != fam):
                setup_days = nz(opts.get("setupDiff"), 0.5)
                req = base_from if last_end.get(w["key"]) is None else last_end[w["key"]] + setup_days
                if req > from_:
                    from_ = req
            alloc = alloc_earliest(ledger, w["key"], from_, w["amt"], w["flux"], alloc_policy)
            # 排产理由：实际分配起点晚于「最早可行起点」→ 被产能约束整批顺延
            # （换型引起的顺延亦沿用产能文案，JS 同条件同文案，勿修）
            if not deferred_note and alloc["start"] > base_from + 1e-9:
                step_label = "/".join(str(w["key"]).split("|")[1:])
                deferred_note = f"因 {step_label} 产能已满，整批顺延至 {add_days(start0, alloc['start'])}"
            bar["from"] = add_days(start0, alloc["start"])
            bar["to"] = add_days(start0, alloc["end"])
            bar["busy_days"] = alloc["span"]
            bar["setup_days"] = setup_days
            bar["res"] = w["key"]
            cursor = alloc["end"]  # 下一道工序最早从本道占用结束点开始（保持依赖）
            last_family[w["key"]] = fam
            last_end[w["key"]] = alloc["end"]

        # 计划开工 = 首道有实际分配的工序起点（护栏跳过的条无 from；全无则回退 add_days(base, kit_offset)，JS 口径）
        first_start = None
        for b in r["gantt"]["bars"]:
            if b.get("kind") in ("subpart", "step") and b.get("from"):
                if first_start is None or b["from"] < first_start:
                    first_start = b["from"]
        start = first_start or add_days(start0, kit_offset)

        batch = r["batch"]["batch_cycle"]
        # 完工 = 末道工序实际产能占用结束日（顺延后可能晚于 start+batch）
        last_bar_end = None
        for b in r["gantt"]["bars"]:
            if b.get("to") and (last_bar_end is None or b["to"] > last_bar_end):
                last_bar_end = b["to"]
        finish = add_days(last_bar_end, -1) if last_bar_end else add_days(start, batch)
        delivery_days = r["delivery"]["days"]
        deliver = add_days(start, delivery_days)
        due = r["order"].get("due_date") or None
        latest = add_days(due, -delivery_days) if due else None
        # 齐套约束实际生效（较 base 推迟了上线）；JS `diffDays(start, kit) < 0` 为恒假死分支（留痕）
        kit_adjusted = bool(kit and kit_offset > 0)
        reason_parts = []
        if kit_adjusted:
            reason_parts.append(f"上线受物料齐套时间 {kit} 约束（实际开工 {start}）")
        if deferred_note:
            reason_parts.append(deferred_note)
        gap = diff_days(deliver, due) if due else None
        r["plan"] = {
            "start_date": start,
            "finish_date": finish,
            "deliver_date": deliver,
            "latest_start_date": latest,
            "gap_days": gap,
            "judge": _judge(due, gap),
            "kit_date": kit,
            "kit_adjusted": kit_adjusted,
            "kit_note": f"上线时间受物料齐套时间 {kit} 约束（实际开工 {start}）" if kit_adjusted else None,
            "kit_risk": bool(kit and latest and (diff_days(latest, kit) or 0) > 0),
            "resource_constrained": True,
            "strategy_id": strat["id"],
            "strategy_name": strat["name"],
            "rationale": "；".join(reason_parts) if reason_parts
            else f"按「{strat['name']}」策略正常排产，无产能冲突",
        }
        planned.append(r)

    # 逐日产能核验：每个时段占用均不得超工序日产能（修正目标）
    for key, rows in ledger.items():
        row0 = next((p for p in planned
                     if any(f"{s['level']}|{s['step_std']}|{s['mode']}" == key for s in p["steps"])), None)
        step0 = None
        if row0 is not None:
            step0 = next((s for s in row0["steps"]
                          if f"{s['level']}|{s['step_std']}|{s['mode']}" == key), None)
        flux = max(1e-9, nz(step0["flux_base"] if step0 else None, 0))
        if step0 is None:
            flux = flux_of.get(key, flux)  # [扩展] 手工条等无 steps 对照的键回退分配时记录的日产能
        for i, cell in enumerate(rows):
            if cell["used"] > flux + 1e-9:
                cap_violations.append({"resource": key, "day_index": i, "date": add_days(base, i),
                                       "used": cell["used"], "flux": flux, "over": cell["used"] - flux})

    return {"planned": planned, "ledger": ledger, "capViolations": cap_violations, "fluxOf": flux_of,
            "warnings": warnings,
            "strategy": {"id": strat["id"], "name": strat["name"], "allocPolicy": alloc_policy,
                         "desc": strat["desc"]}}


def schedule(results, opts=None) -> list:
    """排产入口（js:72-174）。capacity 缺省 True → 有界产能正排，仅返回 planned。"""
    opts = opts or {}
    base = opts.get("base_date") or to_str(date.today())
    if opts.get("capacity") is not False:
        return schedule_process_constrained(results, base, opts)["planned"]

    # 非容量分支（时间线错开模式，兼容/对照用）：同样尊重所选策略的排序
    strat = strategy_mod.get_strategy(opts.get("strategy"), opts.get("P"))
    sorted_ = _ordered_results(results, opts, strat)

    timeline: dict = {}     # 资源占用时间线：key -> [{from,to,setup?}]
    last_family: dict = {}  # 资源上一单工艺族/结束日（换型建模）
    last_end: dict = {}
    planned: list = []
    for r in sorted_:
        if r.get("error"):
            continue
        batch = r["batch"]["batch_cycle"]
        fam = (r.get("aps") or {}).get("family") if opts.get("setup") else None
        if opts.get("sequence"):
            start_iso = base
            # 逐资源检查最早可开工日（含已占用区间错开）
            for bar in r["gantt"]["bars"]:
                key = resource_key(r, bar)
                if not key:
                    continue
                for iv in timeline.get(key) or []:
                    overlap_start = add_days(iv["from"], -bar["earliest_start"])
                    if overlap_start > start_iso:
                        start_iso = overlap_start
                    cand_end = add_days(start_iso, bar["earliest_start"] + bar["busy_days"])
                    need = min(iv["from"], cand_end) < max(iv["to"], add_days(start_iso, bar["earliest_start"]))
                    if need:
                        # JS 同源已知行为（多区间命中时 start 可被回拉），勿修
                        start_iso = add_days(iv["to"], -bar["earliest_start"])
                # 换型约束：同资源工艺族切换需插入换型时间（序列依赖）
                if opts.get("setup") and fam and last_family.get(key) is not None and last_family.get(key) != fam:
                    sd = nz(opts.get("setupDiff"), 0.5)
                    req_start = add_days(last_end[key], sd - bar["earliest_start"])
                    if req_start > start_iso:
                        start_iso = req_start
            r["plan"] = {"start_date": start_iso}
        else:
            r["plan"] = {"start_date": base}
        start = r["plan"]["start_date"]
        # 物料齐套时间约束：上线时间不得早于齐套时间
        kit = r["order"].get("kit_date")
        d_kit = diff_days(start, kit)
        kit_adjusted = bool(kit and d_kit is not None and d_kit > 0)
        eff_start = kit if kit_adjusted else start
        r["plan"] = {**r["plan"], "start_date": eff_start, "kit_date": kit, "kit_adjusted": kit_adjusted,
                     "kit_note": f"上线时间已按物料齐套时间 {kit} 后移至 {eff_start}" if kit_adjusted else None}
        finish = add_days(eff_start, batch)
        delivery_days = r["delivery"]["days"]
        deliver = add_days(eff_start, delivery_days)
        due = r["order"].get("due_date") or None
        latest = add_days(due, -delivery_days) if due else None
        gap = diff_days(deliver, due) if due else None
        r["plan"] = {**r["plan"], "finish_date": finish, "deliver_date": deliver, "latest_start_date": latest,
                     "gap_days": gap, "judge": _judge(due, gap),
                     # 齐套风险：齐套时间晚于最晚上线时间（需求日期 − 交付周期）
                     "kit_risk": bool(kit and latest and (diff_days(latest, kit) or 0) > 0)}
        if opts.get("sequence"):
            for bar in r["gantt"]["bars"]:
                key = resource_key(r, bar)
                if not key:
                    continue
                b_from = add_days(eff_start, bar["earliest_start"])
                b_to = add_days(eff_start, bar["earliest_start"] + bar["busy_days"])
                if opts.get("setup"):
                    # 换型占用：位于本工序条之前
                    sd_apply = nz(opts.get("setupDiff"), 0.5) if (
                        fam and last_family.get(key) is not None and last_family.get(key) != fam) else 0
                    bar["setup_days"] = sd_apply
                    if sd_apply > 0:
                        timeline.setdefault(key, []).append(
                            {"from": last_end[key], "to": add_days(last_end[key], sd_apply), "setup": True})
                timeline.setdefault(key, []).append({"from": b_from, "to": b_to})
                last_family[key] = fam
                last_end[key] = b_to
        planned.append(r)
    return planned


def gantt_chart(results, opts=None) -> dict:
    """相对天数 → 绝对日期甘特（js:436-481 移植；含换型条与 horizon 计算）。"""
    opts = opts or {}
    start0 = opts.get("base_date")
    lanes = []
    for r in results:
        if r.get("error"):
            continue
        plan = r.get("plan") or {}
        s = plan.get("start_date") or start0
        # [扩展] 有界产能模式下 bar 偏移以 base 为基准，无 from/to 的条（前置分部件/护栏跳过）
        # 按 base 回退（JS 按 plan.start_date，subpart 会与首道工序重叠）；非容量分支保持 JS 口径
        anchor = start0 if plan.get("resource_constrained") else s
        bars = []
        for b in r["gantt"]["bars"]:
            from_ = b.get("from") or add_days(anchor, nz(b.get("earliest_start"), 0))
            to_ = b.get("to") or add_days(anchor, nz(b.get("earliest_start"), 0) + nz(b.get("busy_days"), 0))
            res = b.get("res") or resource_key(r, b)
            bars.append({**b, "from": from_, "to": to_, "res": res})
            if b.get("setup_days") and b["setup_days"] > 0:
                bars.append({"kind": "setup", "seq": b.get("seq"), "step_std": "换型", "mode": "",
                             "from": add_days(from_, -b["setup_days"]), "to": from_,
                             "res": res, "setup_days": b["setup_days"]})
        lanes.append({
            "order_no": r["order"]["order_no"], "product": r["order"]["product"], "code": r["process"]["code"],
            "qty": r["order"]["qty"], "input_qty": r["input_qty"], "start": s,
            "finish": plan.get("finish_date"), "deliver": plan.get("deliver_date"),
            "due": r["order"].get("due_date"), "judge": plan.get("judge"),
            "kit_date": plan.get("kit_date"), "kit_adjusted": plan.get("kit_adjusted"),
            "bottleneck": f"{r['bottleneck']['step_std']}({r['bottleneck']['mode']})" if r.get("bottleneck") else "-",
            "batch": r["batch"]["batch_cycle"],
            "bars": bars,
        })
    # 实际所需跨度：覆盖全部工单最早开工到最晚 完成/交付/需求/齐套/工序占用结束
    need = math.ceil(opts["horizon_days"]) if opts.get("horizon_days") else 0
    for l in lanes:
        cand = [l["finish"], l["deliver"], l["due"], l["kit_date"]] + [b["to"] for b in l["bars"]]
        for d in cand:
            if not d:
                continue
            off = diff_days(start0, d)
            if off is not None and off > need:
                need = off
    horizon = max(1, need + 2)  # 右端留 2 天余量，避免末端刻度/标签被裁切
    return {"base_date": start0, "horizon_days": horizon, "end_date": add_days(start0, horizon), "lanes": lanes}
