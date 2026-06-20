"""ShopFloorSimulator 单元测试。"""

from __future__ import annotations

import datetime
import sys
import os

import pytest

# 确保 app 包可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.engine.models import (
    Buffer,
    BufferType,
    ChangeoverMatrix,
    HardRule,
    OrderItem,
    ProcessRoute,
    ProcessStep,
    SchedulingProblem,
    ScheduledTask,
    WorkCenter,
    WorkCenterStatus,
    WorkCenterType,
)
from app.engine.simulator import (
    BufferStatus,
    ShopFloorSimulator,
    SimEvent,
    SimulationResult,
    WorkcenterStats,
)


# ── 辅助：构造测试数据 ──────────────────────────────────────────────────


def _make_workcenter(
    wid: str = "WC1",
    hourly_cap: float = 10.0,
    oee: float = 1.0,
    compatible: list[str] | None = None,
) -> WorkCenter:
    return WorkCenter(
        id=wid,
        code=wid,
        name=wid,
        type=WorkCenterType.PRODUCTION_LINE,
        oee=oee,
        hourly_capacity=hourly_cap,
        status=WorkCenterStatus.AVAILABLE,
        compatible_products=compatible or [],
    )


def _make_task(
    order_item_id: str = "OI1",
    product: str = "P1",
    workcenter_id: str = "WC1",
    quantity: float = 10.0,
    start_hours: float = 0.0,
    step_order: int = 1,
) -> ScheduledTask:
    start_dt = datetime.datetime(2000, 1, 1) + datetime.timedelta(hours=start_hours)
    return ScheduledTask(
        id=f"{order_item_id}@{workcenter_id}",
        order_item_id=order_item_id,
        product_id=product,
        product=product,
        workcenter_id=workcenter_id,
        step_order=step_order,
        step_no=step_order,
        start_time=start_dt,
        quantity=quantity,
    )


def _make_problem(
    workcenters: list[WorkCenter] | None = None,
    buffers: list[Buffer] | None = None,
    changeover_matrix: list[ChangeoverMatrix] | None = None,
    process_routes: list[ProcessRoute] | None = None,
) -> SchedulingProblem:
    return SchedulingProblem(
        workcenters=workcenters or [_make_workcenter()],
        buffers=buffers or [],
        changeover_matrix=changeover_matrix or [],
        process_routes=process_routes or [],
    )


# ── 测试用例 ──────────────────────────────────────────────────────────────


class TestEmptyPlan:
    """空 plan 场景。"""

    def test_empty_plan_returns_empty_result(self):
        problem = _make_problem()
        sim = ShopFloorSimulator(problem)
        result = sim.simulate([])

        assert result.total_time == 0.0
        assert result.total_output == 0.0
        assert result.total_changeover_count == 0
        assert result.total_changeover_time == 0.0
        assert result.avg_utilization == 0.0
        assert result.buffer_violations == 0
        assert result.hard_violations == []
        assert result.events == []
        assert result.completion_times == {}


class TestSingleTask:
    """单个任务仿真。"""

    def test_single_task_completes(self):
        wc = _make_workcenter("WC1", hourly_cap=10.0, oee=1.0)
        task = _make_task("OI1", "P1", "WC1", quantity=20.0, start_hours=0.0)
        problem = _make_problem(workcenters=[wc])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([task])

        # 加工时长 = 20 / (10 * 1.0) = 2.0 小时
        assert result.total_time == pytest.approx(2.0, abs=0.01)
        assert result.completion_times.get("OI1") == pytest.approx(2.0, abs=0.01)
        assert result.total_changeover_count == 0
        assert len(result.events) == 2  # start + end

    def test_single_task_with_oee(self):
        wc = _make_workcenter("WC1", hourly_cap=10.0, oee=0.8)
        task = _make_task("OI1", "P1", "WC1", quantity=20.0, start_hours=0.0)
        problem = _make_problem(workcenters=[wc])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([task])

        # 加工时长 = 20 / (10 * 0.8) = 2.5 小时
        assert result.total_time == pytest.approx(2.5, abs=0.01)


class TestMultipleTasks:
    """多任务仿真。"""

    def test_sequential_tasks_no_changeover(self):
        """同一产线同产品顺序执行，无换线。"""
        wc = _make_workcenter("WC1", hourly_cap=10.0)
        t1 = _make_task("OI1", "P1", "WC1", quantity=10.0, start_hours=0.0)
        t2 = _make_task("OI2", "P1", "WC1", quantity=10.0, start_hours=1.0)
        problem = _make_problem(workcenters=[wc])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1, t2])

        # t1: 0→1h (10/10=1h), t2 等到1h后获取资源, 1→2h
        # 因为 Resource 容量=1，t2 需等 t1 完成
        assert result.total_time == pytest.approx(2.0, abs=0.01)
        assert result.total_changeover_count == 0

    def test_changeover_between_products(self):
        """同一产线不同产品，需要换线。"""
        wc = _make_workcenter("WC1", hourly_cap=10.0)
        t1 = _make_task("OI1", "P1", "WC1", quantity=10.0, start_hours=0.0)
        t2 = _make_task("OI2", "P2", "WC1", quantity=10.0, start_hours=1.0)
        co = ChangeoverMatrix(from_product_id="P1", to_product_id="P2", changeover_time=0.5)
        problem = _make_problem(workcenters=[wc], changeover_matrix=[co])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1, t2])

        # t1: 0→1h, 换线 0.5h, t2: 1.5→2.5h
        assert result.total_time == pytest.approx(2.5, abs=0.01)
        assert result.total_changeover_count == 1
        assert result.total_changeover_time == pytest.approx(0.5, abs=0.01)

    def test_default_changeover_time(self):
        """换线矩阵中无匹配时使用默认值 0.5h。"""
        wc = _make_workcenter("WC1", hourly_cap=10.0)
        t1 = _make_task("OI1", "P1", "WC1", quantity=10.0, start_hours=0.0)
        t2 = _make_task("OI2", "P2", "WC1", quantity=10.0, start_hours=1.0)
        # 不提供换线矩阵
        problem = _make_problem(workcenters=[wc])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1, t2])

        assert result.total_changeover_count == 1
        assert result.total_changeover_time == pytest.approx(0.5, abs=0.01)

    def test_parallel_workcenters(self):
        """不同产线可以并行执行。"""
        wc1 = _make_workcenter("WC1", hourly_cap=10.0)
        wc2 = _make_workcenter("WC2", hourly_cap=10.0)
        t1 = _make_task("OI1", "P1", "WC1", quantity=10.0, start_hours=0.0)
        t2 = _make_task("OI2", "P2", "WC2", quantity=10.0, start_hours=0.0)
        problem = _make_problem(workcenters=[wc1, wc2])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1, t2])

        # 两条产线并行，总时长 = 1h
        assert result.total_time == pytest.approx(1.0, abs=0.01)


class TestZeroQuantity:
    """quantity=0 的任务应跳过。"""

    def test_zero_quantity_skipped(self):
        wc = _make_workcenter("WC1", hourly_cap=10.0)
        t1 = _make_task("OI1", "P1", "WC1", quantity=0.0, start_hours=0.0)
        t2 = _make_task("OI2", "P1", "WC1", quantity=10.0, start_hours=0.0)
        problem = _make_problem(workcenters=[wc])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1, t2])

        # 只有 t2 执行，1h
        assert result.total_time == pytest.approx(1.0, abs=0.01)
        assert "OI1" not in result.completion_times


class TestHardViolations:
    """硬规则违反检测。"""

    def test_resource_compatibility_violation(self):
        """产品在不兼容产线上生产。"""
        wc = _make_workcenter("WC1", hourly_cap=10.0, compatible=["P2"])
        t1 = _make_task("OI1", "P1", "WC1", quantity=10.0, start_hours=0.0)
        problem = _make_problem(workcenters=[wc])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1])

        assert len(result.hard_violations) >= 1
        assert any("资源兼容" in v for v in result.hard_violations)

    def test_process_order_violation(self):
        """后序工序在前序完成前开始。"""
        wc1 = _make_workcenter("WC1", hourly_cap=10.0)
        wc2 = _make_workcenter("WC2", hourly_cap=10.0)

        route = ProcessRoute(
            id="R1",
            product_id="P1",
            steps=[
                ProcessStep(step_order=1, step_name="工序1", workcenter_id="WC1", standard_hours=1.0),
                ProcessStep(step_order=2, step_name="工序2", workcenter_id="WC2", standard_hours=1.0),
            ],
        )

        # 工序2 在工序1 之前开始
        t1 = _make_task("OI1", "P1", "WC1", quantity=10.0, start_hours=2.0, step_order=1)
        t2 = _make_task("OI1", "P1", "WC2", quantity=10.0, start_hours=0.0, step_order=2)
        problem = _make_problem(workcenters=[wc1, wc2], process_routes=[route])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1, t2])

        assert any("工艺顺序" in v for v in result.hard_violations)


class TestBufferMonitoring:
    """缓冲区监控。"""

    def test_buffer_red_zone_violation(self):
        """缓冲区进入红区时记录违反。"""
        wc1 = _make_workcenter("WC1", hourly_cap=10.0)
        wc2 = _make_workcenter("WC2", hourly_cap=10.0)

        buf = Buffer(
            id="BUF1",
            from_workcenter_id="WC1",
            to_workcenter_id="WC2",
            buffer_type=BufferType.INVENTORY,
            green_zone=50.0,
            yellow_zone=20.0,
            red_zone=10.0,
        )

        # 大量消耗 WC2 的前序缓冲区
        t1 = _make_task("OI1", "P1", "WC2", quantity=100.0, start_hours=0.0)
        problem = _make_problem(workcenters=[wc1, wc2], buffers=[buf])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1])

        # 缓冲区初始水位=50，消耗100后应低于红区
        assert result.buffer_violations >= 1
        assert any("红区" in v for v in result.hard_violations)


class TestUntilParameter:
    """until 参数测试。"""

    def test_until_limits_simulation(self):
        wc = _make_workcenter("WC1", hourly_cap=10.0)
        t1 = _make_task("OI1", "P1", "WC1", quantity=100.0, start_hours=0.0)
        problem = _make_problem(workcenters=[wc])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1], until=2.0)

        # 仿真在 2h 截止，任务需要 10h 但只执行了 2h
        assert result.total_time == pytest.approx(2.0, abs=0.01)


class TestWorkcenterStats:
    """工作中心统计。"""

    def test_stats_calculation(self):
        wc = _make_workcenter("WC1", hourly_cap=10.0)
        t1 = _make_task("OI1", "P1", "WC1", quantity=10.0, start_hours=0.0)
        t2 = _make_task("OI2", "P2", "WC1", quantity=10.0, start_hours=1.0)
        co = ChangeoverMatrix(from_product_id="P1", to_product_id="P2", changeover_time=1.0)
        problem = _make_problem(workcenters=[wc], changeover_matrix=[co])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1, t2])

        stats = result.workcenter_stats.get("WC1")
        assert stats is not None
        assert stats.total_work_time == pytest.approx(2.0, abs=0.01)  # 2 个任务各 1h
        assert stats.total_changeover_time == pytest.approx(1.0, abs=0.01)
        assert stats.changeover_count == 1
        # total_time = 3h (1h + 1h换线 + 1h), utilization = (2+1)/3 = 1.0
        assert stats.utilization == pytest.approx(1.0, abs=0.01)


class TestEventLog:
    """事件日志测试。"""

    def test_event_types(self):
        wc = _make_workcenter("WC1", hourly_cap=10.0)
        t1 = _make_task("OI1", "P1", "WC1", quantity=10.0, start_hours=0.0)
        t2 = _make_task("OI2", "P2", "WC1", quantity=10.0, start_hours=1.0)
        problem = _make_problem(workcenters=[wc])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1, t2])

        event_types = [e.event_type for e in result.events]
        assert "start" in event_types
        assert "end" in event_types
        assert "changeover" in event_types

    def test_events_ordered_by_time(self):
        wc = _make_workcenter("WC1", hourly_cap=10.0)
        t1 = _make_task("OI1", "P1", "WC1", quantity=10.0, start_hours=0.0)
        problem = _make_problem(workcenters=[wc])

        sim = ShopFloorSimulator(problem)
        result = sim.simulate([t1])

        times = [e.time for e in result.events]
        assert times == sorted(times)
