"""优先级持久化服务（对应 mps-web server.js 编排职责；异步 SQLAlchemy）。

- 置顶/解除/到期：写 Order 字段 + PriorityLog 审计（PRIO-005/007）
- 拖拽落位：调用 priority.reorder_target 计算并落库
- 批量快照：PriorityBatch.snapshot 保存变更前状态，支持整体撤销（PRIO-008）
"""
from datetime import date, datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mps import Order, PriorityBatch, PriorityLog
from app.mps import priority as prio


def _now():
    return datetime.now()


async def write_log(session: AsyncSession, **row) -> PriorityLog:
    """独立日志写入（自带 commit；勿用于批处理循环——批量场景用各业务函数的内部记日志）。"""
    log = PriorityLog(**row)
    session.add(log)
    await session.commit()
    return log


async def pin_orders(session: AsyncSession, ids: list[str], until=None, operator: str = "") -> list[dict]:
    """置顶：priority=0、P0、source=pin；非"正常"状态拒绝。"""
    out = []
    until_d = None
    if until:
        until_d = date.fromisoformat(str(until)[:10])
    for oid in ids:
        o = (await session.execute(select(Order).where(Order.id == oid))).scalar_one_or_none()
        if not o:
            out.append({"id": oid, "ok": False, "reason": "工单不存在"})
            continue
        if (o.status or "正常") != "正常":
            out.append({"id": oid, "order_no": o.order_no, "ok": False,
                        "reason": f"{o.status or '非正常'}状态工单不可置顶"})
            continue
        old_priority, old_level = o.priority, o.prio_level
        o.pinned = True
        o.pinned_at = _now()
        o.pinned_until = until_d
        o.pinned_by = operator or ""
        o.priority = prio.PINNED_PRIORITY
        o.prio_level = "P0"
        o.prio_source = "pin"
        o.prio_updated_at = _now()
        o.prio_updated_by = operator or ""
        session.add(PriorityLog(
            order_id=oid, order_no=o.order_no, action="pin",
            old_priority=old_priority, new_priority=prio.PINNED_PRIORITY,
            old_level=old_level, new_level="P0",
            reason=f"临时置顶至 {until}" if until else "长期置顶", operator=operator or "",
        ))
        out.append({"id": oid, "order_no": o.order_no, "ok": True, "old_priority": old_priority})
    await session.commit()
    return out


async def unpin_orders(session: AsyncSession, ids: list[str], operator: str = "") -> list[dict]:
    """取消置顶（priority 由调用方重算恢复）。"""
    out = []
    for oid in ids:
        o = (await session.execute(select(Order).where(Order.id == oid))).scalar_one_or_none()
        if not o:
            out.append({"id": oid, "ok": False, "reason": "工单不存在"})
            continue
        old_priority, old_level = o.priority, o.prio_level
        o.pinned = False
        o.pinned_until = None
        o.pinned_at = None
        o.prio_source = "auto"
        o.prio_updated_at = _now()
        o.prio_updated_by = operator or ""
        session.add(PriorityLog(
            order_id=oid, order_no=o.order_no, action="unpin",
            old_priority=old_priority, old_level=old_level,
            reason="手动取消置顶", operator=operator or "",
        ))
        out.append({"id": oid, "order_no": o.order_no, "ok": True, "old_priority": old_priority})
    await session.commit()
    return out


async def expire_pins(session: AsyncSession, today=None) -> list[dict]:
    """置顶到期惰性解除：pinned=1 且 pinned_until < today → 解除并记日志。"""
    t = date.fromisoformat(str(today)[:10]) if today else date.today()
    rows = (await session.execute(
        select(Order).where(Order.pinned.is_(True), Order.pinned_until.is_not(None), Order.pinned_until < t)
    )).scalars().all()
    for o in rows:
        o.pinned = False
        o.pinned_until = None
        o.pinned_at = None
        o.prio_source = "auto"
        o.prio_updated_at = _now()
        session.add(PriorityLog(
            order_id=o.id, order_no=o.order_no, action="unpin",
            old_priority=o.priority, old_level=o.prio_level,
            reason=f"置顶到期自动解除（有效期至 {t} 之前）", operator="system",
        ))
    if rows:
        await session.commit()
    return [{"id": o.id, "order_no": o.order_no} for o in rows]


async def reorder_and_log(session: AsyncSession, order_id: str, prev_id=None, next_id=None,
                          to_pinned: bool = False, operator: str = "") -> dict:
    """拖拽落位并落库（只改被拖动的一条）。非"正常"状态工单拒绝（对齐 mps-web server.js）。"""
    o = (await session.execute(select(Order).where(Order.id == order_id))).scalar_one_or_none()
    if not o:
        return {"ok": False, "reason": "工单不存在"}
    if (o.status or "正常") != "正常":
        return {"ok": False, "reason": f"{o.status or '非正常'}状态工单不可拖拽"}
    prev = (await session.execute(select(Order).where(Order.id == prev_id))).scalar_one_or_none() if prev_id else None
    nxt = (await session.execute(select(Order).where(Order.id == next_id))).scalar_one_or_none() if next_id else None

    def _d(x):
        if x is None:
            return None
        return {"priority": x.priority, "sort_no": x.sort_no, "pinned": x.pinned, "id": x.id}

    target = prio.reorder_target(_d(o), _d(prev), _d(nxt), to_pinned)
    old_priority, old_level, old_sort_no = o.priority, o.prio_level, o.sort_no
    o.pinned = bool(target["pinned"])
    o.priority = target["priority"]
    o.sort_no = target["sort_no"]
    o.prio_level = target["level"]
    o.prio_source = target["source"]
    o.prio_updated_at = _now()
    o.prio_updated_by = operator or ""
    if target["pinned"]:
        o.pinned_at = o.pinned_at or _now()
    else:
        o.pinned_at = None
        o.pinned_until = None
        o.prio_manual = target["priority"]          # 拖入普通组即计划员显式排序（对齐 server.js）
    session.add(PriorityLog(
        order_id=order_id, order_no=o.order_no, action="reorder",
        old_priority=old_priority, new_priority=o.priority,
        old_level=old_level, new_level=o.prio_level,
        old_sort_no=old_sort_no, new_sort_no=o.sort_no,
        reason="拖拽排序", operator=operator or "",
    ))
    await session.commit()
    return {"ok": True, "target": target}


_SNAPSHOT_FIELDS = ("priority", "prio_level", "prio_source", "prio_manual", "prio_score",
                    "sort_no", "pinned", "pinned_at", "pinned_until", "pinned_by")


def _ser(v):
    return v.isoformat() if isinstance(v, (date, datetime)) else v


async def create_batch(session: AsyncSession, action: str, orders: list[Order], operator: str = "") -> PriorityBatch:
    """记录批量操作快照（撤销用）。"""
    snapshot = {str(o.id): {f: _ser(getattr(o, f)) for f in _SNAPSHOT_FIELDS} for o in orders}
    batch = PriorityBatch(batch_id=uuid.uuid4().hex, action=action,
                          item_count=len(orders), snapshot=snapshot, operator=operator or "")
    session.add(batch)
    await session.commit()
    return batch


async def undo_batch(session: AsyncSession, batch_id: str, operator: str = "system") -> int:
    """撤销批量操作：按快照恢复字段并记日志（日志 batch_id=batch.batch_id；undo_of 列未用）。"""
    batch = (await session.execute(select(PriorityBatch).where(PriorityBatch.batch_id == batch_id))).scalar_one_or_none()
    if not batch or batch.undone or not batch.snapshot:
        return 0
    restored = 0
    for oid, snap in batch.snapshot.items():
        o = (await session.execute(select(Order).where(Order.id == oid))).scalar_one_or_none()
        if not o:
            continue
        old_priority, old_level = o.priority, o.prio_level
        for f, v in snap.items():
            if f in ("pinned_at", "pinned_until") and isinstance(v, str) and v:
                v = datetime.fromisoformat(v) if f == "pinned_at" else date.fromisoformat(v)
            setattr(o, f, v)
        o.prio_updated_at = _now()
        o.prio_updated_by = operator
        session.add(PriorityLog(
            order_id=oid, order_no=o.order_no, action="undo",
            old_priority=old_priority, new_priority=o.priority,
            old_level=old_level, new_level=o.prio_level,
            reason=f"撤销批量{batch.action}", operator=operator, batch_id=batch.batch_id,
        ))
        restored += 1
    batch.undone = True
    await session.commit()
    return restored
