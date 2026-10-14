"""calc_order 主体：官方算例 M02-2D 与周期/成品率/投料/瓶颈/批量/交付口径。"""
import pytest

from app.mps.kernel import calc_order

P_BASE = {
    "week_days": 6, "peak_factor": 1.1, "use_peak": "mean",
    "exclude_braze_yield": 1,
    "cf_db_1": 1, "cf_db_2": 0.9, "cf_db_3": 0.8,
    "cf_wb_1": 1, "cf_wb_2": 0.95, "cf_wb_3": 0.9,
    "vapor_cap_cut": 1, "order_buffer_days": 1, "reference_batch": 1000,
    "round_mode": "ceil", "ramp_trigger": "first_flag", "wb_auto_flux_override": 0,
}


def _ctx_m02_2d():
    proc = {
        "code": "M02-2D", "name": "不含SMT二维模块成套工艺", "ramp_days": 1,
        "subpart_mode": None, "subpart_cycle": 0,
    }
    routes = [
        {"code": "M02-2D", "seq": 1, "step_raw": "DB", "step_std": "DB", "level": "模块级",
         "cycle": 1, "yield_overall": 0.97, "feature": "DB-芯片数N_die", "cf_field": "DB胶水类型Y_die"},
        {"code": "M02-2D", "seq": 2, "step_raw": "WB", "step_std": "WB", "level": "模块级",
         "cycle": 1, "yield_overall": 0.99, "feature": "WB-键合线数N_wire", "cf_field": "WB引线类型Y_wire"},
        {"code": "M02-2D", "seq": 3, "step_raw": "调试", "step_std": "调试", "level": "模块级",
         "cycle": 1, "yield_overall": 1, "feature": "工单产品数量N", "cf_field": "/"},
        {"code": "M02-2D", "seq": 4, "step_raw": "封盖前终检", "step_std": "终检", "level": "模块级",
         "cycle": 1, "yield_overall": 0.995, "feature": "工单产品数量N", "cf_field": "/"},
        {"code": "M02-2D", "seq": 5, "step_raw": "封盖", "step_std": "封盖", "level": "模块级",
         "cycle": 2, "yield_overall": 0.995, "feature": "工单产品数量N", "cf_field": "/"},
    ]
    wc_map = {
        "模块级|DB": {"modes": [
            {"mode": "半自动DB", "flux_base": 2000, "flux_peak": 2200, "split_threshold": 20, "unit": "只芯片/天，芯片数N_die"},
            {"mode": "自动DB", "flux_base": 6000, "flux_peak": 6600, "split_threshold": 20, "unit": "只芯片/天，芯片数N_die"},
        ]},
        "模块级|WB": {"modes": [
            {"mode": "半自动WB", "flux_base": 4500, "flux_peak": 4950, "split_threshold": 20, "unit": "根丝/天"},
            {"mode": "自动WB", "flux_base": 12000, "flux_peak": 13200, "split_threshold": 20, "unit": "根丝/天"},
        ]},
        "模块级|调试": {"modes": [{"mode": "/", "flux_base": 10000, "flux_peak": 11000, "unit": "只产品/天"}]},
        "模块级|终检": {"modes": [{"mode": "/", "flux_base": 10000, "flux_peak": 11000, "unit": "只产品/天"}]},
        "模块级|封盖": {"modes": [{"mode": "/", "flux_base": 8000, "flux_peak": 8800, "unit": "只产品/天"}]},
    }
    return {"proc_map": {"M02-2D": proc}, "route_map": {"M02-2D": routes},
            "wc_map": wc_map, "params": dict(P_BASE)}


def _order(**kw):
    base = {"order_no": "T", "product": "模块-01", "code": "M02-2D", "order_type": "常规",
            "first_flag": "否", "water_vapor": "有", "qty": 1000, "due_date": "2026-12-31",
            "features": {"N_die": 60, "N_wire": 60}, "priority": 100}
    base.update(kw)
    return base


def test_chk_calc_001_m02_2d_cycle_flux():
    r = calc_order(_order(), _ctx_m02_2d())
    assert r["cycle"]["base"] == 6          # 1+1+1+1+2
    assert r["cycle"]["urgent"] == 4
    assert r["bottleneck"]["step_std"] == "DB"
    assert r["bottleneck"]["mode"] == "自动DB"
    assert r["bottleneck"]["throughput"] == pytest.approx(100.0)  # 6000÷60
    assert r["steps"][1]["throughput"] == pytest.approx(200.0)    # WB 12000÷60


def test_chk_calc_002_m02_2d_yield_feed_delivery():
    r = calc_order(_order(), _ctx_m02_2d())
    assert r["yield"]["ratio_basis"] == pytest.approx(0.9507210075, rel=1e-9)
    assert r["ratio"]["used"] == pytest.approx(1.052, rel=1e-3)
    assert r["input_qty"] == 1052
    assert r["batch"]["batch_cycle"] == 16
    assert r["batch"]["bottleneck_days"] == 11      # ⌈1052÷100⌉
    assert r["delivery"]["days"] == 17              # 16+0+1 缓冲
    assert r["delivery"]["latest_start_date"] == "2026-12-14"


def test_chk_cycle_005_vapor_cap():
    r = calc_order(_order(water_vapor="无"), _ctx_m02_2d())
    assert r["cycle"]["base"] == 5          # 封盖 2→1
    assert r["steps"][4]["cycle_adjusted"] is True


def test_chk_cycle_006_007_ramp():
    r1 = calc_order(_order(first_flag="首单"), _ctx_m02_2d())
    assert r1["ramp"]["used"] == 1 and r1["delivery"]["days"] == 18   # 16 + 1 爬坡 + 1 缓冲
    r2 = calc_order(_order(first_flag="复线"), _ctx_m02_2d())
    assert r2["ramp"]["used"] == 1
    r3 = calc_order(_order(first_flag="否"), _ctx_m02_2d())
    assert r3["ramp"]["used"] == 0


def test_chk_delivery_002_negative_term_zero():
    # 批量极小：Q < C 时批量项取 0
    r = calc_order(_order(qty=5, features={"N_die": 60, "N_wire": 60}), _ctx_m02_2d())
    assert r["batch"]["batch_cycle"] == r["cycle"]["used"]


def test_chk_delivery_004_005_buffer_variants():
    ctx = _ctx_m02_2d()
    r0 = calc_order(_order(), ctx)
    ctx["params"]["order_buffer_days"] = 0
    r1 = calc_order(_order(), ctx)
    assert r1["delivery"]["days"] == 16 and r0["delivery"]["days"] == 17


def test_chk_yield_005_output_check_iterate():
    # 构造 yRatio 使 ⌈qty×ratio⌉ 恰好产出不足，需要迭代 +1
    ctx = _ctx_m02_2d()
    # 用 qty=1 且 yRatio<1 触发迭代：1×ratio≈1.052→Q=2，2×0.9507=1.90≥1 OK；
    r = calc_order(_order(qty=1, features={"N_die": 60, "N_wire": 60}), ctx)
    assert r["output_check"]["ok"] is True
    assert r["output_check"]["expected"] >= 1


def test_chk_delivery_003_round_mode_variants():
    ctx = _ctx_m02_2d()
    r_ceil = calc_order(_order(), ctx)
    ctx["params"]["round_mode"] = "exact"
    r_exact = calc_order(_order(), ctx)
    assert r_ceil["batch"]["batch_cycle"] == 16
    assert r_exact["batch"]["batch_cycle"] == pytest.approx(15.52, abs=1e-6)


def test_chk_cycle_009_ramp_trigger_variants():
    ctx = _ctx_m02_2d()
    ctx["params"]["ramp_trigger"] = "all"
    r = calc_order(_order(first_flag="否"), ctx)
    assert r["ramp"]["used"] == 1     # 全部订单都触发爬坡
