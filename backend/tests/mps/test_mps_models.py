"""MPS 新模型：建表、约束与字段冒烟测试。"""
import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from app.models.mps import (
    HapFieldMapping, HapMapping, Order, OrderOperation, ProcessMaster,
    ProcessRoute, ProcessSet, SystemParam,
)

EXPECTED_TABLES = {
    "process_masters", "process_sets", "process_routes", "orders", "order_operations",
    "system_params", "schedule_batches", "schedule_allocations",
    "priority_logs", "priority_batches",
    "hap_connections", "hap_mappings", "hap_field_mappings",
}


async def test_mps_tables_created(sqlite_engine):
    async with sqlite_engine.connect() as conn:
        names = await conn.run_sync(lambda c: inspect(c).get_table_names())
    assert EXPECTED_TABLES.issubset(set(names))


async def test_order_no_unique(sqlite_session):
    sqlite_session.add(Order(order_no="T-1", product="模块-01", code="M02-2D", qty=10))
    await sqlite_session.commit()
    sqlite_session.add(Order(order_no="T-1", product="模块-01", code="M02-2D", qty=10))
    with pytest.raises(IntegrityError):
        await sqlite_session.commit()
    await sqlite_session.rollback()


async def test_process_route_unique_code_seq(sqlite_session):
    sqlite_session.add(ProcessRoute(code="X-1", seq=1, step_raw="DB", step_std="DB", level="模块级"))
    await sqlite_session.commit()
    sqlite_session.add(ProcessRoute(code="X-1", seq=1, step_raw="DB", step_std="DB", level="模块级"))
    with pytest.raises(IntegrityError):
        await sqlite_session.commit()
    await sqlite_session.rollback()


async def test_order_features_json_roundtrip(sqlite_session):
    sqlite_session.add(
        Order(order_no="T-2", product="模块-02", code="M02-2D", qty=5,
              features={"N_die": 60, "N_wire": 60, "Y_die": 2}, kit_date=None)
    )
    await sqlite_session.commit()
    row = (await sqlite_session.execute(select(Order).where(Order.order_no == "T-2"))).scalar_one()
    assert row.features["N_die"] == 60


async def test_process_master_unique_triple(sqlite_session):
    sqlite_session.add(ProcessMaster(level="模块级", op="DB", mode="自动DB"))
    await sqlite_session.commit()
    sqlite_session.add(ProcessMaster(level="模块级", op="DB", mode="自动DB"))
    with pytest.raises(IntegrityError):
        await sqlite_session.commit()
    await sqlite_session.rollback()


async def test_system_param_key_unique(sqlite_session):
    sqlite_session.add(SystemParam(key="week_days", value="6"))
    await sqlite_session.commit()
    sqlite_session.add(SystemParam(key="week_days", value="5"))
    with pytest.raises(IntegrityError):
        await sqlite_session.commit()
    await sqlite_session.rollback()
