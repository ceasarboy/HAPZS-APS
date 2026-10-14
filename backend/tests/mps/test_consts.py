"""MPS 常量：特征字段、路线特征映射、参数定义。"""
from app.mps.consts import FEATURE_FIELDS, FEATURE_MAP, PARAM_DEFS


def test_feature_fields_13():
    keys = [f["key"] for f in FEATURE_FIELDS]
    assert len(keys) == 13
    assert "N_die2" in keys and "Y_wire2" in keys and "N_a" in keys


def test_feature_map_db_wb():
    assert FEATURE_MAP["DB-芯片数N_die"] == ["N_die", "Y_die"]
    assert FEATURE_MAP["DB-芯片数N_die-2"] == ["N_die2", "Y_die2"]
    assert FEATURE_MAP["WB-键合线数N_wire-2"] == ["N_wire2", "Y_wire2"]
    assert FEATURE_MAP["工单产品数量N"] == []


def test_param_defs_unique_and_defaults():
    keys = [p["key"] for p in PARAM_DEFS]
    assert len(keys) == len(set(keys))
    defs = {p["key"]: p for p in PARAM_DEFS}
    assert defs["week_days"]["value"] == "6"
    assert defs["peak_factor"]["value"] == "1.1"
    assert defs["order_buffer_days"]["value"] == "1"
    assert defs["reference_batch"]["value"] == "1000"
    assert defs["round_mode"]["value"] == "exact"
    assert defs["ramp_trigger"]["value"] == "first_flag"
    assert defs["wb_auto_flux_override"]["value"] == "0"


def test_feature_map_key_snapshot():
    assert set(FEATURE_MAP) == {
        "植球-球数N_b", "FC-倒装元件数N_fc", "钎焊-部件数N_bs", "SMT-贴装元件数N_smt",
        "DB-芯片数N_die", "DB-芯片数N_die-1", "DB-芯片数N_die-2",
        "WB-键合线数N_wire", "WB-键合线数N_wire-1", "WB-键合线数N_wire-2",
        "电装-（焊点+螺钉）数量N_a", "工单产品数量N",
    }


def test_param_defs_key_snapshot():
    assert {p["key"] for p in PARAM_DEFS} == {
        "week_days", "peak_factor", "use_peak", "exclude_braze_yield", "wb_auto_flux_override",
        "cf_db_1", "cf_db_2", "cf_db_3", "cf_wb_1", "cf_wb_2", "cf_wb_3",
        "vapor_cap_cut", "order_buffer_days", "reference_batch", "round_mode", "ramp_trigger",
    }


def test_feature_map_values_are_feature_keys():
    field_keys = {f["key"] for f in FEATURE_FIELDS}
    for keys in FEATURE_MAP.values():
        assert set(keys).issubset(field_keys)
