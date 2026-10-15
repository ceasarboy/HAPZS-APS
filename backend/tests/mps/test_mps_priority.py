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


def test_evaluate_literal_and_bool_num():
    from app.mps.priority import _num

    ev = evaluate({"due_date": "2026-06-10", "kit_date": "2026-06-01", "order_type": "常规"},
                  _calc(delivery_days=17.0), cfg_of({}), "2026-06-01")
    assert ev["score"] == 74.9 and ev["level"] == "P1" and ev["priority"] == 150
    assert _num(True, 0) == 1.0 and _num(False, 7) == 0.0     # kernel 置顶 bool 透传承重点


def test_cmp_order_eight_levels():
    from app.mps.priority import cmp_order, sort_key

    a = {"pinned": 0, "priority": 100, "sort_no": None, "due_date": "2026-07-01", "order_no": "B"}
    b = {"pinned": 1, "pinned_at": "2026-06-01", "priority": 0, "due_date": "2026-12-01", "order_no": "A"}
    assert cmp_order(a, b) > 0                       # 1 置顶优先
    assert cmp_order(b, a) < 0
    p1 = {"pinned": 1, "pinned_at": "2026-06-01", "order_no": "X"}
    p2 = {"pinned": 1, "pinned_at": "2026-06-02", "order_no": "Y"}
    assert cmp_order(p1, p2) < 0                     # 2 先置顶先排
    assert cmp_order({"priority": 100}, {"priority": 200}) < 0   # 3 数值升序
    assert cmp_order({"priority": 100, "sort_no": 1}, {"priority": 100, "sort_no": 2}) < 0  # 4 拖拽序
    assert cmp_order({"priority": 100, "due_date": "2026-07-01"},
                     {"priority": 100, "due_date": "2026-07-02"}) < 0                            # 5 交期早
    assert cmp_order({"priority": 100, "delivery_days": 10},
                     {"priority": 100, "delivery_days": 20}) < 0                                # 6 快单
    assert cmp_order({"priority": 100, "bottleneck_rate": 0.9},
                     {"priority": 100, "bottleneck_rate": 0.1}) < 0                             # 7 瓶颈高
    assert cmp_order({"priority": 100, "order_no": "A"},
                     {"priority": 100, "order_no": "B"}) < 0                                    # 8 编号兜底
    # 默认兜底：空交期 9999-12-31、未拖拽 1e9、缺优先级 100
    k = sort_key({"order_no": "Z"})
    assert k["due_date"] == "9999-12-31" and k["sort_no"] == 1e9 and k["priority"] == 100


def test_sort_stability_shuffled():
    from app.mps.priority import sort_orders

    base = [{"order_no": f"O{i}", "priority": 100 + (i % 3)} for i in range(9)]
    once = [o["order_no"] for o in sort_orders(base)]
    import random
    shuffled = base[:]
    random.Random(7).shuffle(shuffled)
    assert [o["order_no"] for o in sort_orders(shuffled)] == once  # 稳定可复现


def test_result_key_and_cmp_result():
    from app.mps.priority import cmp_result, result_key

    def mk(no, days, thr, qty, due=None, pr=100):
        return {"order": {"order_no": no, "due_date": due, "priority": pr},
                "delivery": {"days": days}, "bottleneck": {"throughput": thr}, "input_qty": qty}
    r1, r2 = mk("A", 10, 100, 100), mk("B", 20, 100, 100)
    assert result_key(r1, week_days=6)["delivery_days"] == 10
    assert cmp_result(r1, r2) < 0                      # 快单优先（第 6 级）
    r3 = mk("C", 10, 100, 600)                         # 瓶颈占用=ceil(600/100)=6 天 → 1.0
    assert result_key(r3, week_days=6)["bottleneck_rate"] == 1.0


def test_recompute_rows_manual_and_pinned():
    from app.mps.priority import recompute_rows

    cfg = cfg_of({})
    orders = [
        {"id": "1", "order_no": "A", "due_date": "2026-06-20", "kit_date": "2026-06-01", "priority": 500, "prio_source": "manual", "pinned": 0},
        {"id": "2", "order_no": "B", "due_date": "2026-06-20", "kit_date": "2026-06-01", "priority": 0, "pinned": 1, "pinned_until": "2026-12-31"},
        {"id": "3", "order_no": "C", "due_date": "2026-01-01", "priority": 800},
    ]
    calc = {"A": _calc(), "B": _calc(), "C": _calc()}
    out = recompute_rows(orders, calc, cfg, "2026-06-01", {})
    assert out[0]["applied"] is False and "手动值" in out[0]["skipReason"] and out[0]["priority"] == 500
    assert out[1]["applied"] is False and out[1]["skipReason"] == "已置顶，保持不变"
    assert out[2]["level"] == "P0" and out[2]["applied"] is True and out[2]["changed"] is True
    forced = recompute_rows(orders, calc, cfg, "2026-06-01", {"force": True})
    assert forced[0]["applied"] is True and forced[0]["priority"] != 500


def test_reorder_target_pinned_and_normal():
    from app.mps.priority import PINNED_PRIORITY, reorder_target

    order = {"priority": 100, "sort_no": None}
    t = reorder_target(order, {"sort_no": 10}, {"sort_no": 20}, True)
    assert t["pinned"] == 1 and t["sort_no"] == 15 and t["priority"] == PINNED_PRIORITY and t["source"] == "pin"
    t2 = reorder_target(order, {"sort_no": 10}, None, True)
    assert t2["sort_no"] == 20                          # a+10
    t3 = reorder_target(order, None, {"sort_no": 10}, True)
    assert t3["sort_no"] == 0                           # b-10
    t4 = reorder_target(order, None, None, True)
    assert t4["sort_no"] == 10                          # 兜底
    t5 = reorder_target(order, {"sort_no": 10}, {"sort_no": 10.0000001}, True)
    assert t5["sort_no"] == 11                          # 碰撞让位 a+1
    n = reorder_target(order, {"priority": 100, "pinned": 0}, {"priority": 200, "pinned": 0}, False)
    assert n["priority"] == 150 and n["pinned"] == 0 and n["source"] == "manual" and n["level"] == "P1"
    n2 = reorder_target(order, None, {"priority": 200, "pinned": 0}, False)
    assert n2["priority"] == 190                        # b-10
    n3 = reorder_target(order, {"priority": 9995, "pinned": 0}, None, False)
    assert n3["priority"] == 9999                       # min(9999, a+10)
    n4 = reorder_target({"priority": 100}, {"priority": 150, "pinned": 0}, {"priority": 150, "pinned": 0}, False)
    assert n4["priority"] == 151                        # 与邻居重合让位
