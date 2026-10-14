"""排产引擎基准测试框架。

提供预置测试用例、求解器对比运行和 Markdown 报告生成。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

from loguru import logger

from app.engine.evaluator import Evaluator
from app.engine.models import (
    BaseSolver,
    Buffer,
    BufferType,
    ChangeoverRule,
    DemandPlan,
    EvaluationResult,
    HardRule,
    KPI,
    ProductionLine,
    SchedulingProblem,
    ScheduledTask,
    SoftRule,
    TimeSlot,
)

# 旧名别名，保持向后兼容
OrderItem = DemandPlan
WorkCenter = ProductionLine


# ---------------------------------------------------------------------------
# 数据类
# ---------------------------------------------------------------------------

@dataclass
class BenchmarkCase:
    """基准测试用例。"""

    name: str
    problem: SchedulingProblem
    description: str = ""


@dataclass
class BenchmarkResult:
    """基准测试结果。"""

    case_name: str
    solver_name: str
    status: str  # OK / ERROR / TIMEOUT
    solve_time: float
    evaluation: EvaluationResult
    kpi: KPI


# ---------------------------------------------------------------------------
# 预置测试用例生成
# ---------------------------------------------------------------------------

def create_T1_basic() -> BenchmarkCase:
    """T1 基础用例：10 项目 × 4 产线 × 12 槽，无换线。"""
    products = [f"P{i:03d}" for i in range(1, 11)]
    wc_ids = ["WC-A", "WC-B", "WC-C", "WC-D"]

    orders = [
        DemandPlan(
            id=f"ORD-{i:03d}",
            dp_code=f"ORD-{i:03d}",
            product_id=products[i % len(products)],
            quantity=50.0 + i * 10,
            priority="P3",
            compatible_workcenters=wc_ids[:],
        )
        for i in range(1, 11)
    ]

    workcenters = [
        ProductionLine(
            id=wc_id,
            line_code=wc_id,
            line_name=f"产线 {wc_id}",
            daily_capacity=100,
            compatible_products=products[:],
        )
        for wc_id in wc_ids
    ]

    time_slots = [
        TimeSlot(
            index=i,
            start_time=f"2026-06-{13 + i // 2:02d} {'08:00' if i % 2 == 0 else '20:00'}",
            end_time=f"2026-06-{13 + i // 2:02d} {'20:00' if i % 2 == 0 else '08:00+1'}",
        )
        for i in range(12)
    ]

    problem = SchedulingProblem(
        demand_plans=orders,
        production_lines=workcenters,
        time_slots=time_slots,
        hard_rules=[HardRule.FINITE_CAPACITY, HardRule.RESOURCE_COMPATIBILITY],
        soft_rules=[SoftRule.OTD_PRIORITY, SoftRule.LOAD_BALANCING, SoftRule.WIP_CONTROL],
        objective_weights={
            SoftRule.OTD_PRIORITY: 0.35,
            SoftRule.SETUP_MINIMIZATION: 0.25,
            SoftRule.LOAD_BALANCING: 0.15,
            SoftRule.WIP_CONTROL: 0.10,
            SoftRule.DRUM_UTILIZATION: 0.10,
            SoftRule.PLAN_STABILITY: 0.05,
        },
    )

    return BenchmarkCase(
        name="T1-basic",
        problem=problem,
        description="10 项目 × 4 产线 × 12 槽，无换线约束，验证基本可行性",
    )


def create_T2_changeover() -> BenchmarkCase:
    """T2 换线用例：20 项目 × 4 产线 × 12 槽，含换线矩阵。"""
    products = [f"P{i:03d}" for i in range(1, 21)]
    wc_ids = ["WC-A", "WC-B", "WC-C", "WC-D"]

    orders = [
        DemandPlan(
            id=f"ORD-{i:03d}",
            dp_code=f"ORD-{i:03d}",
            product_id=products[i % len(products)],
            quantity=30.0 + i * 5,
            priority="P1" if i % 5 == 0 else "P3",
            compatible_workcenters=wc_ids[:],
        )
        for i in range(1, 21)
    ]

    workcenters = [
        ProductionLine(
            id=wc_id,
            line_code=wc_id,
            line_name=f"产线 {wc_id}",
            daily_capacity=80,
            compatible_products=products[:],
        )
        for wc_id in wc_ids
    ]

    time_slots = [
        TimeSlot(
            index=i,
            start_time=f"2026-06-{13 + i // 2:02d} {'08:00' if i % 2 == 0 else '20:00'}",
            end_time=f"2026-06-{13 + i // 2:02d} {'20:00' if i % 2 == 0 else '08:00+1'}",
        )
        for i in range(12)
    ]

    # 换线矩阵：相邻产品编号差距越大，换线时间越长
    changeover_rules = []
    for i in range(len(products)):
        for j in range(len(products)):
            if i != j:
                gap = abs(i - j)
                co_hours = 0.5 if gap <= 3 else (1.0 if gap <= 7 else 2.0)
                changeover_rules.append(ChangeoverRule(
                    from_product=products[i],
                    to_product=products[j],
                    changeover_hours=co_hours,
                ))

    problem = SchedulingProblem(
        demand_plans=orders,
        production_lines=workcenters,
        time_slots=time_slots,
        hard_rules=[HardRule.FINITE_CAPACITY, HardRule.RESOURCE_COMPATIBILITY],
        soft_rules=[SoftRule.OTD_PRIORITY, SoftRule.SETUP_MINIMIZATION, SoftRule.LOAD_BALANCING, SoftRule.WIP_CONTROL],
        changeover_rules=changeover_rules,
        objective_weights={
            SoftRule.OTD_PRIORITY: 0.35,
            SoftRule.SETUP_MINIMIZATION: 0.25,
            SoftRule.LOAD_BALANCING: 0.15,
            SoftRule.WIP_CONTROL: 0.10,
            SoftRule.DRUM_UTILIZATION: 0.10,
            SoftRule.PLAN_STABILITY: 0.05,
        },
    )

    return BenchmarkCase(
        name="T2-changeover",
        problem=problem,
        description="20 项目 × 4 产线 × 12 槽，含换线矩阵，验证软规则优化",
    )


def create_T3_dbr() -> BenchmarkCase:
    """T3 DBR 用例：20 项目 × 4 产线 × 3 工序，含瓶颈 + 缓冲。"""
    products = [f"P{i:03d}" for i in range(1, 21)]
    wc_ids = ["WC-A", "WC-B", "WC-C", "WC-D"]

    orders = [
        DemandPlan(
            id=f"ORD-{i:03d}",
            dp_code=f"ORD-{i:03d}",
            product_id=products[i % len(products)],
            quantity=40.0 + i * 5,
            priority="P1" if i % 4 == 0 else ("P2" if i % 3 == 0 else "P3"),
            compatible_workcenters=wc_ids[:],
        )
        for i in range(1, 21)
    ]

    # WC-B 为瓶颈（Drum），产能较低
    workcenters = [
        ProductionLine(
            id="WC-A",
            line_code="WC-A",
            line_name="前序产线 A",
            daily_capacity=100,
            compatible_products=products[:],
        ),
        ProductionLine(
            id="WC-B",
            line_code="WC-B",
            line_name="瓶颈产线 B (Drum)",
            daily_capacity=60,
            compatible_products=products[:],
        ),
        ProductionLine(
            id="WC-C",
            line_code="WC-C",
            line_name="后序产线 C",
            daily_capacity=100,
            compatible_products=products[:],
        ),
        ProductionLine(
            id="WC-D",
            line_code="WC-D",
            line_name="辅助产线 D",
            daily_capacity=80,
            compatible_products=products[:],
        ),
    ]

    time_slots = [
        TimeSlot(
            index=i,
            start_time=f"2026-06-{13 + i // 2:02d} {'08:00' if i % 2 == 0 else '20:00'}",
            end_time=f"2026-06-{13 + i // 2:02d} {'20:00' if i % 2 == 0 else '08:00+1'}",
        )
        for i in range(12)
    ]

    # 换线矩阵
    changeover_rules = []
    for i in range(len(products)):
        for j in range(len(products)):
            if i != j:
                gap = abs(i - j)
                co_hours = 0.5 if gap <= 3 else (1.0 if gap <= 7 else 2.0)
                changeover_rules.append(ChangeoverRule(
                    from_product=products[i],
                    to_product=products[j],
                    changeover_hours=co_hours,
                ))

    # 缓冲配置
    buffers = [
        Buffer(
            id="BUF-1",
            from_workcenter_id="WC-A",
            to_workcenter_id="WC-B",
            buffer_type=BufferType.TIME,
            green_zone=0.7,
            yellow_zone=0.5,
            red_zone=0.3,
        ),
        Buffer(
            id="BUF-2",
            from_workcenter_id="WC-B",
            to_workcenter_id="WC-C",
            buffer_type=BufferType.TRANSFER,
            green_zone=0.7,
            yellow_zone=0.5,
            red_zone=0.3,
        ),
    ]

    problem = SchedulingProblem(
        demand_plans=orders,
        production_lines=workcenters,
        time_slots=time_slots,
        hard_rules=[
            HardRule.FINITE_CAPACITY,
            HardRule.RESOURCE_COMPATIBILITY,
            HardRule.PROCESS_ORDER,
        ],
        soft_rules=[SoftRule.OTD_PRIORITY, SoftRule.SETUP_MINIMIZATION, SoftRule.LOAD_BALANCING, SoftRule.WIP_CONTROL, SoftRule.DRUM_UTILIZATION],
        changeover_rules=changeover_rules,
        drum_workcenter_ids=["WC-B"],
        buffers=buffers,
        objective_weights={
            SoftRule.OTD_PRIORITY: 0.35,
            SoftRule.SETUP_MINIMIZATION: 0.25,
            SoftRule.LOAD_BALANCING: 0.15,
            SoftRule.WIP_CONTROL: 0.10,
            SoftRule.DRUM_UTILIZATION: 0.10,
            SoftRule.PLAN_STABILITY: 0.05,
        },
    )

    return BenchmarkCase(
        name="T3-dbr",
        problem=problem,
        description="20 项目 × 4 产线 × 3 工序，含瓶颈识别 + 混合方向 + 缓冲",
    )


# ---------------------------------------------------------------------------
# 基准测试运行器
# ---------------------------------------------------------------------------

class BenchmarkRunner:
    """基准测试运行器。"""

    def __init__(self) -> None:
        self.solvers: List[BaseSolver] = []
        self.cases: List[BenchmarkCase] = []
        self._evaluator = Evaluator()

    def add_solver(self, solver: BaseSolver) -> None:
        """添加求解器。"""
        self.solvers.append(solver)
        logger.info("添加求解器: {}", solver.__class__.__name__)

    def add_case(self, case: BenchmarkCase) -> None:
        """添加测试用例。"""
        self.cases.append(case)
        logger.info("添加测试用例: {}", case.name)

    def run_all(self) -> Dict[str, List[BenchmarkResult]]:
        """运行所有求解器 × 测试用例的组合。

        Returns:
            Dict[str, List[BenchmarkResult]]: key 为用例名称，value 为各求解器的结果
        """
        results: Dict[str, List[BenchmarkResult]] = {}

        for case in self.cases:
            case_results: List[BenchmarkResult] = []
            for solver in self.solvers:
                logger.info("运行: case={}, solver={}", case.name, solver.__class__.__name__)
                result = self._run_single(case, solver)
                case_results.append(result)
            results[case.name] = case_results

        return results

    def _run_single(self, case: BenchmarkCase, solver: BaseSolver) -> BenchmarkResult:
        """运行单个求解器 × 测试用例。"""
        try:
            start = time.perf_counter()
            solve_result = solver.solve(case.problem)
            elapsed = time.perf_counter() - start

            evaluation = self._evaluator.evaluate(solve_result.tasks, case.problem)

            solver_name = solve_result.solver_name or solve_result.metadata.get("solver_name", solver.__class__.__name__)

            return BenchmarkResult(
                case_name=case.name,
                solver_name=solver_name,
                status=solve_result.status.value,
                solve_time=elapsed,
                evaluation=evaluation,
                kpi=evaluation.kpi,
            )
        except Exception as e:
            logger.error("运行失败: case={}, solver={}, error={}", case.name, solver.__class__.__name__, e)
            return BenchmarkResult(
                case_name=case.name,
                solver_name=solver.__class__.__name__,
                status="ERROR",
                solve_time=0.0,
                evaluation=EvaluationResult(),
                kpi=KPI(),
            )

    def generate_report(self, results: Dict[str, List[BenchmarkResult]]) -> str:
        """生成 Markdown 格式的对比报告。

        Args:
            results: run_all() 的返回结果

        Returns:
            str: Markdown 格式的报告文本
        """
        lines: List[str] = []
        lines.append("# 排产引擎基准测试报告\n")

        # 汇总表
        lines.append("## 汇总对比\n")
        solver_names = sorted({r.solver_name for rs in results.values() for r in rs})
        case_names = list(results.keys())

        # 表头
        header = "| 用例 | " + " | ".join(solver_names) + " |"
        sep = "| --- | " + " | ".join(["---"] * len(solver_names)) + " |"
        lines.append(header)
        lines.append(sep)

        for case_name in case_names:
            case_results = results[case_name]
            name_to_score = {r.solver_name: f"{r.evaluation.overall_score:.2f}" for r in case_results}
            row = f"| {case_name} | " + " | ".join(name_to_score.get(s, "-") for s in solver_names) + " |"
            lines.append(row)

        lines.append("")

        # KPI 详细对比
        lines.append("## KPI 详细对比\n")

        kpi_fields = [
            ("OTD 达成率", "otd_rate", "pct"),
            ("换线次数", "changeover_count", "d"),
            ("换线总时长(h)", "changeover_hours", ".2f"),
            ("瓶颈利用率", "drum_utilization", "pct"),
            ("产线均衡率", "line_balance_rate", "pct"),
            ("WIP 水平", "wip_level", ".0f"),
            ("总产量", "total_output", ".0f"),
        ]

        for case_name in case_names:
            lines.append(f"### {case_name}\n")

            case_results = results[case_name]
            header = "| 指标 | " + " | ".join(solver_names) + " |"
            sep = "| --- | " + " | ".join(["---"] * len(solver_names)) + " |"
            lines.append(header)
            lines.append(sep)

            for label, attr, fmt in kpi_fields:
                row = f"| {label} | "
                values = []
                for s_name in solver_names:
                    val = None
                    for r in case_results:
                        if r.solver_name == s_name:
                            val = getattr(r.kpi, attr)
                            break
                    if val is not None:
                        if fmt == "pct":
                            values.append(f"{val:.2%}")
                        elif fmt == "d":
                            values.append(f"{int(val)}")
                        else:
                            values.append(f"{val:{fmt}}")
                    else:
                        values.append("-")
                row += " | ".join(values) + " |"
                lines.append(row)

            # 求解时间
            row = "| 求解时间(s) | "
            values = []
            for s_name in solver_names:
                val = None
                for r in case_results:
                    if r.solver_name == s_name:
                        val = r.solve_time
                        break
                values.append(f"{val:.3f}" if val is not None else "-")
            row += " | ".join(values) + " |"
            lines.append(row)

            # 硬规则违反数
            row = "| 硬规则违反 | "
            values = []
            for s_name in solver_names:
                val = None
                for r in case_results:
                    if r.solver_name == s_name:
                        val = len(r.evaluation.hard_violations)
                        break
                values.append(str(val) if val is not None else "-")
            row += " | ".join(values) + " |"
            lines.append(row)

            lines.append("")

        # 状态汇总
        lines.append("## 求解状态\n")
        header = "| 用例 | " + " | ".join(solver_names) + " |"
        sep = "| --- | " + " | ".join(["---"] * len(solver_names)) + " |"
        lines.append(header)
        lines.append(sep)

        for case_name in case_names:
            case_results = results[case_name]
            name_to_status = {r.solver_name: r.status for r in case_results}
            row = f"| {case_name} | " + " | ".join(name_to_status.get(s, "-") for s in solver_names) + " |"
            lines.append(row)

        lines.append("")
        return "\n".join(lines)
