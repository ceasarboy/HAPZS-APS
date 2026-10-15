"""疑点双档：FLUX-015A/B（模块级 WB 自动通量 12000/20000，参数 wb_auto_flux_override）。

其余双档覆盖位置：
- DELIVERY-003A/B（取整）→ test_kernel_calc.py::test_chk_delivery_003_round_mode_variants
- DELIVERY-005A/B（缓冲）→ test_kernel_calc.py::test_chk_delivery_004_005_buffer_variants
- CYCLE-009A/B（爬坡触发）→ test_kernel_calc.py::test_chk_cycle_006_007_ramp / test_chk_cycle_009_ramp_trigger_variants /
  test_chk_cycle_009b_first_only_trigger
"""
import pytest

from app.mps.kernel import calc_order
from app.mps.load import weekly_load

P_BASE = {
    "week_days": 6, "peak_factor": 1.1, "use_peak": "mean",
    "exclude_braze_yield": 1,
    "cf_db_1": 1, "cf_db_2": 0.9, "cf_db_3": 0.8,
    "cf_wb_1": 1, "cf_wb_2": 0.95, "cf_wb_3": 0.9,
    "vapor_cap_cut": 1, "order_buffer_days": 1, "reference_batch": 1000,
    "round_mode": "ceil", "ramp_trigger": "first_flag", "wb_auto_flux_override": 0,
}


def _ctx_min():
    # 复制自 test_kernel_calc 的最小构造，有意独立（P_BASE 为显式契约，防止联环演化）
    proc = {"code": "M02-2D", "name": "不含SMT二维模块成套工艺", "ramp_days": 1,
            "subpart_mode": None, "subpart_cycle": 0}
    routes = [
        {"code": "M02-2D", "seq": 1, "step_raw": "DB", "step_std": "DB", "level": "模块级",
         "cycle": 1, "yield_overall": 0.97, "feature": "DB-芯片数N_die", "cf_field": "DB胶水类型Y_die"},
        {"code": "M02-2D", "seq": 2, "step_raw": "WB", "step_std": "WB", "level": "模块级",
         "cycle": 1, "yield_overall": 0.99, "feature": "WB-键合线数N_wire", "cf_field": "WB引线类型Y_wire"},
    ]
    wc_map = {
        "模块级|DB": {"modes": [
            {"mode": "半自动DB", "flux_base": 2000, "flux_peak": 2200, "split_threshold": 20, "unit": "只芯片/天"},
            {"mode": "自动DB", "flux_base": 6000, "flux_peak": 6600, "split_threshold": 20, "unit": "只芯片/天"},
        ]},
        "模块级|WB": {"modes": [
            {"mode": "半自动WB", "flux_base": 4500, "flux_peak": 4950, "split_threshold": 20, "unit": "根丝/天"},
            {"mode": "自动WB", "flux_base": 12000, "flux_peak": 13200, "split_threshold": 20, "unit": "根丝/天"},
        ]},
    }
    return {"proc_map": {"M02-2D": proc}, "route_map": {"M02-2D": routes},
            "wc_map": wc_map, "params": dict(P_BASE)}


def _order():
    return {"order_no": "T", "product": "模块-01", "code": "M02-2D", "order_type": "常规",
            "first_flag": "否", "water_vapor": "有", "qty": 1000, "features": {"N_die": 60, "N_wire": 60}}


def test_chk_flux_015a_wb_auto_12000():
    r = calc_order(_order(), _ctx_min())
    wb = next(s for s in r["steps"] if s["step_std"] == "WB")
    assert wb["mode"] == "自动WB"
    assert wb["flux_base"] == 12000                # 主数据口径（= V1.6 逻辑书口径）
    assert wb["throughput"] == pytest.approx(200.0)  # 12000÷60


def test_chk_flux_015b_wb_auto_20000():
    ctx = _ctx_min()
    ctx["params"]["wb_auto_flux_override"] = 20000
    r = calc_order(_order(), ctx)
    wb = next(s for s in r["steps"] if s["step_std"] == "WB")
    assert wb["flux_base"] == 20000
    assert wb["throughput"] == pytest.approx(20000 / 60)
    rows = {x["key"]: x for x in weekly_load([r], {"params": ctx["params"]})}
    assert rows["模块级|WB|自动WB"]["available"] == pytest.approx(20000 * 6)

    # peak 口径：override 同时替换 mean/peak 取值
    ctx_peak = _ctx_min()
    ctx_peak["params"]["wb_auto_flux_override"] = 20000
    ctx_peak["params"]["use_peak"] = "peak"
    wb_peak = next(s for s in calc_order(_order(), ctx_peak)["steps"] if s["step_std"] == "WB")
    assert wb_peak["flux_base"] == 20000
