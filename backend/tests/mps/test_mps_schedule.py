"""排产解码①：alloc_earliest 账本语义 / op_work（含手工条扩展）。"""
import pytest

from app.mps.schedule import alloc_earliest, op_work, order_opts, resource_key


def test_order_opts_defaults():
    o = order_opts({"P": {"setup_days": 1.5, "due_buffer_days": 3}})
    assert o["setupDiff"] == 1.5 and o["due_buffer_days"] == 3
    o2 = order_opts()
    assert o2["setupDiff"] == 0.5 and o2["due_buffer_days"] == 0


def test_alloc_earliest_basic_and_daily_spread():
    ledger = {}
    a = alloc_earliest(ledger, "R1", 0, 63120, 6000)
    assert a["dayNeeded"] == 11 and a["start"] == 0 and a["end"] == 11
    assert ledger["R1"][0]["used"] == pytest.approx(63120 / 11)
    # 第二单同资源：0~10 日均已放 5738.18/天，放不下 360 → 顺延到 day11（该日为空）
    b = alloc_earliest(ledger, "R1", 0, 360, 6000)
    assert b["start"] == 11 and b["dayNeeded"] == 1
    assert ledger["R1"][11]["used"] == pytest.approx(360)


def test_alloc_earliest_scan_gap_and_capacity_fit():
    ledger = {}
    alloc_earliest(ledger, "R1", 0, 6000, 6000)          # day0 满
    c = alloc_earliest(ledger, "R1", 0, 6000, 6000)      # 应顺延到 day1
    assert c["start"] == 1 and c["end"] == 2
    # 单日容量刚好：floor 容差（1e-9）
    d = alloc_earliest(ledger, "R2", 0, 2000 * 0.1, 2000)
    assert d["dayNeeded"] == 1


def test_alloc_earliest_nooverlap_policy():
    ledger = {}
    a = alloc_earliest(ledger, "R1", 0, 3000, 3000, policy="nooverlap")
    b = alloc_earliest(ledger, "R1", 0, 3000, 3000, policy="nooverlap")
    assert b["start"] >= a["end"]                        # 同单其它工序重叠被禁止（跨单由 used 约束）


def test_alloc_earliest_zero_amount():
    r = alloc_earliest({}, "R1", 3, 0, 100)
    assert r == {"start": 3, "end": 3, "span": 0, "dayNeeded": 0}


def _ctx_min():
    return {
        "proc_map": {"M02-2D": {"code": "M02-2D", "ramp_days": 1, "subpart_mode": None, "subpart_cycle": 0}},
        "route_map": {"M02-2D": [
            {"code": "M02-2D", "seq": 1, "step_raw": "DB", "step_std": "DB", "level": "模块级",
             "cycle": 1, "yield_overall": 0.97, "feature": "DB-芯片数N_die", "cf_field": "DB胶水类型Y_die"},
            {"code": "M02-2D", "seq": 2, "step_raw": "WB", "step_std": "WB", "level": "模块级",
             "cycle": 1, "yield_overall": 0.98, "feature": "WB-键合线数N_wire", "cf_field": "WB引线类型Y_wire"},
        ]},
        "wc_map": {
            "模块级|DB": {"modes": [
                {"mode": "半自动DB", "flux_base": 2000, "flux_peak": 2200, "split_threshold": 20, "unit": "只芯片/天"},
                {"mode": "自动DB", "flux_base": 6000, "flux_peak": 6600, "split_threshold": 20, "unit": "只芯片/天"},
            ]},
            "模块级|WB": {"modes": [
                {"mode": "半自动WB", "flux_base": 4500, "flux_peak": 4950, "split_threshold": 20, "unit": "根丝/天"},
                {"mode": "自动WB", "flux_base": 12000, "flux_peak": 13200, "split_threshold": 20, "unit": "根丝/天"},
            ]},
        },
        "params": {"week_days": 6, "peak_factor": 1.1, "use_peak": "mean", "exclude_braze_yield": 1,
                   "cf_db_1": 1, "cf_db_2": 0.9, "cf_db_3": 0.8, "cf_wb_1": 1, "cf_wb_2": 0.95, "cf_wb_3": 0.9,
                   "vapor_cap_cut": 1, "order_buffer_days": 1, "reference_batch": 1000,
                   "round_mode": "ceil", "ramp_trigger": "first_flag", "wb_auto_flux_override": 0},
    }


def _calc(qty=1000):
    from app.mps.kernel import calc_order

    o = {"order_no": "A", "product": "P", "code": "M02-2D", "order_type": "常规",
         "first_flag": "否", "water_vapor": "有", "qty": qty, "features": {"N_die": 60, "N_wire": 60}}
    return calc_order(o, _ctx_min())


def test_op_work_from_step_and_manual():
    r = _calc()
    w = op_work(r, r["gantt"]["bars"][0])
    assert w["key"] == "模块级|DB|自动DB"
    assert w["amt"] == pytest.approx(1052 * 60) and w["flux"] == 6000
    manual = {"kind": "step", "seq": 2.5, "step_std": "调试", "level": "模块级",
              "mode": "/", "usage": 1, "flux": 10000, "manual": True}
    wm = op_work(r, manual)
    assert wm["key"] == "模块级|调试|/" and wm["flux"] == 10000
    assert wm["amt"] == pytest.approx(1052)


def test_resource_key_and_subpart():
    r = _calc()
    assert resource_key(r, r["gantt"]["bars"][0]) == "模块级|DB|自动DB"
    assert resource_key(r, {"kind": "subpart", "seq": 0, "step_std": "前置分部件"}) == "前置分部件|M02-2D"
    assert resource_key(r, {"kind": "step", "seq": 99, "step_std": "X"}) is None
