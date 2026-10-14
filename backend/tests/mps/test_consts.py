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
