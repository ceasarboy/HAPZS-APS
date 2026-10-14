"""旧业务数据清理：dry-run 不删、execute 删除、计数正确。"""
from sqlalchemy import func, select

from app.models.mps import Order
from app.mps.maintenance import OLD_BUSINESS_TABLES, clean_tables


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


async def test_empty_tables_argument_deletes_nothing(sqlite_session):
    sqlite_session.add(Order(order_no="C-3", product="P", code="M02-2D", qty=1))
    await sqlite_session.commit()
    counts = await clean_tables(sqlite_session, tables=[], execute=True)
    assert counts == {}
    assert (await sqlite_session.execute(select(func.count()).select_from(Order))).scalar() == 1


def test_old_business_tables_order_respects_fk():
    """删除顺序：任一表的 FK 父表都不得排在该表之前（子表在前，父表在后）。"""
    from app.database import Base
    import app.models  # noqa: F401

    order = {name: i for i, name in enumerate(OLD_BUSINESS_TABLES)}
    for name in OLD_BUSINESS_TABLES:
        table = Base.metadata.tables[name]
        for fk in table.foreign_keys:
            parent = fk.column.table.name
            if parent in order:
                assert order[parent] > order[name], f"{name} 依赖 {parent}，父表必须排在后面"


def test_old_business_tables_all_registered():
    from app.database import Base
    import app.models  # noqa: F401

    assert set(OLD_BUSINESS_TABLES).issubset(Base.metadata.tables.keys())
