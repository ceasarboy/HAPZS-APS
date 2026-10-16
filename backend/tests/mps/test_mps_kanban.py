"""日任务看板（kanban.js 移植）：任务展开/筛选/状态分级/汇总。"""
import pytest

from app.mps.kanban import build_kanban, parse_res


def test_parse_res():
    assert parse_res("模块级|DB|自动DB") == {"level": "模块级", "op": "DB", "mode": "自动DB"}
    assert parse_res("前置分部件|M02-2D") == {"level": "前置", "op": "分部件", "mode": "M02-2D"}
    assert parse_res(None) is None


def _fixture():
    planned = [{
        "order": {"order_no": "A", "product": "P", "code": "M02-2D", "kit_date": "2026-06-01", "due_date": "2026-06-20"},
        "input_qty": 1052, "plan": {"judge": "满足", "strategy_name": "优先级", "kit_risk": False},
        "gantt": {"bars": [
            {"kind": "step", "seq": 1, "step_std": "DB", "res": "模块级|DB|自动DB",
             "from": "2026-06-01", "to": "2026-06-12", "busy_days": 11},
            {"kind": "step", "seq": 2, "step_std": "WB", "res": "模块级|WB|自动WB",
             "from": "2026-06-12", "to": "2026-06-18", "busy_days": 6},
        ]},
    }]
    ledger = {"模块级|DB|自动DB": [{"used": 5738.18, "slots": []}] * 11 + [],
              "模块级|WB|自动WB": [{"used": 0, "slots": []}] * 17}
    flux_of = {"模块级|DB|自动DB": 6000, "模块级|WB|自动WB": 12000}
    return planned, ledger, flux_of


def test_build_kanban_tasks_and_status():
    planned, ledger, flux_of = _fixture()
    kb = build_kanban(planned, ledger, flux_of, {"base_date": "2026-06-01", "date": "2026-06-02"})
    assert kb["ok"] is True and kb["summary"]["task_count"] == 1
    t = kb["tasks"][0]
    assert t["res"] == "模块级|DB|自动DB" and t["order_no"] == "A"
    assert t["load_rate"] == pytest.approx(round(5738.18 / 6000, 3))
    assert t["status"] == "正常" and t["warnings"] == []


def test_build_kanban_overload_and_filters():
    planned, ledger, flux_of = _fixture()
    ledger["模块级|DB|自动DB"][1] = {"used": 7000, "slots": []}
    kb = build_kanban(planned, ledger, flux_of, {"base_date": "2026-06-01", "date": "2026-06-02"})
    assert kb["tasks"][0]["status"] == "超负荷"
    assert kb["summary"]["overload_count"] == 1
    kb2 = build_kanban(planned, ledger, flux_of, {"base_date": "2026-06-01", "date": "2026-06-02", "level": "组件级"})
    assert kb2["tasks"] == [] and kb2["summary"]["task_count"] == 0
    assert kb["filters"]["levels"] == ["模块级"] and kb["groups"][0]["res"] == "模块级|DB|自动DB"
