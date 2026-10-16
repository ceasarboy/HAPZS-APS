"""工序级需求：分解/手工追加/手工条合并与排产集成（SCHED-006）。"""
import pytest
from sqlalchemy import select

from app.models.mps import Order, OrderOperation
from app.mps.kernel import calc_order
from app.mps.operations import add_manual_operation, decompose, merge_manual_bars, sync_order_operations
from app.mps.schedule import schedule_process_constrained


def _calc_pair():
    from tests.mps.test_mps_schedule import _ctx_min  # 复用最小 ctx

    o = {"order_no": "A", "product": "P", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
         "water_vapor": "有", "qty": 1000, "features": {"N_die": 60, "N_wire": 60}}
    return calc_order(o, _ctx_min()), _ctx_min()


def test_decompose_from_steps():
    r, _ = _calc_pair()
    rows = decompose(r)
    assert [x["seq"] for x in rows] == [1, 2]
    assert rows[0]["op"] == "DB" and rows[0]["mode"] == "自动DB"
    assert rows[0]["qty"] == 1052 and rows[0]["feature_key"] == "N_die"
    assert rows[1]["depends_on_seq"] == 1 and rows[0]["depends_on_seq"] is None
    assert all(x["source"] == "auto" for x in rows)


def test_merge_manual_bars_after_seq():
    r, ctx = _calc_pair()
    ops = [{"after_seq": 1, "level": "模块级", "op": "调试", "mode": None, "usage": 1}]
    merged = merge_manual_bars(r, ops, ctx)
    mb = merged[-1]
    assert mb["manual"] is True and mb["level"] == "模块级"
    assert mb["earliest_start"] == 0               # 前道条（DB, seq=1）earliest_start=0
    assert mb["seq"] == 1.5                        # 排序保持在前道条之后
    assert mb["flux"] == 10000 and mb["mode"] == "/"


async def test_sched_006_rework_extra_operation(sqlite_session):
    r, ctx = _calc_pair()
    merged = merge_manual_bars(r, [{"after_seq": 1, "level": "模块级", "op": "调试", "mode": None, "usage": 1}], ctx)
    out = schedule_process_constrained([r], "2026-06-01", {})
    bars = [b for b in out["planned"][0]["gantt"]["bars"] if b.get("kind") == "step"]
    manual_bar = next(b for b in bars if b.get("manual"))
    assert manual_bar["res"] == "模块级|调试|/"     # 参与资源占用
    assert "模块级|调试|/" in out["ledger"]         # 占用产能账本
    assert out["capViolations"] == []


async def test_sync_and_manual_persistence(sqlite_session):
    r, ctx = _calc_pair()
    o = Order(order_no="O-1", product="P", code="M02-2D", qty=1000, features={"N_die": 60, "N_wire": 60})
    sqlite_session.add(o)
    await sqlite_session.commit()
    n = await sync_order_operations(sqlite_session, o.id, r)
    assert n == 2
    await add_manual_operation(sqlite_session, o.id, level="模块级", op="调试", mode=None,
                               qty=1052, usage=1, after_seq=1, note="返工调试")
    rows = (await sqlite_session.execute(select(OrderOperation).order_by(OrderOperation.seq))).scalars().all()
    assert [(x.seq, x.source) for x in rows] == [(1, "auto"), (2, "auto"), (3, "manual")]
    assert rows[2].depends_on_id == rows[0].id     # 挂在 seq=1 之后（自动行）
    n2 = await sync_order_operations(sqlite_session, o.id, r)   # 重同步：auto 重建、manual 保留
    assert n2 == 2
    rows2 = (await sqlite_session.execute(select(OrderOperation).order_by(OrderOperation.seq))).scalars().all()
    assert [x.source for x in rows2].count("manual") == 1
