"""MPS 日期工具：解析/格式化/加天/差天（含 JS Math.round 半上取整复刻）。"""
from app.mps.dates import DAY, add_days, diff_days, to_date, to_str


def test_parse_and_format():
    from datetime import date

    assert to_date("2026-12-31") == date(2026, 12, 31)
    assert to_date("2026-12-31T08:00:00Z") == date(2026, 12, 31)
    assert to_date(date(2026, 1, 2)) == date(2026, 1, 2)
    assert to_date("") is None and to_date(None) is None and to_date("bad") is None
    assert to_str(date(2026, 1, 2)) == "2026-01-02"
    assert to_str(None) == ""


def test_add_days_half_rounding_matches_js():
    # JS Math.round(0.5)=1 → 复刻为 floor(x+0.5)
    assert add_days("2026-01-01", 0.5) == "2026-01-02"
    assert add_days("2026-01-01", 1) == "2026-01-02"
    assert add_days("2026-01-01", -0.5) == "2026-01-01"   # floor(0)=0
    assert add_days("2026-01-01", 2.4) == "2026-01-03"
    assert add_days("bad", 1) == ""


def test_diff_days():
    assert diff_days("2026-12-14", "2026-12-31") == 17
    assert diff_days("2026-12-31", "2026-12-14") == -17
    assert diff_days(None, "2026-01-01") is None
    assert DAY == 86400000


def test_datetime_inputs_normalized():
    from datetime import datetime

    dt = datetime(2026, 1, 2, 3, 4, 5)
    assert to_date(dt).isoformat() == "2026-01-02"
    assert to_str(to_date(dt)) == "2026-01-02"
    assert add_days(dt, 1) == "2026-01-03"
    assert diff_days(dt, "2026-01-05") == 3
