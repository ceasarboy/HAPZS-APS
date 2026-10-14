"""内核单点函数：本地工具 / 加急 / 分流 / 特征用量 / 折算系数 / 必填字段。"""
from app.mps.kernel import (
    ceil_int, conv_factor, feature_usage, nz, pick_mode, ramp_flux_factor,
    required_fields, urgent_cycle,
)


def test_nz_and_ceil_int():
    assert nz(None, 6) == 6 and nz("", 6) == 6 and nz("abc", 6) == 6
    assert nz("2.5", 0) == 2.5
    assert ceil_int(9.52) == 10 and ceil_int(10.0) == 10
    assert ceil_int(0.1) == 1


def test_urgent_cycle_tiers():
    assert urgent_cycle(5) == 4      # ≤5 → ΔT=1
    assert urgent_cycle(6) == 4      # 6~10 → ΔT=2
    assert urgent_cycle(10) == 8
    assert urgent_cycle(11) == 8     # >10 → ΔT=3
    assert urgent_cycle(1) == 1      # 下限 1 天
    assert urgent_cycle(2) == 1


def test_ramp_flux_factor():
    assert ramp_flux_factor(0, 2) == 0.0
    assert ramp_flux_factor(1, 2) == 0.5
    assert ramp_flux_factor(2, 2) == 1.0
    assert ramp_flux_factor(5, 2) == 1.0
    assert ramp_flux_factor(1, 0) == 1.0  # 无爬坡


def test_pick_mode_module_db_split():
    wc = {
        "modes": [
            {"mode": "半自动DB", "flux_base": 2000, "split_threshold": 20},
            {"mode": "自动DB", "flux_base": 6000, "split_threshold": 20},
        ]
    }
    assert pick_mode(wc, 19)["mode_name"] == "半自动DB"   # CHK-FLUX-001
    assert pick_mode(wc, 20)["mode_name"] == "自动DB"
    assert pick_mode(wc, 1000)["mode_name"] == "自动DB"   # 参考批量口径
    assert pick_mode({"modes": [{"mode": "/", "flux_base": 500}]}, 1)["mode_name"] == "/"


def test_feature_usage_and_missing():
    step = {"feature": "DB-芯片数N_die"}
    assert feature_usage(step, {"N_die": 60}) == {"key": "N_die", "usage": 60, "missing": False}
    assert feature_usage(step, {})["missing"] is True      # CHK-FLUX-014 缺参
    assert feature_usage({"feature": "工单产品数量N"}, {}) == {"key": "N", "usage": 1, "missing": False}
    assert feature_usage({"feature": "不存在的特征"}, {})["missing"] is True


def test_conv_factor_db_wb():
    p = {"cf_db_1": 1, "cf_db_2": 0.9, "cf_db_3": 0.8, "cf_wb_1": 1, "cf_wb_2": 0.95, "cf_wb_3": 0.9}
    db = {"cf_field": "DB胶水类型Y_die", "feature": "DB-芯片数N_die"}
    wb = {"cf_field": "WB引线类型Y_wire", "feature": "WB-键合线数N_wire"}
    assert conv_factor(db, {"Y_die": 1}, p) == 1.0
    assert conv_factor(db, {"Y_die": 2}, p) == 0.9
    assert conv_factor(db, {"Y_die": 3}, p) == 0.8
    assert conv_factor(wb, {"Y_wire": 2}, p) == 0.95
    assert conv_factor(wb, {"Y_wire": 4}, p) == 0.9
    assert conv_factor({"cf_field": "/"}, {}, p) == 1.0
    # 第2组（特征名以 -2 结尾）走 Y_die2 / Y_wire2（CHK-FLUX-017）
    db2 = {"cf_field": "DB胶水类型Y_die", "feature": "DB-芯片数N_die-2"}
    assert conv_factor(db2, {"Y_die": 1, "Y_die2": 2}, p) == 0.9


def test_required_fields():
    routes = [
        {"code": "X", "seq": 2, "feature": "WB-键合线数N_wire"},
        {"code": "X", "seq": 1, "feature": "DB-芯片数N_die"},
        {"code": "Y", "seq": 1, "feature": "SMT-贴装元件数N_smt"},
    ]
    fields = required_fields("X", routes)
    keys = [f["key"] for f in fields]
    assert keys == ["N_die", "Y_die", "N_wire", "Y_wire"]  # 按 FEATURE_FIELDS 顺序，seq 排序
    unmapped = required_fields("Z", [{"code": "Z", "seq": 1, "feature": "未知-特征X"}])
    assert unmapped[0]["unmapped"] is True


def test_pick_mode_none_and_empty():
    assert pick_mode(None, 1) is None
    assert pick_mode({}, 1) is None
    assert pick_mode({"modes": []}, 1) is None


def test_pick_mode_reversed_modes_order():
    """行序反转（明道云同步后可能）仍按名称正确分流。"""
    wc = {
        "modes": [
            {"mode": "自动DB", "flux_base": 6000, "split_threshold": 20},
            {"mode": "半自动DB", "flux_base": 2000, "split_threshold": 20},
        ]
    }
    assert pick_mode(wc, 10)["mode_name"] == "半自动DB"
    assert pick_mode(wc, 20)["mode_name"] == "自动DB"


def test_conv_factor_wb_second_group_and_default():
    p = {"cf_wb_1": 1, "cf_wb_2": 0.95, "cf_wb_3": 0.9}
    wb2 = {"cf_field": "WB引线类型Y_wire", "feature": "WB-键合线数N_wire-2"}
    assert conv_factor(wb2, {"Y_wire": 1, "Y_wire2": 3}, p) == 0.9   # 第2组走 Y_wire2
    wb = {"cf_field": "WB引线类型Y_wire", "feature": "WB-键合线数N_wire"}
    assert conv_factor(wb, {}, p) == 1.0                            # 缺键默认 1 种


def test_feature_usage_zero_empty_missing():
    step = {"feature": "DB-芯片数N_die"}
    assert feature_usage(step, {"N_die": 0})["missing"] is True
    assert feature_usage(step, {"N_die": ""})["missing"] is True
    assert feature_usage(step, {"N_die": -1})["missing"] is True
