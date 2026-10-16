"""排产解码层（移植自 mps-web src/schedule.js；纯函数，不写库）。

- alloc_earliest：按日产能账本找"最早可排时段"（整批占用、顺延、可选 nooverlap）
- op_work：单工单在资源上的工作量（特征量）；含 [扩展] 手工追加条（返工/试制）
- 与 JS 的已知微观差异：页码扫描上限同 3650；`Math.floor(from)||0` → `max(0, int(from))`。
"""
from datetime import date

from app.mps import priority as prio   # noqa: F401（资源键/排序由第二批使用）
from app.mps.dates import add_days, diff_days, to_str  # noqa: F401
from app.mps.kernel import ceil_int, nz


def order_opts(opts=None) -> dict:
    """构造传给 orderFn 的排序选项（注入可调参数：换线天数/交期缓冲）。"""
    o = dict(opts or {})
    p = o.get("P") or {}
    if o.get("setupDiff") is None:
        o["setupDiff"] = nz(p.get("setup_days"), 0.5)
    o["due_buffer_days"] = nz(p.get("due_buffer_days"), 0)
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


op_key = resource_key  # 与 JS 两份同构函数等价


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
