"""排产服务：载单 → 手工条并入 → 求解 → 批次/每日分配落库 → 订单回写（CHK-SCHED-010；唯一碰 DB 的排产模块）。

- 单事务提交：ScheduleBatch + ScheduleAllocation×N + orders 回写一并 commit；
- batch_no 规则 `SCH-{YYYYMMDD}-{序号:03d}`（序号=同前缀最大+1，天然单调）；
- D12：该单 manual 工序行（depends_on_id → 前道 seq）经 merge_manual_bars 并入甘特参与排产；
  分配行按 manual 行顺序（seq 升序）与手工条一一关联 operation_id；
- 分配行：每条 step 条（不含 setup 条）按日拆分：busy_days 逐日一条，
  qty=amt/busy_days（amt=op_work 工作量）；自动条 operation_id 按 (order_id, seq) 关联工序需求；
  同资源逐日按 bars 顺序 append（执行层 FIFO）。
- 本函数不同步工序需求（调用方按需先行 sync_order_operations；手工行/自动行均从库读）。
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mps import Order, OrderOperation, ScheduleAllocation, ScheduleBatch
from app.mps.context import load_ctx
from app.mps.dates import add_days, to_date
from app.mps.kernel import calc_order, nz
from app.mps.operations import merge_manual_bars
from app.mps.schedule import op_work
from app.mps.solver import solve


def order_to_dict(o: Order) -> dict:
    """DB 订单 → 内核输入 dict（calc_order/gate/回写消费）。"""
    return {
        "id": o.id, "order_no": o.order_no, "product": o.product, "code": o.code,
        "order_type": o.order_type, "first_flag": o.first_flag, "water_vapor": o.water_vapor,
        "qty": o.qty, "due_date": o.due_date, "kit_date": o.kit_date, "priority": o.priority,
        "features": o.features or {}, "remark": o.remark, "status": o.status,
        "prio_level": o.prio_level, "prio_score": o.prio_score, "prio_source": o.prio_source,
        "prio_manual": o.prio_manual, "pinned": o.pinned, "pinned_at": o.pinned_at,
        "sort_no": o.sort_no,
    }


async def run_schedule(session: AsyncSession, base_date, opts=None) -> dict:
    """载入正常工单 → 求解 → 落库批次/分配并回写订单；返回批次摘要。"""
    opts = dict(opts or {})
    ctx = await load_ctx(session)
    orders = (await session.execute(
        select(Order).where(Order.status == "正常").order_by(Order.order_no))).scalars().all()
    if not orders:
        raise ValueError("无待排工单（orders.status='正常' 为空）")
    results = [calc_order(order_to_dict(o), ctx) for o in orders]

    op_rows = (await session.execute(
        select(OrderOperation).where(OrderOperation.order_id.in_([o.id for o in orders]))
        .order_by(OrderOperation.order_id, OrderOperation.seq))).scalars().all()
    seq_by_id = {row.id: row.seq for row in op_rows}
    ops_by_order: dict = {}
    manual_rows_by_order: dict = {}
    for row in op_rows:
        ops_by_order.setdefault(row.order_id, {})[row.seq] = row.id
        if row.source == "manual":
            manual_rows_by_order.setdefault(row.order_id, []).append(row)
    for o, r in zip(orders, results):                        # D12：手工追加工序并入甘特参与排产
        mrows = manual_rows_by_order.get(o.id, [])
        if mrows:
            merge_manual_bars(r, [{"after_seq": seq_by_id.get(m.depends_on_id), "level": m.level,
                                   "op": m.op, "mode": m.mode, "usage": m.feature_usage}
                                  for m in mrows], ctx)

    out = solve(results, ctx, {**opts, "base_date": base_date})
    planned = out["schedule"]

    prefix = f"SCH-{to_date(base_date).strftime('%Y%m%d')}-"
    last = (await session.execute(
        select(ScheduleBatch.batch_no).where(ScheduleBatch.batch_no.like(prefix + "%"))
        .order_by(ScheduleBatch.batch_no.desc()).limit(1))).scalar()
    seq_no = int(last.rsplit("-", 1)[1]) + 1 if last else 1
    batch_no = f"{prefix}{seq_no:03d}"
    batch = ScheduleBatch(
        batch_no=batch_no, base_date=to_date(base_date), solver_mode=out["solver"]["mode"],
        strategy_id=out["strategy"]["id"], params_snapshot=ctx["params"], kpi=out["metrics"])
    session.add(batch)
    await session.flush()

    by_no = {o.order_no: o for o in orders}
    alloc_rows = 0
    for r in planned:
        o = by_no[r["order"]["order_no"]]
        op_ids = ops_by_order.get(o.id, {})
        mrows = manual_rows_by_order.get(o.id, [])
        manual_bars = [b for b in r["gantt"]["bars"] if b.get("manual")]
        manual_ids = [m.id for m in mrows] if len(manual_bars) == len(mrows) else []
        m_at = 0
        for bar in r["gantt"]["bars"]:
            if bar.get("kind") != "step":
                continue
            if bar.get("manual"):
                op_id = manual_ids[m_at] if m_at < len(manual_ids) else None
                m_at += 1
            else:
                seq_val = bar.get("seq")
                op_id = op_ids.get(seq_val) if isinstance(seq_val, int) else None
            res = bar.get("res")
            busy = int(nz(bar.get("busy_days"), 0))
            if not res or busy <= 0 or not bar.get("from"):
                continue
            w = op_work(r, bar)
            if not w:
                continue
            per_day = w["amt"] / busy
            for i in range(busy):
                session.add(ScheduleAllocation(
                    batch_id=batch.id, order_id=o.id, operation_id=op_id, resource_key=res,
                    work_date=to_date(add_days(bar["from"], i)), qty=per_day))
                alloc_rows += 1

    for r in planned:
        o = by_no[r["order"]["order_no"]]
        bn = r.get("bottleneck") or {}
        plan = r["plan"]
        o.input_qty = r["input_qty"]
        o.yield_ratio = r["ratio"]["used"]
        o.y_full = r["yield"]["full"]
        o.cycle_single = r["cycle"]["used"]
        o.cycle_batch = r["batch"]["batch_cycle"]
        o.adopted_flux = bn.get("throughput")
        o.bottleneck_op = bn.get("step_std")
        o.ramp_applied = int(r["ramp"]["used"])
        o.delivery_cycle = r["delivery"]["days"]
        o.latest_start_date = to_date(r["delivery"]["latest_start_date"])
        o.plan_start_date = to_date(plan["start_date"])
        o.plan_finish_date = to_date(plan["finish_date"])
        o.gap_days = plan["gap_days"]
        o.judge = plan["judge"]
        o.strategy_id = plan["strategy_id"]
    await session.commit()
    return {"batch_id": batch.id, "batch_no": batch_no, "base_date": base_date,
            "solver_mode": out["solver"]["mode"], "strategy_id": out["strategy"]["id"],
            "kpi": out["metrics"], "solver": out["solver"], "order_count": len(planned),
            "allocation_rows": alloc_rows, "warnings": out["warnings"]}
