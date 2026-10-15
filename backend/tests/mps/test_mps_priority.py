"""优先级纯核心①：6 因子评分 / 分级 / 数值映射（移植 priority.js §2）。"""
import pytest

from app.mps.priority import (
    DEFAULTS, LEVELS, PINNED_PRIORITY, bottleneck_rate, cfg_of, evaluate,
    level_info, level_of, level_of_priority, priority_of, score_factors,
)


def test_cfg_of_defaults_and_normalization():
    c = cfg_of({})
    assert c["prio_w_u"] == 0.30 and c["prio_thr_p0"] == 80 and c["week_days"] == 6
    c2 = cfg_of({"prio_w_u": 0.6, "prio_w_b": 0.6, "prio_w_k": 0, "prio_w_r": 0, "prio_w_d": 0, "prio_w_w": 0})
    assert c2["prio_w_u"] == pytest.approx(0.5) and c2["prio_w_b"] == pytest.approx(0.5)  # 和=1.2 → 归一
    c3 = cfg_of({"prio_w_u": "abc", "week_days": "5"})
    assert c3["prio_w_u"] == 0.30 and c3["week_days"] == 5


def _calc(delivery_days=17.0, throughput=100.0, input_qty=1052):
    return {"delivery": {"days": delivery_days},
            "bottleneck": {"throughput": throughput}, "input_qty": input_qty}


def test_score_factors_overdue_and_urgent():
    f = score_factors({"due_date": "2026-01-01", "order_type": "加急"},
                      _calc(), cfg_of({}), "2026-06-01")
    assert f["U"] == 100 and f["remain"] < 0
    assert f["W"] == 40                       # 加急 +40
    assert level_of(f, {"order_type": "加急"}, cfg_of({})) == "P0"


def test_score_factors_kit_and_dependency():
    # 齐套晚于最晚上线 → K=100、D=30
    f = score_factors({"due_date": "2026-07-01", "kit_date": "2026-07-05", "first_flag": "首单"},
                      _calc(delivery_days=17.0), cfg_of({}), "2026-06-01")
    assert f["K"] == 100 and f["D"] == 30
    # 首单且齐套 OK → D=80、W≥15
    f2 = score_factors({"due_date": "2026-07-01", "kit_date": "2026-06-01", "first_flag": "首单"},
                       _calc(), cfg_of({}), "2026-06-01")
    assert f2["D"] == 80 and f2["W"] == 15 and f2["K"] == 0


def test_score_factors_slack_buckets():
    from app.mps.dates import add_days as add

    base = {"kit_date": "2026-06-01"}
    def B(remain, delivery):
        f = score_factors({**base, "due_date": add("2026-06-01", remain)},
                          _calc(delivery_days=delivery), cfg_of({}), "2026-06-01")
        return f["B"]
    assert B(15, 17) == 100   # slack<1
    assert B(17, 15) == 80    # 1≤slack<1.2（17/15≈1.133）
    assert B(20, 15) == 60    # 1.2≤slack<1.5 (20/15≈1.33)
    assert B(25, 15) == 40    # 1.5≤slack<2 (25/15≈1.67)
    assert B(50, 15) == 20    # slack≥2


def test_level_and_priority_mapping():
    c = cfg_of({})
    assert level_of({"remain": -1, "score": 0}, {}, c) == "P0"
    assert level_of({"remain": 10, "score": 85}, {}, c) == "P0"
    assert level_of({"remain": 10, "score": 70}, {}, c) == "P1"
    assert level_of({"remain": 10, "score": 50}, {}, c) == "P2"
    assert level_of({"remain": 10, "score": 10}, {}, c) == "P3"
    assert priority_of("P0", 100) == 1
    assert priority_of("P0", 0) == 99
    assert priority_of("P1", 100) == 100
    assert priority_of("P2", 50) == 450        # 300 + round(0.5*299)=449.5→450
    assert priority_of("P3", 0) == 999
    assert level_info("P1")["label"] == "高" and level_info("X") is None
    assert level_of_priority(0) == "P0"
    assert level_of_priority(150) == "P1"
    assert level_of_priority(500) == "P2"
    assert level_of_priority(700) == "P3"
    assert level_of_priority(50) == "P0"
    assert level_of_priority(5000) == "P3"
    assert level_of_priority(None) == "P3"


def test_evaluate_end_to_end():
    ev = evaluate({"due_date": "2026-06-10", "kit_date": "2026-06-01", "order_type": "常规"},
                  _calc(delivery_days=17.0), cfg_of({}), "2026-06-01")
    assert set(ev) == {"score", "level", "priority", "factors"}
    assert ev["priority"] == priority_of(ev["level"], ev["score"])
    assert DEFAULTS["prio_thr_p0"] == 80 and PINNED_PRIORITY == 0 and LEVELS[0]["level"] == "P0"
