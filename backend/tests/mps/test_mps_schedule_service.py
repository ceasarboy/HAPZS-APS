"""排产服务：批次/每日分配落库与订单回写（CHK-SCHED-010）。"""
from datetime import date

import pytest
from sqlalchemy import func, select

from app.models.mps import Order, ScheduleAllocation, ScheduleBatch
from app.mps.context import load_ctx
from app.mps.kernel import calc_order
from app.mps.operations import add_manual_operation, sync_order_operations
from app.mps.schedule_service import order_to_dict, run_schedule
from app.seed.loader import load_mps_seed


def _mk_order(no, qty, prio=100, due=None):
    return Order(order_no=no, product="P-" + no, code="M02-2D", order_type="常规", first_flag="否",
                 water_vapor="有", qty=qty, due_date=due, kit_date=date(2026, 6, 1), priority=prio,
                 features={"N_die": 60, "N_wire": 60})


async def _seed_orders(session):
    await load_mps_seed(session)
    a = _mk_order("WO-A", 1000, 100, date(2026, 9, 30))
    b = _mk_order("WO-B", 5, 50)
    session.add_all([a, b])
    await session.commit()
    ctx = await load_ctx(session)
    for o in (a, b):                                    # 预同步工序需求 → 分配行可关联 operation_id
        await sync_order_operations(session, o.id, calc_order(order_to_dict(o), ctx))
    return a, b


async def test_chk_sched_010_batch_result_persistence(sqlite_session):
    a, b = await _seed_orders(sqlite_session)
    r1 = await run_schedule(sqlite_session, "2026-06-01",
                            {"mode": "deterministic", "strategy": "priority"})
    assert r1["batch_no"] == "SCH-20260601-001"
    assert r1["solver_mode"] == "deterministic" and r1["strategy_id"] == "priority"
    assert r1["order_count"] == 2 and r1["allocation_rows"] == 32 and r1["warnings"] == []
    assert r1["kpi"] == {"tardiness": 0, "maxLate": 0, "setupTotal": 0.0, "onTime": 1, "lateN": 0,
                         "imbalance": pytest.approx(0.5653581678004794), "makespan": 26, "overloadWC": 1}

    batch = (await sqlite_session.execute(select(ScheduleBatch))).scalar_one()
    assert batch.batch_no == "SCH-20260601-001" and batch.base_date == date(2026, 6, 1)
    assert batch.solver_mode == "deterministic" and batch.strategy_id == "priority"
    assert batch.params_snapshot["week_days"] == 6.0 and batch.status == "完成"
    assert batch.kpi["makespan"] == 26

    total = (await sqlite_session.execute(select(func.count()).select_from(ScheduleAllocation))).scalar()
    assert total == 32
    a_rows = (await sqlite_session.execute(
        select(ScheduleAllocation).where(ScheduleAllocation.order_id == a.id))).scalars().all()
    assert len(a_rows) == 27 and all(x.operation_id is not None for x in a_rows)
    sums = {}
    for x in a_rows:
        sums[x.resource_key] = sums.get(x.resource_key, 0.0) + x.qty
    assert sums["模块级|DB|自动DB"] == pytest.approx(1052 * 60)
    assert sums["模块级|WB|自动WB"] == pytest.approx(1052 * 60)
    assert sums["模块级|调试|/"] == pytest.approx(1052)
    assert sums["模块级|终检|/"] == pytest.approx(1052)
    assert sums["模块级|封盖|/"] == pytest.approx(1052)
    db_day1 = [x for x in a_rows if x.resource_key == "模块级|DB|自动DB"
               and x.work_date == date(2026, 6, 1)]
    assert len(db_day1) == 1 and db_day1[0].qty == pytest.approx(63120 / 11)

    await sqlite_session.refresh(a)
    await sqlite_session.refresh(b)
    assert a.input_qty == 1052 and a.yield_ratio == pytest.approx(1.0518332845401022)
    assert a.y_full == pytest.approx(0.9507210074999999)
    assert a.cycle_single == 6.0 and a.cycle_batch == 16.0
    assert a.adopted_flux == 100.0 and a.bottleneck_op == "DB" and a.ramp_applied == 0
    assert a.delivery_cycle == 17.0 and a.latest_start_date == date(2026, 9, 13)
    assert a.plan_start_date == date(2026, 6, 1) and a.plan_finish_date == date(2026, 6, 27)
    assert a.gap_days == 104 and a.judge == "满足" and a.strategy_id == "priority"
    assert b.input_qty == 6 and b.latest_start_date is None
    assert b.plan_start_date == date(2026, 6, 1) and b.plan_finish_date == date(2026, 6, 5)
    assert b.gap_days is None and b.judge == "无交期"

    r2 = await run_schedule(sqlite_session, "2026-06-01",
                            {"population": 4, "generations": 1, "seed": 42})
    assert r2["batch_no"] == "SCH-20260601-002" and r2["solver_mode"] == "ga"
    assert r2["allocation_rows"] == 32
    n = (await sqlite_session.execute(select(func.count()).select_from(ScheduleBatch))).scalar()
    assert n == 2


async def test_run_schedule_manual_operation_participates(sqlite_session):
    """D12：手工追加工序经服务端并入排产，分配行关联到手工工序行（探针实测）。"""
    a, b = await _seed_orders(sqlite_session)
    manual = await add_manual_operation(sqlite_session, a.id, level="模块级", op="调试", mode=None,
                                        qty=1052, usage=1, after_seq=5, note="返工调试")
    r = await run_schedule(sqlite_session, "2026-06-01", {"mode": "deterministic"})
    assert r["allocation_rows"] == 37                        # 32 自动 + 5（手工条 1052/250=5 天）
    a_rows = (await sqlite_session.execute(
        select(ScheduleAllocation).where(ScheduleAllocation.order_id == a.id))).scalars().all()
    m_rows = sorted([x for x in a_rows if x.operation_id == manual.id], key=lambda x: x.work_date)
    assert len(m_rows) == 5
    assert m_rows[0].work_date == date(2026, 6, 28) and m_rows[0].resource_key == "模块级|调试|/"
    assert all(x.qty == pytest.approx(1052 / 5) for x in m_rows)
    sums = {}
    for x in a_rows:
        sums[x.resource_key] = sums.get(x.resource_key, 0.0) + x.qty
    assert sums["模块级|调试|/"] == pytest.approx(2104)       # 自动 1052 + 手工 1052


async def test_run_schedule_requires_orders(sqlite_session):
    await load_mps_seed(sqlite_session)
    with pytest.raises(ValueError) as ei:
        await run_schedule(sqlite_session, "2026-06-01", {"mode": "deterministic"})
    assert str(ei.value) == "无待排工单（orders.status='正常' 为空）"
