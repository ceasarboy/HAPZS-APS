"""策略层：5 策略注册表/排序器/指标/得分/配置 schema（移植 strategy.js）。"""
import pytest

from app.mps.strategy import (
    OBJECTIVE_SCHEMA, STRATEGIES, STRATEGY_CONFIG_SCHEMA, STRATEGY_IDS,
    bottleneck_load_of, family_of, get_strategy, get_strategy_config_values,
    order_by_bottleneck, order_by_due, order_by_setup, order_by_util,
    strategy_metrics, strategy_score, workload_of,
)


def _r(no, code="M01-2DS", due="2026-07-01", qty=100, thr=None, days=17, judge="满足"):
    return {"order": {"order_no": no, "code": code, "due_date": due},
            "input_qty": qty,
            "bottleneck": {"throughput": thr} if thr else None,
            "delivery": {"days": days},
            "plan": {"judge": judge, "start_date": "2026-06-01", "finish_date": "2026-06-10"},
            "gantt": {"bars": []}}


def test_registry_and_defaults():
    assert STRATEGY_IDS == ["priority", "due", "util", "setup", "bottleneck"]
    s = get_strategy("due")
    assert s["allocPolicy"] == "pack"
    assert STRATEGIES["setup"]["allocPolicy"] == "nooverlap"
    assert get_strategy("nope")["id"] == "priority"      # 非法回退
    s2 = get_strategy("due", {"strategy_due_tardy": 4.5, "strategy_due_setup": "abc"})
    assert s2["objective"]["tardy"] == 4.5 and s2["objective"]["setup"] == 1  # 非法保留原值


def test_family_and_helpers():
    assert family_of(_r("A", code="M01-2DS")) == "M01"
    assert family_of(_r("A", code="")) == "NA"
    assert workload_of(_r("A", qty=1052)) == 1052 and workload_of({}) == 0
    assert bottleneck_load_of(_r("A", qty=600, thr=100)) == 6
    assert bottleneck_load_of(_r("A", thr=None)) is None


def test_order_fns():
    a = _r("A", code="M01-2DS", due="2026-07-02", qty=100, thr=100)
    b = _r("B", code="M02-2D", due="2026-07-01", qty=500, thr=50)
    c = _r("C", code="M01-2DS", due="2026-07-01", qty=200, thr=None)
    assert [x["order"]["order_no"] for x in order_by_due([a, b, c], {"base_date": "2026-06-01"})] == ["B", "C", "A"]
    assert [x["order"]["order_no"] for x in order_by_util([a, b, c], {})] == ["B", "C", "A"]     # 500>200>100
    assert [x["order"]["order_no"] for x in order_by_setup([b, a, c], {})] == ["C", "A", "B"]    # 族 M01 聚拢；族内交期早者先
    assert [x["order"]["order_no"] for x in order_by_bottleneck([a, c, b], {})] == ["B", "A", "C"]  # 600/100=6 > 100/100=1 > 无
    d = _r("D", code="M01-2DS", due="2026-07-03")
    seq0 = [x["order"]["order_no"] for x in order_by_due([a, d], {"base_date": "2026-06-01"})]
    seq1 = [x["order"]["order_no"] for x in order_by_due([a, d], {"base_date": "2026-06-01", "due_buffer_days": 10})]
    assert seq0 == seq1            # 交期缓冲对顺序无观察效果（评审留痕）


def test_order_fn_interface_contract():
    src = [_r("A", due="2026-07-02"), _r("B", due="2026-07-01")]
    snapshot = [x["order"]["order_no"] for x in src]
    out = get_strategy("due")["orderFn"](src, {"base_date": "2026-06-01"})
    assert [x["order"]["order_no"] for x in out] == ["B", "A"]
    assert [x["order"]["order_no"] for x in src] == snapshot      # 输入不被修改
    assert out is not src


def test_strategy_score_edges():
    assert strategy_score(STRATEGIES["priority"], None) is None
    zero = {"tardy": 0, "setup": 0, "imbal": 0, "makespan": 0}
    assert strategy_score({"objective": zero}, {"onTimeRate": 80}) == 0   # wsum 兜底为 1，分子 0


def test_metrics_makespan_and_error_first_row():
    planned = [_r("A", judge="满足"), _r("B", judge="满足")]
    m = strategy_metrics(planned, [])
    assert m["makespan"] == 9      # 06-01 → 06-10
    err_first = [{"error": "boom"}, _r("A", judge="满足")]
    m2 = strategy_metrics(err_first, [])
    assert m2["makespan"] == 9     # 锚点加固：不受 error 首行影响


def test_strategy_metrics_and_score():
    planned = [_r("A", judge="延期"), _r("B", judge="满足"), _r("C", judge="无交期")]
    planned[2]["order"]["due_date"] = None                 # 无交期订单不计入 onTime（JS 口径）
    # 让 A 有 setup 条
    planned[0]["gantt"]["bars"] = [{"setup_days": 0.5}, {"setup_days": 0}]
    load = [{"load_rate": 1.5, "judge": "超载"}, {"load_rate": 0.5, "judge": "正常"}]
    m = strategy_metrics(planned, load)
    assert m["total"] == 3 and m["late"] == 1 and m["onTime"] == 1
    assert m["onTimeRate"] == pytest.approx(33.3, abs=0.1)
    assert m["overloadWC"] == 1 and m["setupTotal"] == 0.5
    assert m["utilization"] == pytest.approx(1.0)          # mean(1.5,0.5)
    assert m["bottleneckUtil"] == 1.5
    sc = strategy_score(STRATEGIES["priority"], m)
    assert 0 <= sc <= 100


def test_config_schemas():
    assert [f["key"] for f in OBJECTIVE_SCHEMA] == ["tardy", "setup", "imbal", "makespan"]
    assert STRATEGY_CONFIG_SCHEMA["due"][0]["key"] == "due_buffer_days"
    vals = get_strategy_config_values("setup", {"setup_days": 1.5})
    assert vals["fields"]["setup_days"] == 1.5
    vals2 = get_strategy_config_values("setup", {"strategy_setup_tardy": 2})
    assert vals2["objective"]["tardy"] == 2


def test_order_by_priority_week_days_tiebreak():
    """week_days 透传：瓶颈负荷率档位相同时按编号兜底（3B2 修复，探针实证）。"""
    from app.mps.strategy import order_by_priority

    a = _r("A", due="2026-07-01")            # 同优先级/同交期/同交期天数，仅瓶颈负荷不同
    a["input_qty"] = 500
    a["bottleneck"] = {"throughput": 100}
    b = _r("B", due="2026-07-01")
    b["input_qty"] = 1000
    b["bottleneck"] = {"throughput": 100}
    # week_days=6：B(⌈1000/100⌉/6=1.0) 先于 A(5/6≈0.833)
    assert [x["order"]["order_no"] for x in order_by_priority([a, b], {"week_days": 6})] == ["B", "A"]
    # week_days=3：两者均 clamp 至 1.0 → 退到编号兜底 A 先
    assert [x["order"]["order_no"] for x in order_by_priority([a, b], {"week_days": 3})] == ["A", "B"]
    # 缺省等价 6（与 3A 口径一致）
    assert [x["order"]["order_no"] for x in order_by_priority([a, b])] == ["B", "A"]
