"""优先级持久化服务：置顶/到期解除/拖拽/审计日志/批量快照撤销。"""
from datetime import date, timedelta

from sqlalchemy import select

from app.models.mps import Order, PriorityBatch, PriorityLog
from app.mps.priority_service import (
    create_batch, expire_pins, pin_orders, reorder_and_log, undo_batch, unpin_orders,
)


async def _mk_order(session, no, **kw):
    o = Order(order_no=no, product="P", code="M02-2D", qty=10, **kw)
    session.add(o)
    await session.commit()
    return o


async def test_pin_sets_fields_and_logs(sqlite_session):
    o = await _mk_order(sqlite_session, "A-1")
    res = await pin_orders(sqlite_session, [o.id], until="2026-12-31", operator="alice")
    assert res[0]["ok"] is True
    await sqlite_session.refresh(o)
    assert o.pinned is True and o.priority == 0 and o.prio_level == "P0" and o.prio_source == "pin"
    assert o.pinned_until == date(2026, 12, 31) and o.pinned_by == "alice"
    log = (await sqlite_session.execute(select(PriorityLog))).scalars().one()
    assert log.action == "pin" and log.new_priority == 0 and log.operator == "alice"


async def test_pin_rejects_non_normal_status(sqlite_session):
    o = await _mk_order(sqlite_session, "A-2", status="暂停")
    res = await pin_orders(sqlite_session, [o.id], until=None, operator="bob")
    assert res[0]["ok"] is False and "不可置顶" in res[0]["reason"]


async def test_expire_pins_only_past(sqlite_session):
    past = await _mk_order(sqlite_session, "A-3", pinned=True, priority=0, prio_level="P0", prio_source="pin",
                           pinned_until=date.today() - timedelta(days=1))
    future = await _mk_order(sqlite_session, "A-4", pinned=True, priority=0, prio_level="P0", prio_source="pin",
                             pinned_until=date.today() + timedelta(days=5))
    expired = await expire_pins(sqlite_session)
    assert [e["order_no"] for e in expired] == ["A-3"]
    await sqlite_session.refresh(past)
    await sqlite_session.refresh(future)
    assert past.pinned is False and past.pinned_until is None and past.prio_source == "auto"
    assert future.pinned is True


async def test_unpin_and_reorder(sqlite_session):
    o1 = await _mk_order(sqlite_session, "B-1", priority=100)
    o2 = await _mk_order(sqlite_session, "B-2", priority=250, prio_level="P1")
    o3 = await _mk_order(sqlite_session, "B-3", priority=400, prio_level="P2")
    r = await reorder_and_log(sqlite_session, o2.id, o1.id, o3.id, False, operator="carol")
    assert r["ok"] is True
    await sqlite_session.refresh(o2)
    assert o2.priority == 250 and o2.prio_source == "manual"   # (100+400)/2
    logs = (await sqlite_session.execute(select(PriorityLog))).scalars().all()
    assert any(l.action == "reorder" and l.new_priority == 250 for l in logs)

    r2 = await unpin_orders(sqlite_session, [o1.id], operator="carol")
    assert r2[0]["ok"] is True


async def test_batch_snapshot_and_undo(sqlite_session):
    o1 = await _mk_order(sqlite_session, "C-1", priority=150, prio_level="P1")
    o2 = await _mk_order(sqlite_session, "C-2", priority=350, prio_level="P2")
    b = await create_batch(sqlite_session, "recompute", [o1, o2], operator="dave")
    o1.priority, o1.prio_level = 20, "P0"
    o2.priority, o2.prio_level = 90, "P0"
    await sqlite_session.commit()
    n = await undo_batch(sqlite_session, b.batch_id, operator="dave")
    assert n == 2
    await sqlite_session.refresh(o1)
    await sqlite_session.refresh(o2)
    assert o1.priority == 150 and o1.prio_level == "P1"
    assert o2.priority == 350 and o2.prio_level == "P2"
    await sqlite_session.refresh(b)
    assert b.undone is True
    logs = (await sqlite_session.execute(select(PriorityLog))).scalars().all()
    assert any(l.action == "undo" and l.batch_id == b.batch_id for l in logs)
