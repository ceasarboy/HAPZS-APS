"""周负荷（weeklyLoad 移植）与产线瓶颈（lineBottleneck 移植）。"""
import pytest

from app.mps.load import line_bottleneck, weekly_load

P = {"week_days": 6, "peak_factor": 1.1, "use_peak": "mean"}

DB_SEMI = {
    "seq": 1, "step_std": "DB", "level": "模块级", "mode": "半自动DB", "wc_key": "模块级|DB",
    "feature": "DB-芯片数N_die", "feature_key": "N_die", "usage": 60, "missing": False,
    "flux_base": 2000, "unit": "只芯片/天", "is_bottleneck": True, "throughput": 100,
}


def _mk(order_no, input_qty, steps):
    return {"order": {"order_no": order_no, "product": "P", "code": "M02-2D"}, "input_qty": input_qty,
            "steps": steps, "bottleneck": next((s for s in steps if s.get("is_bottleneck")), None),
            "batch": {"batch_cycle": 10, "bottleneck_days": 3}}


def _results():
    # 构造两个工单结果（字段依赖与 mps-web 结果同构）
    wb = {"seq": 2, "step_std": "WB", "level": "模块级", "mode": "半自动WB", "wc_key": "模块级|WB",
          "feature": "WB-键合线数N_wire", "feature_key": "N_wire", "usage": 100, "missing": False,
          "flux_base": 4500, "unit": "根丝/天", "is_bottleneck": False}
    miss = {"seq": 3, "step_std": "SMT", "level": "模块级", "mode": "/", "wc_key": "模块级|SMT",
            "feature": "SMT-贴装元件数N_smt", "feature_key": "N_smt", "usage": None, "missing": True,
            "flux_base": 2400, "unit": "只/天", "is_bottleneck": False}
    return [_mk("A", 100, [dict(DB_SEMI), wb]), _mk("B", 100, [dict(DB_SEMI), dict(miss)])]


def test_weekly_load_and_judge():
    rows = weekly_load(_results(), {"params": dict(P)})
    d = {r["key"]: r for r in rows}
    # 模块级|DB|半自动DB：load=(100+100)×60=12000；available=2000×6=12000 → 恰 1.0 不属超载
    assert d["模块级|DB|半自动DB"]["load"] == pytest.approx(12000)
    assert d["模块级|DB|半自动DB"]["available"] == pytest.approx(12000)
    assert d["模块级|DB|半自动DB"]["judge"] == "偏紧"   # rate==1.0 → 不是 >1
    # 模块级|WB|半自动WB：load=100×100=10000；available=4500×6=27000
    assert d["模块级|WB|半自动WB"]["load_rate"] == pytest.approx(10000 / 27000)
    # 缺特征订单进入 missing_orders 且不累计负荷
    smt = d["模块级|SMT|/"]
    assert smt["load"] == 0 and smt["missing_orders"] == ["B"]


def test_weekly_load_peak_mode():
    rows = weekly_load(_results(), {"params": {**P, "use_peak": "peak"}})
    d = {r["key"]: r for r in rows}
    assert d["模块级|DB|半自动DB"]["available"] == pytest.approx(2000 * 1.1 * 6)


def test_judge_thresholds():
    # 边界校正（按真实算术）：恰 1.0 → 偏紧（>1 才超载）
    rows = weekly_load(_results(), {"params": dict(P)})
    d = {r["key"]: r for r in rows}
    assert d["模块级|DB|半自动DB"]["load_rate"] == pytest.approx(1.0)
    assert d["模块级|DB|半自动DB"]["judge"] == "偏紧"    # =1.00
    # 峰值模式：DB 12000/13200≈0.909 → 偏紧；WB 10000/29700≈0.337 → 正常（<0.85）
    rows2 = weekly_load(_results(), {"params": {**P, "use_peak": "peak"}})
    d2 = {r["key"]: r for r in rows2}
    assert d2["模块级|DB|半自动DB"]["available"] == pytest.approx(2000 * 1.1 * 6)
    assert d2["模块级|DB|半自动DB"]["load_rate"] == pytest.approx(12000 / 13200)
    assert d2["模块级|DB|半自动DB"]["judge"] == "偏紧"
    assert d2["模块级|WB|半自动WB"]["available"] == pytest.approx(4500 * 1.1 * 6)
    assert d2["模块级|WB|半自动WB"]["load_rate"] == pytest.approx(10000 / 29700)
    assert d2["模块级|WB|半自动WB"]["judge"] == "正常"
    # 超载：本测试内局部追加一单（副本，不改 _results() 本体）→ DB 18000/12000=1.5
    results3 = _results()
    results3.append(_mk("C", 100, [dict(DB_SEMI)]))
    d3 = {r["key"]: r for r in weekly_load(results3, {"params": dict(P)})}
    assert d3["模块级|DB|半自动DB"]["load"] == pytest.approx(18000)
    assert d3["模块级|DB|半自动DB"]["load_rate"] == pytest.approx(1.5)
    assert d3["模块级|DB|半自动DB"]["judge"] == "超载"


def test_line_bottleneck_hits_details_join():
    results = _results()
    load_rows = weekly_load(results, {"params": dict(P)})
    rows = line_bottleneck(results, load_rows)
    assert len(rows) == 1
    r = rows[0]
    assert r["key"] == "模块级|DB|半自动DB"
    assert r["level"] == "模块级" and r["op"] == "DB" and r["mode"] == "半自动DB"
    assert r["hits"] == 2
    assert r["total_days"] == 6          # 两单各 bottleneck_days=3
    assert [o["order_no"] for o in r["orders"]] == ["A", "B"]
    assert r["orders"][0]["code"] == "M02-2D" and r["orders"][0]["throughput"] == 100
    assert r["load_rate"] == pytest.approx(1.0)
    assert r["judge"] == "偏紧"


def test_line_bottleneck_skip_rules():
    results = _results()
    results.append({"error": "x", "order": {"order_no": "E"}, "input_qty": 0,
                    "steps": [], "bottleneck": None, "batch": {}})
    no_bn_step = {**DB_SEMI, "is_bottleneck": False}          # F 无瓶颈步
    results.append(_mk("F", 50, [no_bn_step]))
    rows = line_bottleneck(results, [])
    assert len(rows) == 1 and rows[0]["hits"] == 2 and rows[0]["total_days"] == 6


def test_line_bottleneck_sorting_rate_then_hits_and_no_join_last():
    wb_step = {"seq": 2, "step_std": "WB", "level": "模块级", "mode": "半自动WB", "wc_key": "模块级|WB",
               "feature": "WB-键合线数N_wire", "feature_key": "N_wire", "usage": 100, "missing": False,
               "flux_base": 4500, "unit": "根丝/天", "is_bottleneck": True}
    smt_step = {"seq": 3, "step_std": "SMT", "level": "模块级", "mode": "/", "wc_key": "模块级|SMT",
                "feature": "SMT-贴装元件数N_smt", "feature_key": "N_smt", "usage": 10, "missing": False,
                "flux_base": 2400, "unit": "只/天", "is_bottleneck": True}
    results = [_mk("A", 100, [dict(DB_SEMI)]), _mk("B", 100, [dict(DB_SEMI)]),
               _mk("C", 100, [dict(wb_step)]), _mk("D", 100, [dict(smt_step)])]
    load_rows = [
        {"key": "模块级|DB|半自动DB", "load_rate": 0.5, "judge": "正常"},
        {"key": "模块级|WB|半自动WB", "load_rate": 0.5, "judge": "正常"},
    ]
    rows = line_bottleneck(results, load_rows)
    # rate 相等 → hits 降序（DB 2 > WB 1）；无 join 行者（SMT）load_rate/judge 为 None 且排最后
    assert [r["key"] for r in rows] == ["模块级|DB|半自动DB", "模块级|WB|半自动WB", "模块级|SMT|/"]
    assert rows[2]["load_rate"] is None and rows[2]["judge"] is None

    load_rows2 = [
        {"key": "模块级|DB|半自动DB", "load_rate": 0.4, "judge": "正常"},
        {"key": "模块级|WB|半自动WB", "load_rate": 0.9, "judge": "偏紧"},
    ]
    rows2 = line_bottleneck(results, load_rows2)
    assert rows2[0]["key"] == "模块级|WB|半自动WB"    # rate 优先于 hits


def test_weekly_load_zero_flux_missing_judge():
    results = _results()
    results.append(_mk("Z", 10, [{
        "seq": 1, "step_std": "调试", "level": "模块级", "mode": "/", "wc_key": "模块级|调试",
        "feature": "工单产品数量N", "feature_key": "N", "usage": 1, "missing": False,
        "flux_base": 0, "unit": "只/天", "is_bottleneck": False}]))
    d = {r["key"]: r for r in weekly_load(results, {"params": dict(P)})}
    assert d["模块级|调试|/"]["load_rate"] is None
    assert d["模块级|调试|/"]["judge"] == "缺通量"


def test_weekly_load_boundary_085():
    at = weekly_load([_mk("A", 85, [dict(DB_SEMI)]), _mk("B", 85, [dict(DB_SEMI)])], {"params": dict(P)})
    assert at[0]["load"] == pytest.approx(10200)
    assert at[0]["judge"] == "偏紧"          # 0.85 ≥ 0.85

    below = weekly_load([_mk("A", 84, [dict(DB_SEMI)]), _mk("B", 83, [dict(DB_SEMI)])], {"params": dict(P)})
    assert below[0]["load_rate"] == pytest.approx(10020 / 12000)
    assert below[0]["judge"] == "正常"       # 0.835 < 0.85


def test_weekly_load_sort_orders_detail_and_defaults():
    rows = weekly_load(_results(), {"params": dict(P)})
    assert [r["key"] for r in rows] == ["模块级|DB|半自动DB", "模块级|WB|半自动WB", "模块级|SMT|/"]
    db = rows[0]
    assert db["orders"] == [
        {"order_no": "A", "qty": 100, "usage": 60, "amount": 6000},
        {"order_no": "B", "qty": 100, "usage": 60, "amount": 6000},
    ]
    # 参数缺省：week_days 默认 6；error 结果与无 wc_key 步不入聚合
    results3 = _results()
    results3[0]["steps"] = results3[0]["steps"] + [{"seq": 9, "wc_key": None, "missing": False, "usage": 1}]
    results3.append({"error": True, "steps": []})
    d3 = {r["key"]: r for r in weekly_load(results3, {})}
    assert set(d3) == {"模块级|DB|半自动DB", "模块级|WB|半自动WB", "模块级|SMT|/"}
    assert d3["模块级|DB|半自动DB"]["week_days"] == 6


def test_weekly_load_scope_route_without_db():
    wb_step = {"seq": 1, "step_std": "WB", "level": "模块级", "mode": "半自动WB", "wc_key": "模块级|WB",
               "feature": "WB-键合线数N_wire", "feature_key": "N_wire", "usage": 100, "missing": False,
               "flux_base": 4500, "unit": "根丝/天", "is_bottleneck": False}
    rows = weekly_load(_results() + [_mk("R", 100, [dict(wb_step)])], {"params": dict(P)})
    d = {r["key"]: r for r in rows}
    assert d["模块级|DB|半自动DB"]["load"] == pytest.approx(12000)   # 路线不含 DB 的订单不参与
    assert d["模块级|WB|半自动WB"]["load"] == pytest.approx(20000)   # 100+100
