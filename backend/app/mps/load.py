"""周负荷与产线瓶颈（移植自 mps-web src/schedule.js weeklyLoad / lineBottleneck）。"""
from app.mps.kernel import nz


def weekly_load(results: list[dict], opts: dict) -> list[dict]:
    """周负荷 = Σ(投料量 × 单只特征用量)；周可用 = 基准通量 × 周工作天数。

    判定：rate>1 超载 / ≥0.85 偏紧 / <0.85 正常；缺通量为 "缺通量"。
    """
    p = opts.get("params") or {}
    week_days = nz(p.get("week_days"), 6)
    use_peak = str(p.get("use_peak") or "mean") == "peak"
    agg: dict[str, dict] = {}
    for r in results:
        if r.get("error"):
            continue
        for s in r["steps"]:
            if not s.get("wc_key"):
                continue
            key = f"{s['wc_key']}|{s['mode']}"
            if key not in agg:
                agg[key] = {
                    "key": key, "level": s.get("level"), "op": s.get("step_std"), "mode": s.get("mode"),
                    "feature": s.get("feature"), "feature_key": s.get("feature_key"), "unit": s.get("unit"),
                    "flux_base": s.get("flux_base"), "load": 0, "orders": [], "missing_orders": [],
                }
            a = agg[key]
            a["flux_base"] = max(a["flux_base"] or 0, s.get("flux_base") or 0)
            if s.get("missing") or not s.get("usage"):
                a["missing_orders"].append(r["order"]["order_no"])
                continue
            a["load"] += r["input_qty"] * s["usage"]
            a["orders"].append({"order_no": r["order"]["order_no"], "qty": r["input_qty"],
                                "usage": s["usage"], "amount": r["input_qty"] * s["usage"]})
    rows = []
    for a in agg.values():
        flux = (a["flux_base"] * nz(p.get("peak_factor"), 1.1)) if use_peak else a["flux_base"]
        available = flux * week_days
        rate = (a["load"] / available) if available > 0 else None
        rows.append({**a, "week_days": week_days, "flux_used": flux, "available": available,
                     "load_rate": rate,
                     "judge": "缺通量" if rate is None else ("超载" if rate > 1 else ("偏紧" if rate >= 0.85 else "正常"))})
    rows.sort(key=lambda x: x["load_rate"] or 0, reverse=True)
    return rows


def line_bottleneck(results: list[dict], load_rows: list[dict]) -> list[dict]:
    """产线瓶颈 = 承担工单最多的约束工序（按负荷率、命中次数排序）。"""
    cnt: dict[str, dict] = {}
    for r in results:
        if r.get("error") or not r.get("bottleneck"):
            continue
        s = next((x for x in r["steps"] if x.get("is_bottleneck")), None)
        if not s:
            continue
        key = f"{s['wc_key']}|{s['mode']}"
        if key not in cnt:
            cnt[key] = {"key": key, "level": s.get("level"), "op": s.get("step_std"), "mode": s.get("mode"),
                        "hits": 0, "orders": [], "total_days": 0}
        c = cnt[key]
        c["hits"] += 1
        c["orders"].append({"order_no": r["order"]["order_no"], "product": r["order"].get("product"),
                            "code": r["order"]["code"], "throughput": s.get("throughput"),
                            "batch": r["batch"]["batch_cycle"]})
        c["total_days"] += r["batch"].get("bottleneck_days") or 0
    rows = []
    for c in cnt.values():
        load = next((l for l in load_rows if l["key"] == c["key"]), None)
        rows.append({**c, "load_rate": load["load_rate"] if load else None,
                     "judge": load["judge"] if load else None})
    rows.sort(key=lambda x: (-(x["load_rate"] or 0), -x["hits"]))
    return rows
