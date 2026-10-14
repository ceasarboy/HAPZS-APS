"""种子导入：行数、抽查值、幂等性与参数保护。"""
from sqlalchemy import func, select

from app.models.mps import Order, ProcessMaster, ProcessRoute, ProcessSet, SystemParam
from app.mps.consts import PARAM_DEFS
from app.seed.loader import load_mps_seed


async def test_seed_counts(sqlite_session):
    counts = await load_mps_seed(sqlite_session)
    assert counts["workcenters"] == 28
    assert counts["processes"] == 24
    assert counts["routes"] == 133
    assert counts["params_added"] == len(PARAM_DEFS)
    assert (await sqlite_session.execute(select(func.count()).select_from(ProcessMaster))).scalar() == 28
    assert (await sqlite_session.execute(select(func.count()).select_from(ProcessSet))).scalar() == 24
    assert (await sqlite_session.execute(select(func.count()).select_from(ProcessRoute))).scalar() == 133


async def test_seed_spot_values(sqlite_session):
    await load_mps_seed(sqlite_session)
    wc = (await sqlite_session.execute(
        select(ProcessMaster).where(
            ProcessMaster.level == "模块级", ProcessMaster.op == "DB", ProcessMaster.mode == "自动DB")
    )).scalar_one()
    assert wc.flux_base == 6000 and wc.flux_peak == 6600 and wc.split_threshold == 20

    ps = (await sqlite_session.execute(select(ProcessSet).where(ProcessSet.code == "M02-2D"))).scalar_one()
    assert ps.cycle_ref == 6 and ps.urgent_ref == 4
    assert abs(ps.yield_ref - 0.9507210075) < 1e-9
    assert ps.route_text == "DB1-WB1-调试1-封盖前终检1-封盖2"

    r5 = (await sqlite_session.execute(
        select(ProcessRoute).where(ProcessRoute.code == "M02-2D", ProcessRoute.seq == 5)
    )).scalar_one()
    assert r5.step_std == "封盖" and r5.cycle == 2


async def test_seed_idempotent_and_params_preserved(sqlite_session):
    await load_mps_seed(sqlite_session)
    param = (await sqlite_session.execute(select(SystemParam).where(SystemParam.key == "week_days"))).scalar_one()
    param.value = "5"
    await sqlite_session.commit()

    await load_mps_seed(sqlite_session)
    assert (await sqlite_session.execute(select(func.count()).select_from(ProcessMaster))).scalar() == 28
    param2 = (await sqlite_session.execute(select(SystemParam).where(SystemParam.key == "week_days"))).scalar_one()
    assert param2.value == "5"


async def test_seed_demo_orders_once(sqlite_session):
    counts = await load_mps_seed(sqlite_session, with_demo_orders=True)
    assert counts["demo_orders"] == 20
    counts2 = await load_mps_seed(sqlite_session, with_demo_orders=True)
    assert counts2["demo_orders"] == 0
    assert (await sqlite_session.execute(select(func.count()).select_from(Order))).scalar() == 20


async def test_seed_params_fallback_defaults(sqlite_session):
    """转换后的种子只覆盖部分参数；其余参数按 PARAM_DEFS 默认值落库。"""
    await load_mps_seed(sqlite_session)
    p = (await sqlite_session.execute(select(SystemParam).where(SystemParam.key == "order_buffer_days"))).scalar_one()
    assert p.value == "1"
    p2 = (await sqlite_session.execute(select(SystemParam).where(SystemParam.key == "peak_factor"))).scalar_one()
    assert p2.value == "1.1"


async def test_all_route_features_resolvable(sqlite_session):
    """种子加载后，全部路线核算特征均可被 FEATURE_MAP 解析（防静默缺参）。"""
    from app.mps.consts import FEATURE_MAP

    await load_mps_seed(sqlite_session)
    features = (await sqlite_session.execute(
        select(ProcessRoute.feature).distinct()
    )).scalars().all()
    assert features, "种子应包含路线特征"
    for f in features:
        assert f in FEATURE_MAP, f"路线特征未被 FEATURE_MAP 覆盖: {f}"
