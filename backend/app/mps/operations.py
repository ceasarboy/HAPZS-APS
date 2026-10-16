"""工序级需求（设计 D12）：产品工单按路线自动分解；手工追加（返工/试制）参与排产。

- decompose：从核算结果的 steps 生成工序级需求（自动行）
- sync_order_operations：auto 行删除重建（depends_on_id 按 seq 链）；manual 行保留
- add_manual_operation：手工追加工序需求（挂在指定 seq 的 auto 行之后）
- merge_manual_bars：把手工行转换为解码层可消费的 extra bars（[扩展] manual 标记）
- sync/追加逐单提交（非批处理原子），与 priority_service 口径一致。
"""
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mps import OrderOperation
from app.mps.kernel import nz, pick_mode


def decompose(calc_result) -> list[dict]:
    rows = []
    prev = None
    for s in calc_result.get("steps", []):
        rows.append({
            "seq": s.get("seq"), "level": s.get("level"), "op": s.get("step_std"),
            "mode": s.get("mode"), "qty": calc_result.get("input_qty"),
            "unit": s.get("unit"), "feature_key": s.get("feature_key"),
            "feature_usage": s.get("usage"), "source": "auto",
            "depends_on_seq": prev, "note": None,
        })
        prev = s.get("seq")
    return rows


async def sync_order_operations(session: AsyncSession, order_id: str, calc_result) -> int:
    """重建该单自动工序需求（manual 行保留），返回插入行数。"""
    if calc_result.get("error") or "steps" not in calc_result:
        raise ValueError("calc_result 无效（含 error 或缺少 steps），拒绝重建工序需求")
    await session.execute(
        delete(OrderOperation).where(OrderOperation.order_id == order_id, OrderOperation.source == "auto"))
    rows = decompose(calc_result)
    by_seq: dict = {}
    for row in rows:
        op = OrderOperation(order_id=order_id, seq=row["seq"], level=row["level"], op=row["op"],
                            mode=row["mode"], qty=row["qty"], unit=row["unit"],
                            feature_key=row["feature_key"], feature_usage=row["feature_usage"],
                            source="auto", note=None)
        session.add(op)
        await session.flush()
        by_seq[row["seq"]] = op.id
        if row["depends_on_seq"] is not None:
            op.depends_on_id = by_seq.get(row["depends_on_seq"])
    await session.commit()
    return len(rows)


async def add_manual_operation(session: AsyncSession, order_id: str, *, level: str, op: str,
                               mode=None, qty=None, usage=None, after_seq=None, note=None) -> OrderOperation:
    """手工追加工序需求（返工/试制）；seq 追加在末位，依赖由 depends_on_id 表达。"""
    max_seq = (await session.execute(
        select(OrderOperation.seq).where(OrderOperation.order_id == order_id)
        .order_by(OrderOperation.seq.desc()).limit(1))).scalar() or 0
    dep_id = None
    if after_seq is not None:
        dep_id = (await session.execute(
            select(OrderOperation.id).where(OrderOperation.order_id == order_id,
                                            OrderOperation.seq == after_seq).limit(1))).scalar()
    rec = OrderOperation(order_id=order_id, seq=int(max_seq) + 1, level=level, op=op, mode=mode,
                         qty=qty, feature_usage=usage, source="manual",
                         depends_on_id=dep_id, note=note)
    session.add(rec)
    await session.commit()
    return rec


def merge_manual_bars(calc_result, manual_ops: list[dict], ctx: dict) -> list[dict]:
    """手工工序需求 → 解码层 bars（追加进 calc_result['gantt']['bars']）并返回 bars 列表。

    manual_ops 每项：{after_seq, level, op, mode?, usage}
    - flux 按订单实际批量分流从主数据解析（缺主数据 → flux None → 解码时跳过并告警）
    - 显式 mode 时按 mode_name 精确匹配取产能；无匹配 → flux None（解码护栏）：
    - seq 取前道条 seq + 0.5（排序保持其后）；earliest_start 取前道条同值
    """
    bars = calc_result["gantt"]["bars"]
    bars[:] = [b for b in bars if not b.get("manual")]  # 幂等：以本次 manual_ops 为准，先剥离既有手工条
    qty = calc_result["input_qty"]
    p = ctx["params"]
    use_peak = str(p.get("use_peak") or "mean") == "peak"
    for m in manual_ops:
        wc = ctx["wc_map"].get(f"{m['level']}|{m['op']}")
        flux = None
        mode = m.get("mode")
        if wc:
            md_ = None
            if mode:
                md_ = next((x for x in (wc.get("modes") or []) if (x.get("mode") or "/") == mode), None)
            else:
                picked = pick_mode(wc, qty)
                if picked:
                    mode = picked["mode_name"]
                    md_ = picked["mode"]
            if md_:
                flux = nz(md_.get("flux_peak"), 0) if use_peak else nz(md_.get("flux_base"), 0)
        pred = next((b for b in bars
                     if b.get("kind") == "step" and b.get("seq") == m.get("after_seq")), None)
        bar = {"kind": "step", "seq": (pred["seq"] + 0.5) if pred else (max(
                   [b.get("seq") or 0 for b in bars if b.get("kind") == "step"] or [0]) + 1),
               "step_std": m["op"], "step_raw": m["op"], "level": m["level"], "mode": mode or "/",
               "usage": m.get("usage"), "flux": flux, "manual": True,
               "earliest_start": pred["earliest_start"] if pred else 0,
               "is_bottleneck": False, "throughput": None}
        bars.append(bar)
    return bars
