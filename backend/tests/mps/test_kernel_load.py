"""周负荷（weeklyLoad 移植）与产线瓶颈（lineBottleneck 移植）。"""
import pytest

from app.mps.load import line_bottleneck, weekly_load

P = {"week_days": 6, "peak_factor": 1.1, "use_peak": "mean"}

DB_SEMI = {
    "seq": 1, "step_std": "DB", "level": "模块级", "mode": "半自动DB", "wc_key": "模块级|DB",
    "feature": "DB-芯片数N_die", "feature_key": "N_die", "usage": 60, "missing": False,
    "flux_base": 2000, "unit": "只芯片/天", "is_bottleneck": True,
}


def _mk(order_no, input_qty, steps):
    return {"order": {"order_no": order_no, "product": "P"}, "input_qty": input_qty,
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
