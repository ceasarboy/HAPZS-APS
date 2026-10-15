"""官方周负荷算例（CHK-CALC-003）：V1.6 §九 完整算例的"同一周"两单组合。

数据复原（调查记录，2026-10-14）：
- V1.6 §九 第一段：M02-2D 1000 只常规（N_die=60、N_wire=60）→ Q=1052；
- 同段末句"同一周另有 M01-2DS 订单 500 只（首单，N_smt=24、N_die=60、N_wire=300）"→ Q=529；
- 复原校核：DB 1052×60+529×60=94860 ✓；WB 1052×60+529×300=221820 ✓；SMT 529×24=12696 ✓；
- 为何必然两单：单 M01-2DS（529×60=31740）无法解释 94860，须叠加 §九 第一段的 M02-2D（1052×60=63120）；
- 为何 Q=529：成品率链 0.995×0.97×0.99×1×0.995×0.995≈0.9459674 → 放量比≈1.0571189 → ⌈500×1.0571189⌉=529；
- 2.64/3.08/0.88 为文档显示值（两位小数）；DB 精确商 2.635，断言容差同时覆盖显示值；
- 可用：DB 6000×6=36000、WB 12000×6=72000（疑点①按 12000 口径）、SMT 2400×6=14400。
"""
import pytest

from app.mps.context import load_ctx
from app.mps.kernel import calc_order
from app.mps.load import weekly_load
from app.seed.loader import load_mps_seed

ORDERS = [
    {"order_no": "案例A", "product": "模块-01", "code": "M02-2D", "order_type": "常规", "first_flag": "否",
     "water_vapor": "有", "qty": 1000, "features": {"N_die": 60, "N_wire": 60}},
    {"order_no": "案例B", "product": "模块-01", "code": "M01-2DS", "order_type": "常规", "first_flag": "首单",
     "water_vapor": "有", "qty": 500, "features": {"N_smt": 24, "N_die": 60, "N_wire": 300}},
]


async def test_chk_calc_003_m01_2ds_weekly_load(sqlite_session):
    await load_mps_seed(sqlite_session)
    ctx = await load_ctx(sqlite_session)
    results = [calc_order(o, ctx) for o in ORDERS]
    assert [r["input_qty"] for r in results] == [1052, 529]

    rows = {r["key"]: r for r in weekly_load(results, {"params": ctx["params"]})}
    db = rows["模块级|DB|自动DB"]
    # load 为整数值双精度累积（各积和 < 2^53），精确相等成立
    assert db["load"] == 94860 and db["available"] == 36000
    assert [(o["order_no"], o["amount"]) for o in db["orders"]] == [("案例A", 63120), ("案例B", 31740)]
    assert db["load_rate"] == pytest.approx(2.635, abs=0.005)
    assert db["judge"] == "超载"

    wb = rows["模块级|WB|自动WB"]
    assert wb["load"] == 221820 and wb["available"] == 72000
    assert [(o["order_no"], o["amount"]) for o in wb["orders"]] == [("案例A", 63120), ("案例B", 158700)]
    assert wb["load_rate"] == pytest.approx(3.08, abs=0.005)
    assert wb["judge"] == "超载"

    smt = rows["模块级|SMT|/"]
    assert smt["load"] == 12696 and smt["available"] == 14400
    assert smt["load_rate"] == pytest.approx(0.88, abs=0.005)
    assert smt["judge"] == "偏紧"
