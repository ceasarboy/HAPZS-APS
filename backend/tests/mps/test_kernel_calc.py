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
    assert r["steps"][2]["throughput"] == pytest.approx(10000.0)  # 调试=基准通量（只产品N 直接取用）
    assert r["steps"][4]["throughput"] == pytest.approx(8000.0)   # 封盖=基准通量


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


def test_chk_yield_005_output_check():
    # Q=⌈qty×ratio⌉ 数学上恒满足 Q×Y≥qty，while 循环为浮点尾差防御（构造上不可达）；
    # 本测试钉住产出校核字段语义。
    ctx = _ctx_m02_2d()
    r = calc_order(_order(qty=1, features={"N_die": 60, "N_wire": 60}), ctx)
    assert r["input_qty"] == 2          # ⌈1×1.052⌉
    assert r["output_check"] == {"expected": 1, "needed": 1, "ok": True}


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


def test_gantt_bars_m02_2d():
    r = calc_order(_order(), _ctx_m02_2d())
    bars = r["gantt"]["bars"]
    assert r["gantt"]["lead_days"] == r["cycle"]["used"] == 6
    assert r["gantt"]["batch_days"] == r["batch"]["batch_cycle"] == 16
    assert len(bars) == 5
    assert [b["earliest_start"] for b in bars] == [0, 1, 2, 3, 4]
    assert [b["latest_finish"] for b in bars] == [11, 12, 13, 14, 16]
    assert [b["window_days"] for b in bars] == [11, 11, 11, 11, 12]
    assert [b["busy_days"] for b in bars] == [11, 6, 1, 1, 1]
    assert [b["float_days"] for b in bars] == [0, 5, 10, 10, 11]
    assert bars[0]["is_bottleneck"] is True


def test_gantt_subpart_bar():
    ctx = _ctx_m02_2d()
    ctx["proc_map"]["M02-2D"]["subpart_mode"] = "前置"
    ctx["proc_map"]["M02-2D"]["subpart_cycle"] = 2
    r = calc_order(_order(), ctx)
    assert r["cycle"]["subpart_included"] == 2
    assert r["cycle"]["base"] == 8              # 6+2
    bars = r["gantt"]["bars"]
    assert bars[0]["kind"] == "subpart" and bars[0]["window_days"] == 2
    assert bars[1]["earliest_start"] == 2
    assert r["gantt"]["lead_days"] == 8


def test_warnings_happy_missing_and_no_wc():
    r = calc_order(_order(), _ctx_m02_2d())
    assert r["warnings"] == []

    r2 = calc_order(_order(features={}), _ctx_m02_2d())
    assert r2["warnings"][0]["level"] == "error"
    assert "缺少 BOM 特征参数" in r2["warnings"][0]["text"]
    assert r2["bottleneck"]["step_std"] == "封盖"         # 缺参工序不参与取小，仅"只产品N"参与
    assert r2["bottleneck"]["throughput"] == pytest.approx(8000.0)

    ctx = _ctx_m02_2d()
    del ctx["wc_map"]["模块级|DB"]
    r3 = calc_order(_order(), ctx)
    assert any(w["level"] == "warn" and "工序主数据缺失" in w["text"] for w in r3["warnings"])


def test_urgent_used_in_batch_and_delivery():
    r = calc_order(_order(order_type="加急"), _ctx_m02_2d())
    assert r["cycle"]["used"] == 4
    assert r["batch"]["batch_cycle"] == 14      # 4 + ⌈9.52⌉
    assert r["delivery"]["days"] == 15          # 14 + 0 + 1


def test_due_none_and_unknown_code():
    r = calc_order(_order(due_date=None), _ctx_m02_2d())
    assert r["delivery"]["latest_start_date"] is None
    with pytest.raises(ValueError):
        calc_order(_order(code="X-NOPE"), _ctx_m02_2d())


def test_chk_cycle_009b_first_only_trigger():
    ctx = _ctx_m02_2d()
    ctx["params"]["ramp_trigger"] = "first_only"
    assert calc_order(_order(first_flag="首单"), ctx)["ramp"]["used"] == 1
    assert calc_order(_order(first_flag="复线"), ctx)["ramp"]["used"] == 0
    assert calc_order(_order(first_flag="变更首件"), ctx)["ramp"]["used"] == 0


def test_chk_yield_006_component_braze_excluded():
    """组件级（C 系列）钎焊良率双档：exclude=1 剔除 / =0 纳入。"""
    ctx = _ctx_m02_2d()
    ctx["proc_map"]["C-T"] = {"code": "C-T", "ramp_days": 2, "subpart_mode": None, "subpart_cycle": 0}
    ctx["route_map"]["C-T"] = [
        {"code": "C-T", "seq": 1, "step_raw": "钎焊", "step_std": "钎焊", "level": "组件级",
         "cycle": 1, "yield_overall": 0.96, "feature": "钎焊-部件数N_bs", "cf_field": "/"},
        {"code": "C-T", "seq": 2, "step_raw": "调试", "step_std": "调试", "level": "组件级",
         "cycle": 1, "yield_overall": 0.99, "feature": "工单产品数量N", "cf_field": "/"},
    ]
    ctx["wc_map"]["组件级|钎焊"] = {"modes": [{"mode": "/", "flux_base": 1000, "flux_peak": 1100, "unit": "只/天"}]}
    ctx["wc_map"]["组件级|调试"] = {"modes": [{"mode": "/", "flux_base": 1000, "flux_peak": 1100, "unit": "只/天"}]}
    order = {"order_no": "C1", "product": "组件-1", "code": "C-T", "order_type": "常规", "first_flag": "否",
             "water_vapor": "有", "qty": 100, "features": {"N_bs": 10}}

    r = calc_order(order, ctx)
    assert r["ratio"]["exclude_braze"] is True
    assert r["yield"]["ratio_basis"] == pytest.approx(0.99)      # 钎焊 0.96 被剔除
    assert r["yield"]["full"] == pytest.approx(0.96 * 0.99)      # 开关只作用于 basis，full 不变

    ctx["params"]["exclude_braze_yield"] = 0
    r2 = calc_order(order, ctx)
    assert r2["yield"]["ratio_basis"] == pytest.approx(0.96 * 0.99)
    assert r2["yield"]["full"] == pytest.approx(0.96 * 0.99)


def test_chk_cycle_002_parallel_subparts_excluded():
    ctx = _ctx_m02_2d()
    ctx["proc_map"]["M02-2D"]["subpart_mode"] = "平行"
    ctx["proc_map"]["M02-2D"]["subpart_cycle"] = 4
    r = calc_order(_order(), ctx)
    assert r["cycle"]["subpart_included"] == 0
    assert r["cycle"]["base"] == 6          # 平行分部件不占周期
    assert all(b["kind"] == "step" for b in r["gantt"]["bars"])   # 不插分部件条


def test_ramp_days_from_proc():
    ctx = _ctx_m02_2d()
    ctx["proc_map"]["M02-2D"]["ramp_days"] = 2
    ctx["params"]["order_buffer_days"] = 0
    r = calc_order(_order(first_flag="首单"), ctx)
    assert r["ramp"]["days"] == 2           # proc 原始值
    assert r["ramp"]["used"] == 2           # 应用值（首单触发）
    assert r["delivery"]["days"] == 18      # 16 + 2 + 0


def test_order_priority_passthrough():
    """优先级透传字段（计划 3A 接口确认：供 cmp_order/result_key 消费）。"""
    order = _order()
    order.update({"id": "o-1", "prio_level": "P1", "prio_score": 66.6, "prio_source": "manual",
                  "prio_manual": 150, "pinned": True, "pinned_at": "2026-10-01", "sort_no": 2.5, "status": "正常"})
    r = calc_order(order, _ctx_m02_2d())
    o = r["order"]
    assert o["id"] == "o-1" and o["prio_level"] == "P1" and o["prio_score"] == 66.6
    assert o["prio_source"] == "manual" and o["pinned"] is True and o["pinned_at"] == "2026-10-01"
    assert o["sort_no"] == 2.5 and o["status"] == "正常"
    # 缺省：prio_source=auto、pinned=False、sort_no=None
    o2 = calc_order(_order(), _ctx_m02_2d())["order"]
    assert o2["prio_source"] == "auto" and o2["pinned"] is False and o2["sort_no"] is None
    # datetime 归一化：pinned_at 始终为 'YYYY-MM-DD' 字符串（cmp 键依赖字符串比较）
    from datetime import datetime

    o3 = _order()
    o3["pinned_at"] = datetime(2026, 10, 1, 8, 0)
    assert calc_order(o3, _ctx_m02_2d())["order"]["pinned_at"] == "2026-10-01"
