"""旧业务数据清理：dry-run 不删、execute 删除、计数正确。"""
from sqlalchemy import func, select

from app.models.mps import Order
from app.mps.maintenance import clean_tables


async def test_clean_dry_run_keeps_rows(sqlite_session):
    sqlite_session.add(Order(order_no="C-1", product="P", code="M02-2D", qty=1))
    await sqlite_session.commit()
    counts = await clean_tables(sqlite_session, tables=["orders"], execute=False)
    assert counts == {"orders": 1}
    assert (await sqlite_session.execute(select(func.count()).select_from(Order))).scalar() == 1


async def test_clean_execute_deletes_rows(sqlite_session):
    sqlite_session.add(Order(order_no="C-2", product="P", code="M02-2D", qty=1))
    await sqlite_session.commit()
    counts = await clean_tables(sqlite_session, tables=["orders"], execute=True)
    assert counts == {"orders": 1}
    assert (await sqlite_session.execute(select(func.count()).select_from(Order))).scalar() == 0
