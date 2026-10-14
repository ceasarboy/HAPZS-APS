"""上下文装载：种子库 → 内核输入；主数据变更后重算结果联动变化（CHK-CALC-004）。"""
import pytest
from sqlalchemy import select

from app.models.mps import ProcessMaster, SystemParam
from app.mps.context import _NUMERIC_PARAM_KEYS, load_ctx
from app.mps.kernel import calc_order
from app.seed.loader import load_mps_seed


async def test_load_ctx_from_seed(sqlite_session):
    await load_mps_seed(sqlite_session)
    ctx = await load_ctx(sqlite_session)
    assert "M02-2D" in ctx["proc_map"] and len(ctx["route_map"]["M02-2D"]) == 5
    db_modes = {m["mode"]: m for m in ctx["wc_map"]["模块级|DB"]["modes"]}
    assert db_modes["自动DB"]["flux_base"] == 6000
    assert ctx["params"]["week_days"] == 6
    assert ctx["params"]["round_mode"] == "ceil"
    assert ctx["params"]["use_peak"] == "mean"


async def test_calc_with_seeded_data_matches_official(sqlite_session):
    await load_mps_seed(sqlite_session)
    ctx = await load_ctx(sqlite_session)
    order = {"order_no": "W0-000", "product": "模块-01", "code": "M02-2D", "order_type": "常规",
             "first_flag": "否", "water_vapor": "有", "qty": 1000, "due_date": "2026-12-31",
             "features": {"N_die": 60, "N_wire": 60}}
    r = calc_order(order, ctx)
    assert r["input_qty"] == 1052 and r["batch"]["batch_cycle"] == 16 and r["delivery"]["days"] == 17


async def test_chk_calc_004_data_flow_linkage(sqlite_session):
    """主数据修改 → 重装载 → 结果变化（上游改下游刷新）。"""
    await load_mps_seed(sqlite_session)
    ctx1 = await load_ctx(sqlite_session)
    order = {"order_no": "L", "product": "模块-01", "code": "M02-2D", "order_type": "常规",
             "first_flag": "否", "water_vapor": "有", "qty": 1000, "features": {"N_die": 60, "N_wire": 60}}
    t1 = calc_order(order, ctx1)["bottleneck"]["throughput"]

    wc = (await sqlite_session.execute(
        select(ProcessMaster).where(ProcessMaster.level == "模块级", ProcessMaster.op == "DB",
                                    ProcessMaster.mode == "自动DB")
    )).scalar_one()
    wc.flux_base = 3000
    await sqlite_session.commit()

    ctx2 = await load_ctx(sqlite_session)
    t2 = calc_order(order, ctx2)["bottleneck"]["throughput"]
    assert t1 == 100.0 and t2 == pytest.approx(50.0)  # 3000÷60


async def test_load_params_invalid_falls_back_to_default(sqlite_session):
    """非法数值参数回退 PARAM_DEFS 默认（而非静默归 0）。"""
    await load_mps_seed(sqlite_session)
    row = (await sqlite_session.execute(
        select(SystemParam).where(SystemParam.key == "week_days")
    )).scalar_one()
    row.value = "abc"
    await sqlite_session.commit()
    ctx = await load_ctx(sqlite_session)
    assert ctx["params"]["week_days"] == 6


async def test_empty_db_ctx_and_error(sqlite_session):
    ctx = await load_ctx(sqlite_session)
    assert ctx["proc_map"] == {} and ctx["route_map"] == {} and ctx["wc_map"] == {}
    with pytest.raises(ValueError):
        calc_order({"code": "M02-2D", "qty": 1}, ctx)


async def test_small_qty_uses_semi_mode(sqlite_session):
    await load_mps_seed(sqlite_session)
    ctx = await load_ctx(sqlite_session)
    order = {"order_no": "S", "product": "模块-01", "code": "M02-2D", "order_type": "常规",
             "first_flag": "否", "water_vapor": "有", "qty": 5, "features": {"N_die": 60, "N_wire": 60}}
    r = calc_order(order, ctx)
    assert r["steps"][0]["mode"] == "半自动DB"
    assert r["bottleneck"]["throughput"] == pytest.approx(2000 / 60)


def test_numeric_param_keys_subset_of_param_defs():
    from app.mps.consts import PARAM_DEFS

    assert set(_NUMERIC_PARAM_KEYS).issubset({p["key"] for p in PARAM_DEFS})
