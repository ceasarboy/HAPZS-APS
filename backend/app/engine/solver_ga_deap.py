"""基于 DEAP 框架的遗传算法排产求解器，支持 SimPy 仿真评估。"""

from __future__ import annotations

import math
import random
import time
from datetime import datetime, timedelta
from typing import Any

from loguru import logger

from app.engine.models import (
    BaseSolver,
    BufferType,
    DemandPlan,
    HardRule,
    LineProcessConfig,
    ProductProcess,
    ProcessInfo,
    ProductionLine,
    ProductionLineInfo,
    ScheduledTask,
    SchedulingProblem,
    SolveResult,
    SolveStatus,
    SoftRule,
    SolverCapabilities,
)

# 旧名别名，保持向后兼容
OrderItem = DemandPlan
WorkCenter = ProductionLine
WorkcenterInfo = ProductionLineInfo
ProcessRoute = type("ProcessRoute", (), {})  # 旧名占位，实际使用 ProductProcess

# 条件导入：DEAP 框架
try:
    from deap import algorithms, base, creator, tools

    _DEAP_AVAILABLE = True
except ImportError:
    _DEAP_AVAILABLE = False

# 条件导入：SimPy 仿真器
try:
    from app.engine.simulator import ShopFloorSimulator

    _SIM_AVAILABLE = True
except ImportError:
    _SIM_AVAILABLE = False

# 条件导入：约束构建器
try:
    from app.engine.constraint_builder import ConstraintBuilder

    _CONSTRAINT_BUILDER_AVAILABLE = True
except ImportError:
    _CONSTRAINT_BUILDER_AVAILABLE = False

# ── 常量 ──────────────────────────────────────────────────────────────────────

HARD_VIOLATION_PENALTY = 10000

# 阶段1（快速搜索）
PHASE1_POP_SIZE = 200
PHASE1_MAX_GEN = 120
PHASE1_CROSSOVER_RATE = 0.7
PHASE1_MUTATION_RATE = 0.3

# 阶段2（精细优化）
PHASE2_POP_SIZE = 100
PHASE2_MAX_GEN = 80
PHASE2_CROSSOVER_RATE = 0.5
PHASE2_MUTATION_RATE = 0.2

CONVERGENCE_PATIENCE = 20
DEFAULT_MAX_TIME_SECONDS = 60
TOURNAMENT_SIZE = 5
MUTATE_INDPB = 0.2


# ── DEAP 遗传算法求解器 ──────────────────────────────────────────────────────


class DEAPGASolver(BaseSolver):
    """基于 DEAP 框架的遗传算法求解器，支持 SimPy 仿真评估。

    编码方案：
        染色体 = 订单排列序列（permutation encoding）
        个体是一个整数列表，代表订单明细的排列顺序
        排列顺序决定排产优先级：排在前面的订单优先分配时间槽和产线
        产线分配由解码器根据兼容性和负荷自动决定

    两阶段进化：
        阶段1（快速搜索，前 60% 代数）：使用数学公式评估
        阶段2（精细优化，后 40% 代数）：使用 SimPy 仿真评估（如可用）
    """

    def __init__(self, **kwargs: Any) -> None:
        self.max_time_seconds: float = kwargs.get(
            "max_time_seconds", DEFAULT_MAX_TIME_SECONDS
        )
        self.convergence_patience: int = kwargs.get(
            "convergence_patience", CONVERGENCE_PATIENCE
        )
        random.seed()

    # ── 公开接口 ───────────────────────────────────────────────────────────

    def solve(self, problem: SchedulingProblem) -> SolveResult:
        """两阶段进化求解。"""
        start_ts = time.time()

        if not _DEAP_AVAILABLE:
            logger.error("DEAP 框架未安装，无法求解")
            return SolveResult(
                status=SolveStatus.INFEASIBLE,
                solve_time_seconds=0.0,
                solver_name="deap-ga-simpy",
            )

        if not problem.demand_plans and not problem.order_items:
            logger.warning("订单明细为空，无法求解")
            return SolveResult(
                status=SolveStatus.INFEASIBLE,
                solve_time_seconds=0.0,
                solver_name="deap-ga-simpy",
            )

        # 构建辅助索引
        self._build_indices(problem)

        # 构建 DEAP toolbox
        toolbox = self._setup_deap(problem)

        # 注册评估函数（阶段1：数学公式）
        toolbox.register(
            "evaluate", self._evaluate_math, problem=problem
        )

        # ── 阶段1：快速搜索 ──
        phase1_pop = self._generate_seeded_population(toolbox, problem, PHASE1_POP_SIZE)

        # 评估初始种群
        for ind in phase1_pop:
            ind.fitness.values = toolbox.evaluate(ind)

        best_ind = tools.selBest(phase1_pop, 1)[0]
        no_improve_count = 0

        logger.info(
            "DEAP-GA 阶段1启动: pop_size={}, max_gen={}, items={}, workcenters={}",
            PHASE1_POP_SIZE,
            PHASE1_MAX_GEN,
            len(problem.demand_plans or problem.order_items or []),
            len(problem.production_lines or problem.workcenters or []),
        )

        phase1_gen = 0
        for gen in range(1, PHASE1_MAX_GEN + 1):
            elapsed = time.time() - start_ts
            if elapsed >= self.max_time_seconds:
                logger.info("阶段1 超时终止，代数={}, 耗时={:.1f}s", gen - 1, elapsed)
                break

            phase1_gen = gen
            phase1_pop, gen_best = self._evolve_one_generation(
                phase1_pop, toolbox, PHASE1_CROSSOVER_RATE, PHASE1_MUTATION_RATE
            )

            if gen_best.fitness.values[0] > best_ind.fitness.values[0]:
                best_ind = gen_best
                no_improve_count = 0
            else:
                no_improve_count += 1

            if gen % 10 == 0:
                logger.info(
                    "阶段1 代数={}, 最优适应度={:.2f}",
                    gen,
                    best_ind.fitness.values[0],
                )

            if no_improve_count >= self.convergence_patience:
                logger.info("阶段1 收敛终止，连续 {} 代无改善", self.convergence_patience)
                break

        # ── 阶段2：精细优化 ──
        use_sim = _SIM_AVAILABLE
        if use_sim:
            try:
                simulator = ShopFloorSimulator(problem)
                toolbox.register(
                    "evaluate",
                    self._evaluate_sim,
                    problem=problem,
                    simulator=simulator,
                )
                logger.info("阶段2 使用 SimPy 仿真评估")
            except Exception:
                use_sim = False
                logger.warning("SimPy 仿真器初始化失败，回退到数学公式评估")

        if not use_sim:
            # 回退到数学公式评估（重新注册确保可用）
            toolbox.register(
                "evaluate", self._evaluate_math, problem=problem
            )
            logger.info("阶段2 使用数学公式评估（SimPy 不可用）")

        # 从阶段1最优个体初始化阶段2种群
        phase2_pop = self._init_phase2_population(toolbox, problem, best_ind)

        for ind in phase2_pop:
            if not ind.fitness.valid:
                ind.fitness.values = toolbox.evaluate(ind)

        best_phase2 = tools.selBest(phase2_pop, 1)[0]
        if best_phase2.fitness.values[0] > best_ind.fitness.values[0]:
            best_ind = best_phase2

        no_improve_count = 0

        logger.info(
            "DEAP-GA 阶段2启动: pop_size={}, max_gen={}, sim={}",
            PHASE2_POP_SIZE,
            PHASE2_MAX_GEN,
            use_sim,
        )

        phase2_gen = 0
        for gen in range(1, PHASE2_MAX_GEN + 1):
            elapsed = time.time() - start_ts
            if elapsed >= self.max_time_seconds:
                logger.info("阶段2 超时终止，代数={}, 耗时={:.1f}s", gen - 1, elapsed)
                break

            phase2_gen = gen
            phase2_pop, gen_best = self._evolve_one_generation(
                phase2_pop, toolbox, PHASE2_CROSSOVER_RATE, PHASE2_MUTATION_RATE
            )

            if gen_best.fitness.values[0] > best_ind.fitness.values[0]:
                best_ind = gen_best
                no_improve_count = 0
            else:
                no_improve_count += 1

            if gen % 10 == 0:
                logger.info(
                    "阶段2 代数={}, 最优适应度={:.2f}",
                    gen,
                    best_ind.fitness.values[0],
                )

            if no_improve_count >= self.convergence_patience:
                logger.info("阶段2 收敛终止，连续 {} 代无改善", self.convergence_patience)
                break

        elapsed = time.time() - start_ts

        # 解码最优个体
        tasks = self._decode(best_ind, problem)
        hard_violations = self._count_hard_violations_from_tasks(tasks, problem)
        objective_values = self._compute_objectives(tasks, problem)

        # GA 是启发式算法，有任务即为 FEASIBLE（硬约束违反只影响质量，不代表无解）
        status = SolveStatus.FEASIBLE if tasks else SolveStatus.INFEASIBLE

        total_gen = phase1_gen + phase2_gen
        logger.info(
            "DEAP-GA 求解完成: status={}, fitness={:.2f}, hard_violations={}, "
            "tasks={}, 耗时={:.2f}s, 总代数={}",
            status.value,
            best_ind.fitness.values[0],
            hard_violations,
            len(tasks),
            elapsed,
            total_gen,
        )

        # 构建规则评分报告
        rule_report = self._build_ga_rule_report(tasks, problem, hard_violations)

        return SolveResult(
            status=status,
            tasks=tasks,
            objective_values=objective_values,
            fitness=best_ind.fitness.values[0],
            hard_violations=hard_violations,
            solve_time_seconds=elapsed,
            generations=total_gen,
            solver_name="deap-ga-simpy",
            metadata={
                "pop_size_phase1": PHASE1_POP_SIZE,
                "pop_size_phase2": PHASE2_POP_SIZE,
                "sim_enabled": use_sim,
                "hard_rules": rule_report["hard_rules"],
                "soft_scores": rule_report["soft_scores"],
            },
        )

    def get_capabilities(self) -> SolverCapabilities:
        """返回求解器能力声明。"""
        return SolverCapabilities(
            solver_name="deap-ga-simpy",
            supported_hard_rules=[
                HardRule.FINITE_CAPACITY,
                HardRule.PROCESS_ORDER,
                HardRule.RESOURCE_COMPATIBILITY,
            ],
            supported_soft_rules=list(SoftRule),
            max_items=200,
            max_workcenters=20,
            max_time_slots=96,
        )

    # ── DEAP 框架配置 ─────────────────────────────────────────────────────

    def _setup_deap(self, problem: SchedulingProblem) -> base.Toolbox:
        """配置 DEAP 框架。"""
        # 创建 Fitness 类（最大化），避免重复创建
        if not hasattr(creator, "FitnessMax"):
            creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        # 创建 Individual 类
        if not hasattr(creator, "Individual"):
            creator.create("Individual", list, fitness=creator.FitnessMax)

        toolbox = base.Toolbox()
        n_items = len(problem.demand_plans or problem.order_items)

        # 基因生成：随机排列
        toolbox.register("indices", random.sample, range(n_items), n_items)
        toolbox.register(
            "individual",
            tools.initIterate,
            creator.Individual,
            toolbox.indices,
        )
        toolbox.register("population", tools.initRepeat, list, toolbox.individual)

        # 交叉：部分匹配交叉 PMX（保留排列特征）
        toolbox.register("mate", tools.cxPartialyMatched)

        # 变异：shuffle 变异
        toolbox.register("mutate", tools.mutShuffleIndexes, indpb=MUTATE_INDPB)

        # 选择：锦标赛选择（tournsize 不超过种群大小）
        tournsize = min(TOURNAMENT_SIZE, PHASE1_POP_SIZE)
        toolbox.register("select", tools.selTournament, tournsize=tournsize)

        return toolbox

    # ── 辅助索引 ───────────────────────────────────────────────────────────

    def _build_indices(self, problem: SchedulingProblem) -> None:
        """构建产线索引和兼容性索引。"""
        items = problem.demand_plans or problem.order_items or []
        workcenters = problem.production_lines or problem.workcenters or []

        self._wc_by_id: dict[str, ProductionLineInfo] = {
            wc.id: wc for wc in workcenters
        }
        self._item_by_idx: dict[int, DemandPlan] = {
            i: item for i, item in enumerate(items)
        }
        self._item_by_id: dict[str, DemandPlan] = {
            item.id: item for item in items
        }
        self._compatible_wcs: dict[int, list[str]] = {}
        for i, item in enumerate(items):
            if item.compatible_workcenters:
                self._compatible_wcs[i] = item.compatible_workcenters
            else:
                compatible = [
                    wc.id
                    for wc in workcenters
                    if not wc.compatible_products
                    or item.product_id in wc.compatible_products
                ]
                self._compatible_wcs[i] = compatible or [
                    wc.id for wc in workcenters
                ]
        self._num_slots = len(problem.time_slots) if problem.time_slots else 96
        self._time_slots = problem.time_slots

        # 构建产线 → 全局时间槽索引列表的映射
        self._wc_slot_indices: dict[str, list[int]] = {}
        # V3: 时间槽产能映射 (wc_id, slot_idx) → available_capacity
        self._slot_capacity: dict[tuple[str, int], float] = {}
        for ts in problem.time_slots:
            if ts.workcenter_id:
                idx = ts.index if ts.index is not None else (ts.slot_id if ts.slot_id is not None else 0)
                self._wc_slot_indices.setdefault(ts.workcenter_id, []).append(idx)
                if ts.available_capacity > 0:
                    self._slot_capacity[(ts.workcenter_id, idx)] = ts.available_capacity

        # 换线时间查找表
        self._changeover_time: dict[tuple[str, str], float] = {}
        self._changeover_time_lpc: dict[tuple[str, str], float] = {}
        for entry in problem.changeover_matrix:
            if entry.from_product_id and entry.to_product_id:
                self._changeover_time[(entry.from_product_id, entry.to_product_id)] = (
                    entry.changeover_time or entry.setup_time
                )
            if entry.from_lpc_id and entry.to_lpc_id:
                self._changeover_time_lpc[(entry.from_lpc_id, entry.to_lpc_id)] = (
                    entry.changeover_time or entry.setup_time
                )
        for rule in problem.changeover_rules:
            key = (rule.from_product, rule.to_product)
            self._changeover_time[key] = rule.changeover_hours

        # V3 LPC 索引：(line_id, process_id) → LineProcessConfig
        self._lpc_by_line_process: dict[tuple[str, str], LineProcessConfig] = {}
        for lpc in problem.line_process_configs:
            self._lpc_by_line_process[(lpc.line_id, lpc.process_id)] = lpc

        # 工艺路径索引：product_id → list[ProductProcess]（V2，替代 ProcessRoute）
        self._route_by_product: dict[str, list[ProductProcess]] = {}
        for pp in problem.product_processes:
            self._route_by_product.setdefault(pp.product_id, []).append(pp)
        for pid in self._route_by_product:
            self._route_by_product[pid].sort(key=lambda p: p.seq)

        # V2 工序信息索引：process_id → ProcessInfo
        self._process_info_by_id: dict[str, ProcessInfo] = {
            pi.id: pi for pi in problem.process_info
        }

        # V2 产线工艺配置索引：process_id → [line_id, ...]
        self._process_lines: dict[str, list[str]] = {}
        for lpc in problem.line_process_configs:
            self._process_lines.setdefault(lpc.process_id, []).append(lpc.line_id)

        # 冻结窗口
        self._freeze_horizon = problem.freeze_horizon

        # V3 时间槽日期映射：构建 (wc_id, local_slot_idx) → TimeSlot
        # 用于从逻辑槽号反推 start_time/end_time 字符串
        self._wc_slot_map: dict[str, dict[int, Any]] = {}  # wc_id → {local_idx: TimeSlot}
        for ts in problem.time_slots:
            if ts.workcenter_id:
                local_idx = len(self._wc_slot_map.setdefault(ts.workcenter_id, {}))
                self._wc_slot_map[ts.workcenter_id][local_idx] = ts

        # 推断时间槽粒度（日级=720分钟 vs 小时级=60分钟 vs 5分钟级=5分钟）
        self._slot_duration_minutes = 5  # 默认5分钟
        if problem.time_slots:
            _slot_keys = set()
            for ts in problem.time_slots[:100]:
                _slot_keys.add((ts.date, ts.workcenter_id, ts.process_id))
            if len(_slot_keys) == len(problem.time_slots[:100]):
                self._slot_duration_minutes = 720  # 日级时间槽

        # 推断 base_date（从时间槽最小日期）
        self._base_date: datetime | None = None
        if problem.time_slots:
            dates = [ts.date for ts in problem.time_slots if ts.date]
            if dates:
                self._base_date = datetime.strptime(min(dates), "%Y-%m-%d")

    # ── 解码器 ─────────────────────────────────────────────────────────────

    def _decode(
        self, individual: list[int], problem: SchedulingProblem
    ) -> list[ScheduledTask]:
        """将排列序列解码为具体的排产方案。

        V3 DAG 工序级排产：每个需求的每道工序独立排到产线+时段。
        按排列顺序遍历需求计划：
        1. 获取该需求的工艺路线（工序列表）
        2. 按 DAG 拓扑层级排产（同层级工序可并行）
        3. 每道工序选择兼容的产线（支持该工序的产线）
        4. 后继工序必须在所有前驱工序完成之后开始
        """
        tasks: list[ScheduledTask] = []
        # 产线每个时间槽已分配的数量：wc_id → {slot: qty}
        wc_slot_usage: dict[str, dict[int, float]] = {}
        # 产线上最后一个产品（用于计算换线时间）
        wc_last_product: dict[str, str] = {}

        for idx in individual:
            item = self._item_by_idx.get(idx)
            if item is None:
                continue

            product_id = item.product_id or item.product_code
            pp_list = self._route_by_product.get(product_id, [])

            if not pp_list:
                # 没有工艺路线，作为单工序排产（向后兼容）
                compatible = self._compatible_wcs.get(idx, [])
                if not compatible:
                    continue
                best_wc_id = min(
                    compatible,
                    key=lambda wc_id: sum(wc_slot_usage.get(wc_id, {}).values()),
                )
                task_list = self._assign_single_process(
                    item, best_wc_id, product_id, "", "", "", 0, "",
                    wc_slot_usage, wc_last_product, problem,
                )
                tasks.extend(task_list)
                continue

            # V3 DAG 工序级排产：按拓扑层级排产
            # 构建该产品的 DAG 拓扑层级
            topo_levels = self._topological_sort(pp_list, product_id, problem)

            # 记录每个工序的结束时间槽和起始时间槽（用于前驱约束）
            process_end_slots: dict[str, int] = {}
            process_start_slots: dict[str, int] = {}

            for level in topo_levels:
                for pp in level:
                    process_id = pp.process_id
                    seq = pp.seq
                    pi = self._process_info_by_id.get(process_id)
                    process_code = pi.proc_code if pi else ""
                    process_name = pi.proc_name if pi else ""
                    constraint_type = pi.constraint_type if pi else ""

                    # 找到支持该工序+工艺类型的产线
                    # V3: 优先匹配工序+工艺类型，其次只匹配工序
                    auto_type = pp.auto_type or "非自动"
                    all_lines = self._process_lines.get(process_id, [])
                    compatible = []
                    for wc_id in all_lines:
                        lpc = self._lpc_by_line_process.get((wc_id, process_id))
                        if lpc and lpc.auto_type == auto_type:
                            compatible.append(wc_id)
                    if not compatible:
                        # 回退：只匹配工序
                        compatible = all_lines
                    if not compatible:
                        compatible = self._compatible_wcs.get(idx, [])

                    if not compatible:
                        continue

                    # 计算最小起始时间槽（根据 dependency_type + 延迟时间）
                    min_start_slot = self._get_min_start_slot(
                        process_id, product_id, process_end_slots, process_start_slots, pp_list, problem,
                    )

                    # 选择最优产线
                    best_wc_id = min(
                        compatible,
                        key=lambda wc_id: max(
                            min_start_slot,
                            self._get_next_available_slot(wc_id, wc_slot_usage, min_start_slot),
                        ),
                    )

                    task_list = self._assign_single_process(
                        item, best_wc_id, product_id, process_id,
                        process_code, process_name, seq, constraint_type,
                        wc_slot_usage, wc_last_product, problem,
                        min_start_slot=min_start_slot,
                        dependency_type=pp.dependency_type or "FS",
                        wait_time=pp.wait_time or 0,
                        prep_time=pp.prep_time or 0,
                        auto_type=pp.auto_type or "非自动",
                        cycle_time=pp.cycle_time or 0.0,
                        max_units_per_beat=pp.max_units_per_beat or 1,
                    )
                    tasks.extend(task_list)

                    # 记录该工序的起始和结束时间
                    if task_list:
                        process_start_slots[process_id] = min(t.start_slot for t in task_list)
                        process_end_slots[process_id] = max(t.end_slot for t in task_list)

        return tasks

    def _topological_sort(
        self, pp_list: list[ProductProcess], product_id: str, problem: SchedulingProblem,
    ) -> list[list[ProductProcess]]:
        """对产品的工序列表进行拓扑排序，返回层级列表。

        同一层级的工序互为并行（无前驱依赖关系）。
        优先使用显式 ProcessDependency，否则从 seq 自动推导。
        """
        # 构建显式依赖索引
        explicit_deps: dict[str, list[str]] = {}
        for dep in problem.process_dependencies:
            if dep.product_id == product_id:
                explicit_deps.setdefault(dep.to_process, []).append(dep.from_process)

        has_explicit = bool(explicit_deps)

        # 构建 process_id → ProductProcess 映射
        pp_map: dict[str, ProductProcess] = {pp.process_id: pp for pp in pp_list}

        if has_explicit:
            # 使用显式依赖构建 DAG
            in_degree: dict[str, int] = {pp.process_id: 0 for pp in pp_list}
            adj: dict[str, list[str]] = {pp.process_id: [] for pp in pp_list}
            for to_proc, from_procs in explicit_deps.items():
                if to_proc in in_degree:
                    for from_proc in from_procs:
                        if from_proc in adj:
                            adj[from_proc].append(to_proc)
                            in_degree[to_proc] += 1

            # Kahn 算法拓扑排序
            levels: list[list[ProductProcess]] = []
            queue = [pid for pid, deg in in_degree.items() if deg == 0]
            visited: set[str] = set()

            while queue:
                level = [pp_map[pid] for pid in queue if pid in pp_map]
                if level:
                    levels.append(level)
                next_queue = []
                for pid in queue:
                    visited.add(pid)
                    for neighbor in adj.get(pid, []):
                        in_degree[neighbor] -= 1
                        if in_degree[neighbor] == 0 and neighbor not in visited:
                            next_queue.append(neighbor)
                queue = next_queue

            # 处理未访问的节点（环或孤立节点）
            for pp in pp_list:
                if pp.process_id not in visited:
                    levels.append([pp])

            return levels
        else:
            # 从 seq 自动推导：同 seq 值的工序在同一层级
            seq_groups: dict[int, list[ProductProcess]] = {}
            for pp in pp_list:
                seq_groups.setdefault(pp.seq, []).append(pp)
            return [seq_groups[seq] for seq in sorted(seq_groups.keys())]

    def _get_min_start_slot(
        self,
        process_id: str,
        product_id: str,
        process_end_slots: dict[str, int],
        process_start_slots: dict[str, int],
        pp_list: list[ProductProcess],
        problem: SchedulingProblem,
    ) -> int:
        """计算工序的最小起始时间槽，根据 dependency_type 和延迟时间。

        FS: start ≥ pred_end + delay_slots
        SS: start ≥ pred_start + delay_slots
        FF: 不限制 start（约束 end ≥ pred_end，解码时难以直接约束）
        SF: 不限制 start（约束 end ≥ pred_start，解码时难以直接约束）
        """
        SLOT_DURATION_MINUTES = self._slot_duration_minutes

        # 优先使用显式依赖
        explicit_preds: list[str] = []
        for dep in problem.process_dependencies:
            if dep.product_id == product_id and dep.to_process == process_id:
                explicit_preds.append(dep.from_process)

        # 获取当前工序的 dependency_type
        pp_map = {pp.process_id: pp for pp in pp_list}
        current_pp = pp_map.get(process_id)
        dep_type = current_pp.dependency_type if current_pp else "FS"

        # 获取前驱工序列表
        if explicit_preds:
            pred_process_ids = explicit_preds
        else:
            # 回退：从 seq 推导前驱
            if not current_pp:
                return 0
            pred_process_ids = [pp.process_id for pp in pp_list if pp.seq < current_pp.seq]

        if not pred_process_ids:
            return 0

        # 根据依赖类型计算最小起始时间槽
        min_start = 0
        succ_pp = current_pp  # 后继工序的 ProductProcess

        for pred_pid in pred_process_ids:
            pred_pp = pp_map.get(pred_pid)

            if dep_type == "FS":
                # FS: start ≥ pred_end + delay_slots
                # prep_time 已计入生产时间内（自动工艺每轮换治具，非自动工艺一次性准备），
                # 此处延迟只算 wait_time（工序间等待，如冷却/固化）
                pred_end = process_end_slots.get(pred_pid, 0)
                wait_time = pred_pp.wait_time if pred_pp else 0
                if wait_time > 0:
                    if pred_pp and not pred_pp.wait_includes_offhours:
                        # 只算工作时间（8:00-20:00 = 12小时/天）
                        work_hours_per_day = 12
                        work_minutes_per_day = work_hours_per_day * SLOT_DURATION_MINUTES
                        days = int(wait_time // work_minutes_per_day)
                        remaining = wait_time % work_minutes_per_day
                        delay_slots = days * work_hours_per_day + int(remaining + SLOT_DURATION_MINUTES - 1) // SLOT_DURATION_MINUTES
                    else:
                        delay_slots = int(wait_time + SLOT_DURATION_MINUTES - 1) // SLOT_DURATION_MINUTES
                else:
                    delay_slots = 1  # FS 最少延迟1个时间槽
                min_start = max(min_start, pred_end + delay_slots)

            elif dep_type == "SS":
                # SS: 后工序可在前工序开始后开始，prep_time已在生产时间内
                pred_start = process_start_slots.get(pred_pid, 0)
                min_start = max(min_start, pred_start)

            elif dep_type in ("FF", "SF"):
                # FF/SF: 不直接约束 start，由后续工序对齐
                # 简化处理：至少保证 start ≥ pred_start
                pred_start = process_start_slots.get(pred_pid, 0)
                min_start = max(min_start, pred_start)

        return min_start

    def _get_next_available_slot(
        self, wc_id: str, wc_slot_usage: dict[str, dict[int, float]], min_slot: int = 0,
    ) -> int:
        """获取产线上从 min_slot 开始的下一个可用时间槽。"""
        usage = wc_slot_usage.get(wc_id, {})
        cap = self._get_wc_capacity(wc_id)
        for s in range(min_slot, self._num_slots):
            if usage.get(s, 0.0) < cap:
                return s
        return self._num_slots  # 超出范围

    def _assign_single_process(
        self,
        item: DemandPlan,
        wc_id: str,
        product_id: str,
        process_id: str,
        process_code: str,
        process_name: str,
        seq: int,
        constraint_type: str,
        wc_slot_usage: dict[str, dict[int, float]],
        wc_last_product: dict[str, str],
        problem: SchedulingProblem,
        min_start_slot: int = 0,
        dependency_type: str = "FS",
        wait_time: float = 0.0,
        prep_time: float = 0.0,
        auto_type: str = "非自动",
        cycle_time: float = 0.0,
        max_units_per_beat: int = 1,
    ) -> list[ScheduledTask]:
        """为单个需求×单个工序分配产线时间槽。"""
        tasks: list[ScheduledTask] = []
        remaining = int(round(item.quantity))
        current_slot = min_start_slot

        # 考虑冻结窗口
        if self._freeze_horizon > 0 and current_slot < self._freeze_horizon:
            current_slot = self._freeze_horizon

        # V3 换线时间查找：优先用 LPC 维度，其次用产品维度
        last_product = wc_last_product.get(wc_id, "")
        if last_product and last_product != product_id:
            co_time = 0.0
            # 先查 LPC 维度
            from_lpc = self._lpc_by_line_process.get((wc_id, process_id))
            if from_lpc:
                # 注意：这里 last_product 实际是上一个产品的 ID
                # LPC 维度换线需要知道上一个任务在哪个 LPC 上
                # 简化处理：如果 LPC 换线表有数据，用产品维度查不到时回退
                pass
            if co_time == 0.0:
                co_time = self._changeover_time.get((last_product, product_id), 0.0)
            co_slots = max(1, int(co_time + 0.5)) if co_time > 0 else 0
            current_slot += co_slots

        # 预构建全局时间槽索引映射
        wc_slots = self._wc_slot_indices.get(wc_id, [])

        # V3 时间独占模式：任务占用连续N个5分钟时间槽
        # 计算需要占用的连续时间槽数
        # 自动工艺: 每轮 = cycle_time + prep_time(换治具, 分钟转秒)
        # 非自动工艺: 总时间 = beat_count * cycle_time + prep_time * 60 (一次性准备)
        qty = int(round(item.quantity))
        if auto_type == "自动" and max_units_per_beat > 0:
            beat_count = -(-qty // max_units_per_beat)  # 向上取整
        else:
            beat_count = qty
        if auto_type == "自动":
            total_time_seconds = beat_count * (cycle_time + prep_time * 60)
        else:
            total_time_seconds = beat_count * cycle_time + prep_time * 60
        total_time_minutes = total_time_seconds / 60.0
        SLOT_DURATION = self._slot_duration_minutes
        slots_needed = max(1, math.ceil(total_time_minutes / SLOT_DURATION))

        # 在产线上找连续N个未占用的时间槽
        slot_usage = wc_slot_usage.setdefault(wc_id, {})
        max_slot = len(self._time_slots) - 1 if self._time_slots else self._num_slots - 1

        # 从 current_slot 开始搜索连续N个未占用的时间槽
        found_start = -1
        search_slot = current_slot
        while search_slot + slots_needed - 1 <= max_slot:
            # 检查 [search_slot, search_slot + slots_needed) 范围内是否全部未占用
            all_free = True
            for s in range(search_slot, search_slot + slots_needed):
                if slot_usage.get(s, 0) >= 1:  # 0/1占用标记
                    all_free = False
                    break
            if all_free:
                found_start = search_slot
                break
            search_slot += 1

        if found_start < 0:
            # 找不到连续空闲时间槽，任务未排
            return tasks

        # 标记占用
        for s in range(found_start, found_start + slots_needed):
            slot_usage[s] = 1

        # 将逻辑槽号映射到全局时间槽索引
        global_idx = wc_slots[found_start] if found_start < len(wc_slots) else found_start

        # 计算 start_time/end_time 字符串
        start_time_str = ""
        end_time_str = ""
        wc_slot_map = self._wc_slot_map.get(wc_id, {})
        ts_obj = wc_slot_map.get(found_start)
        if ts_obj:
            sr_date = ts_obj.date or ""
            sr_start = ts_obj.start_time or ""
            if sr_date and sr_start:
                if "全" in sr_start:
                    start_time_str = f"{sr_date} 08:00"
                else:
                    start_time_str = f"{sr_date} {sr_start}"
            elif sr_date:
                start_time_str = f"{sr_date} 08:00"
        elif self._base_date:
            start_dt = self._base_date + timedelta(minutes=found_start * SLOT_DURATION)
            start_time_str = start_dt.strftime("%Y-%m-%d %H:%M")

        # end_time = start_time + total_time_minutes
        if start_time_str and total_time_minutes > 0:
            try:
                s_dt = datetime.strptime(start_time_str, "%Y-%m-%d %H:%M")
                e_dt = s_dt + timedelta(minutes=total_time_minutes)
                end_time_str = e_dt.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                pass

        tasks.append(
            ScheduledTask(
                order_item_id=item.id,
                workcenter_id=wc_id,
                start_slot=found_start,
                end_slot=found_start + slots_needed,
                time_slot=global_idx,
                slot_id=global_idx,
                quantity=qty,
                product=product_id,
                order_id=item.dp_code or item.id,
                process_id=process_id,
                process_code=process_code,
                process_name=process_name,
                seq=seq,
                constraint_type=constraint_type,
                dependency_type=dependency_type,
                wait_time=wait_time,
                prep_time=prep_time,
                # V3 节拍计算过程变量
                auto_type=auto_type,
                cycle_time=cycle_time,
                max_units_per_beat=max_units_per_beat,
                beat_count=beat_count,
                total_time=total_time_seconds,
                # V3 规则评分用字段
                demand_id=item.id,
                due_date=item.due_date or "",
                start_time=start_time_str,
                end_time=end_time_str,
                slot_count=slots_needed,
            )
        )

        # 更新产线最后产品
        if tasks:
            wc_last_product[wc_id] = product_id

        return tasks

    def _get_buffer_slots(self, item: DemandPlan, problem: SchedulingProblem) -> int:
        """获取需求计划在瓶颈工序前的缓冲时间槽数。"""
        product_id = item.product_id or item.product_code
        pp_list = self._route_by_product.get(product_id, [])
        if not pp_list:
            return 0
        # 如果有关键工序（is_key），在其前插入缓冲
        for pp in pp_list:
            if pp.is_key:
                # 缓冲时间 = 节拍时间的 20%（最少1个时间槽）
                cycle_time = pp.cycle_time / 3600.0 if pp.cycle_time > 100 else pp.cycle_time  # 秒→小时
                buf = max(1, int(cycle_time * 0.2 + 0.5))
                return buf
        return 0

    # ── 适应度评估 ─────────────────────────────────────────────────────────

    def _evaluate_math(
        self, individual: list[int], problem: SchedulingProblem
    ) -> tuple[float]:
        """数学公式评估（快速，用于前期进化）。"""
        tasks = self._decode(individual, problem)
        soft_score = self._compute_soft_score_from_tasks(tasks, problem)
        hard_violations = self._count_hard_violations_from_tasks(tasks, problem)
        fitness = soft_score - hard_violations * HARD_VIOLATION_PENALTY
        return (fitness,)

    def _evaluate_sim(
        self,
        individual: list[int],
        problem: SchedulingProblem,
        simulator: Any,
    ) -> tuple[float]:
        """SimPy 仿真评估（精确，用于后期精化）。"""
        tasks = self._decode(individual, problem)
        try:
            sim_result = simulator.simulate(tasks)
            # 从仿真结果计算适应度
            weighted_kpi = self._compute_sim_kpi_score(sim_result, problem)
            hard_violations = self._count_hard_violations_from_tasks(tasks, problem)
            fitness = weighted_kpi - hard_violations * HARD_VIOLATION_PENALTY
        except Exception:
            # 仿真失败，回退到数学公式
            logger.warning("SimPy 仿真评估失败，回退到数学公式")
            return self._evaluate_math(individual, problem)
        return (fitness,)

    def _compute_sim_kpi_score(
        self, sim_result: Any, problem: SchedulingProblem
    ) -> float:
        """从仿真结果计算 KPI 加权得分。"""
        weights = problem.soft_rule_weights or {}
        active_rules = set(problem.soft_rules) if problem.soft_rules else set(SoftRule)

        score = 0.0

        # OTD：用仿真总产量 / 总需求近似
        if SoftRule.OTD_PRIORITY in active_rules:
            total_demand = sum(
                getattr(item, "quantity", 0)
                for item in (problem.demand_plans or problem.order_items or [])
            )
            output = getattr(sim_result, "total_output", 0)
            otd = min(1.0, output / max(total_demand, 1))
            w = weights.get(SoftRule.OTD_PRIORITY.value, 0.35)
            score += otd * w

        # 换线最小化
        if SoftRule.SETUP_MINIMIZATION in active_rules:
            co_count = getattr(sim_result, "total_changeover_count", 0)
            max_co = len(problem.demand_plans or problem.order_items or []) * 2
            co_score = 1.0 - min(co_count / max(max_co, 1), 1.0)
            w = weights.get(SoftRule.SETUP_MINIMIZATION.value, 0.25)
            score += co_score * w

        # 产线均衡
        if SoftRule.LOAD_BALANCING in active_rules:
            balance = getattr(sim_result, "avg_utilization", 0.0)
            w = weights.get(SoftRule.LOAD_BALANCING.value, 0.15)
            score += balance * w

        # Drum 利用率
        if SoftRule.DRUM_UTILIZATION in active_rules:
            drum_util = getattr(sim_result, "avg_utilization", 0.0)
            w = weights.get(SoftRule.DRUM_UTILIZATION.value, 0.10)
            score += drum_util * w

        return score

    # ── 软规则评分（基于解码后的 tasks）───────────────────────────────────

    def _compute_soft_score_from_tasks(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> float:
        """基于解码后的任务列表计算软规则加权得分。

        使用与 ortools 一致的 SoftRule 枚举：
        - OTD_PRIORITY → 准时交付
        - SETUP_MINIMIZATION → 换线最小化
        - LOAD_BALANCING → 负荷均衡
        - DRUM_UTILIZATION → 瓶颈利用率
        同时兼容旧枚举（MINIMIZE_CHANGEOVER/PRIORITY_FIRST 等）。
        """
        if not tasks:
            return 0.0

        weights = problem.soft_rule_weights
        active_rules = set(problem.soft_rules) if problem.soft_rules else set(SoftRule)
        score = 0.0

        # 准时交付
        if SoftRule.OTD_PRIORITY in active_rules:
            s = self._score_otd_tasks(tasks, problem)
            w = weights.get(SoftRule.OTD_PRIORITY.value, 0.35)
            score += s * w

        # 换线最小化（兼容旧枚举）
        if SoftRule.SETUP_MINIMIZATION in active_rules or SoftRule.MINIMIZE_CHANGEOVER in active_rules:
            s = self._score_changeover_tasks(tasks, problem)
            w = weights.get(SoftRule.SETUP_MINIMIZATION.value,
                           weights.get(SoftRule.MINIMIZE_CHANGEOVER.value, 0.25))
            score += s * w

        # 负荷均衡（兼容旧枚举）
        if SoftRule.LOAD_BALANCING in active_rules or SoftRule.BALANCE_LOAD in active_rules:
            s = self._score_balance_tasks(tasks, problem)
            w = weights.get(SoftRule.LOAD_BALANCING.value,
                           weights.get(SoftRule.BALANCE_LOAD.value, 0.15))
            score += s * w

        # 瓶颈利用率
        if SoftRule.DRUM_UTILIZATION in active_rules:
            s = self._score_balance_tasks(tasks, problem)  # 复用均衡得分
            w = weights.get(SoftRule.DRUM_UTILIZATION.value, 0.10)
            score += s * w

        # 优先级（兼容旧枚举）
        if SoftRule.PRIORITY_FIRST in active_rules:
            s = self._score_priority_tasks(tasks, problem)
            w = weights.get(SoftRule.PRIORITY_FIRST.value, 1.0)
            score += s * w

        # 交期优先（兼容旧枚举）
        if SoftRule.DUE_DATE_FIRST in active_rules:
            s = self._score_due_date_tasks(tasks, problem)
            w = weights.get(SoftRule.DUE_DATE_FIRST.value, 1.0)
            score += s * w

        # 最大完工时间（兼容旧枚举）
        if SoftRule.MINIMIZE_MAKESPAN in active_rules:
            s = self._score_makespan_tasks(tasks, problem)
            w = weights.get(SoftRule.MINIMIZE_MAKESPAN.value, 1.0)
            score += s * w

        return score

    def _score_otd_tasks(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> float:
        """OTD 得分：按需求计划统计，最后一个工序结束时间 ≤ 交期。"""
        demand_tasks: dict[str, list[ScheduledTask]] = {}
        for t in tasks:
            did = getattr(t, 'demand_id', '') or getattr(t, 'order_item_id', '') or ''
            if did:
                demand_tasks.setdefault(did, []).append(t)
        on_time = 0
        total = 0
        for did, dtasks in demand_tasks.items():
            last_task = max(dtasks, key=lambda t: t.seq)
            due = getattr(last_task, 'due_date', '') or ''
            end_time = getattr(last_task, 'end_time', '') or getattr(last_task, 'start_time', '') or ''
            if not due or not end_time:
                continue
            total += 1
            try:
                due_dt = datetime.strptime(str(due)[:10], "%Y-%m-%d")
                end_dt = datetime.strptime(str(end_time)[:10], "%Y-%m-%d")
                if end_dt <= due_dt:
                    on_time += 1
            except ValueError:
                pass
        return on_time / total if total > 0 else 0.0

    def _score_changeover_tasks(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> float:
        """换线得分：按产线分组，相邻产品变化越少分越高。"""
        wc_tasks: dict[str, list[ScheduledTask]] = {}
        for task in tasks:
            wc_tasks.setdefault(task.workcenter_id, []).append(task)

        total_changes = 0
        total_adjacent = 0
        for wc_id, wc_task_list in wc_tasks.items():
            sorted_tasks = sorted(wc_task_list, key=lambda t: t.start_slot)
            for i in range(1, len(sorted_tasks)):
                total_adjacent += 1
                if sorted_tasks[i - 1].product != sorted_tasks[i].product:
                    total_changes += 1

        if total_adjacent == 0:
            return 1.0
        return 1.0 - (total_changes / total_adjacent)

    def _score_priority_tasks(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> float:
        """优先级得分：高优先级订单排得越靠前越好。"""
        n = len(tasks)
        if n == 0:
            return 0.0

        priority_map = {
            "紧急": 5.0, "特急": 5.0, "P1": 5.0,
            "P2": 3.0, "高": 3.0,
            "普通": 1.0, "P3": 1.0,
            "低": 0.5,
        }

        score = 0.0
        for idx, task in enumerate(tasks):
            item = self._item_by_id.get(task.order_item_id)
            if item:
                rank_ratio = 1.0 - (idx / n)
                p_val = priority_map.get(item.priority, 1.0)
                score += rank_ratio * p_val
        return score / n

    def _score_due_date_tasks(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> float:
        """交期得分：交期越早的排在越前面得分越高。"""
        items_with_due = [
            t for t in tasks
            if self._item_by_id.get(t.order_item_id)
            and self._item_by_id[t.order_item_id].due_date
        ]
        if not items_with_due:
            return 1.0

        n = len(tasks)
        sorted_by_due = sorted(
            items_with_due,
            key=lambda t: self._item_by_id[t.order_item_id].due_date,  # type: ignore[arg-type]
        )
        correct_count = 0
        for i, task in enumerate(sorted_by_due):
            pos_in_tasks = next(
                (j for j, t in enumerate(tasks) if t.order_item_id == task.order_item_id),
                0,
            )
            if pos_in_tasks <= i + n * 0.2:
                correct_count += 1
        return correct_count / len(items_with_due)

    def _score_balance_tasks(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> float:
        """负载均衡得分：各产线负载越均衡分越高。"""
        wc_load: dict[str, float] = {}
        for task in tasks:
            wc_load[task.workcenter_id] = wc_load.get(task.workcenter_id, 0.0) + task.quantity

        if not wc_load:
            return 1.0
        loads = list(wc_load.values())
        avg = sum(loads) / len(loads)
        if avg == 0:
            return 1.0
        variance = sum((l - avg) ** 2 for l in loads) / len(loads)
        cv = (variance ** 0.5) / avg
        return max(0.0, 1.0 - cv)

    def _score_makespan_tasks(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> float:
        """最大完工时间得分：makespan 越小分越高。"""
        if not tasks:
            return 1.0
        max_end = max(t.end_slot for t in tasks)
        if self._num_slots == 0:
            return 1.0
        return max(0.0, 1.0 - (max_end / self._num_slots))

    # ── 硬规则违反计数（基于解码后的 tasks）──────────────────────────────

    def _build_ga_rule_report(
        self,
        tasks: list[ScheduledTask],
        problem: SchedulingProblem,
        hard_violations: int,
    ) -> dict[str, Any]:
        """构建GA求解器的规则评分报告。"""
        hard_rules_list: list[dict[str, Any]] = []
        active_hard = set(problem.hard_rules) if problem.hard_rules else set(HardRule)

        # 硬规则1: 有限时间
        cap_violations = self._count_capacity_violations_tasks(tasks, problem) if HardRule.FINITE_CAPACITY in active_hard else 0
        hard_rules_list.append({
            "name": "有限时间", "code": "FINITE_CAPACITY",
            "status": "PASS" if cap_violations == 0 else "FAIL",
            "violations": cap_violations,
            "detail": f"产能违反 {cap_violations} 次",
        })

        # 硬规则2: 工序顺序
        order_violations = self._count_process_order_violations_tasks(tasks, problem) if HardRule.PROCESS_ORDER in active_hard else 0
        hard_rules_list.append({
            "name": "工序顺序", "code": "PROCESS_ORDER",
            "status": "PASS" if order_violations == 0 else "FAIL",
            "violations": order_violations,
            "detail": f"工序顺序违反 {order_violations} 次",
        })

        # 硬规则3: 资源兼容性
        compat_violations = self._count_compatibility_violations_tasks(tasks, problem) if HardRule.RESOURCE_COMPATIBILITY in active_hard else 0
        hard_rules_list.append({
            "name": "资源兼容性", "code": "RESOURCE_COMPATIBILITY",
            "status": "PASS" if compat_violations == 0 else "FAIL",
            "violations": compat_violations,
            "detail": f"兼容性违反 {compat_violations} 次",
        })

        # 软规则评分
        weights = problem.soft_rule_weights or {}
        active_soft = set(problem.soft_rules) if problem.soft_rules else set(SoftRule)
        soft_scores: dict[str, Any] = {}
        total_assigned = len(tasks)

        # 准时交付（按需求计划统计：所有工序都准时才算准时）
        if SoftRule.OTD_PRIORITY in active_soft:
            on_time_count = 0
            late_count = 0
            # 按 demand_id 分组
            demand_tasks: dict[str, list[ScheduledTask]] = {}
            for t in tasks:
                did = getattr(t, 'demand_id', '') or getattr(t, 'order_item_id', '') or ''
                if did:
                    demand_tasks.setdefault(did, []).append(t)
            for did, dtasks in demand_tasks.items():
                # 取该需求最后一个工序的 end_time 与 due_date 比较
                last_task = max(dtasks, key=lambda t: t.seq)
                due = getattr(last_task, 'due_date', '') or ''
                end_time = getattr(last_task, 'end_time', '') or getattr(last_task, 'start_time', '') or ''
                if not due or not end_time:
                    continue
                try:
                    due_dt = datetime.strptime(str(due)[:10], "%Y-%m-%d")
                    end_dt = datetime.strptime(str(end_time)[:10], "%Y-%m-%d")
                    if end_dt <= due_dt:
                        on_time_count += 1
                    else:
                        late_count += 1
                except ValueError:
                    pass
            total_demands = on_time_count + late_count
            otd_score = on_time_count / total_demands if total_demands > 0 else 0.0
            soft_scores["OTD_PRIORITY"] = {
                "name": "准时交付",
                "score": round(otd_score, 4),
                "detail": f"{on_time_count}/{total_demands} 按时完成, {late_count} 超期",
                "weight": weights.get(SoftRule.OTD_PRIORITY.value, 0.35),
            }

        # 换线最小化
        if SoftRule.SETUP_MINIMIZATION in active_soft:
            changeover_count = 0
            wc_tasks: dict[str, list[tuple[int, str]]] = {}
            for t in tasks:
                wc_id = t.workcenter_id or ""
                slot = t.time_slot or t.slot_id or 0
                demand_id = getattr(t, 'order_item_id', '') or getattr(t, 'item_id', '') or ''
                wc_tasks.setdefault(wc_id, []).append((slot, demand_id))
            for wc_id, task_list in wc_tasks.items():
                task_list.sort()
                for k in range(1, len(task_list)):
                    if task_list[k][1] != task_list[k - 1][1]:
                        changeover_count += 1
            setup_score = max(0.0, 1.0 - changeover_count / max(total_assigned, 1))
            soft_scores["SETUP_MINIMIZATION"] = {
                "name": "换线最小化",
                "score": round(setup_score, 4),
                "detail": f"换线次数={changeover_count}",
                "weight": weights.get(SoftRule.SETUP_MINIMIZATION.value, 0.25),
            }

        # 负荷均衡
        if SoftRule.LOAD_BALANCING in active_soft:
            wc_task_counts: dict[str, int] = {}
            for t in tasks:
                wc_id = t.workcenter_id or ""
                wc_task_counts[wc_id] = wc_task_counts.get(wc_id, 0) + 1
            if len(wc_task_counts) > 1:
                counts = list(wc_task_counts.values())
                avg = sum(counts) / len(counts)
                variance = sum((x - avg) ** 2 for x in counts) / len(counts)
                std = variance ** 0.5
                cv = std / avg if avg > 0 else 0
                load_score = max(0.0, 1.0 - cv)
            else:
                load_score = 1.0
            soft_scores["LOAD_BALANCING"] = {
                "name": "负荷均衡",
                "score": round(load_score, 4),
                "detail": f"产线任务数: {wc_task_counts}",
                "weight": weights.get(SoftRule.LOAD_BALANCING.value, 0.15),
            }

        return {
            "hard_rules": hard_rules_list,
            "soft_scores": soft_scores,
        }

    def _count_hard_violations_from_tasks(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> int:
        """统计硬规则违反次数。"""
        violations = 0
        active_hard = set(problem.hard_rules) if problem.hard_rules else set(HardRule)

        if HardRule.FINITE_CAPACITY in active_hard:
            violations += self._count_capacity_violations_tasks(tasks, problem)

        if HardRule.PROCESS_ORDER in active_hard:
            violations += self._count_process_order_violations_tasks(tasks, problem)

        if HardRule.RESOURCE_COMPATIBILITY in active_hard:
            violations += self._count_compatibility_violations_tasks(tasks, problem)

        return violations

    def _get_wc_capacity(self, wc_id: str, slot_idx: int | None = None) -> float:
        """获取产线单槽产能。

        V3时间独占模式: 每个时间槽只能被一个任务占用，产能=1.0。
        """
        # V3时间独占模式：产能=1.0（一个时间槽一个任务）
        return 1.0

    def _count_capacity_violations_tasks(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> int:
        """统计产能违反次数。

        V3时间独占模式: 检查同一产线同一时间槽是否被多个任务占用。
        """
        slot_usage: dict[str, dict[int, int]] = {}  # wc_id → {slot: 占用次数}
        for task in tasks:
            wc_slots = slot_usage.setdefault(task.workcenter_id, {})
            for s in range(task.start_slot, task.end_slot):
                wc_slots[s] = wc_slots.get(s, 0) + 1

        violations = 0
        for wc_id, slots in slot_usage.items():
            for _slot, count in slots.items():
                if count > 1:  # V3: 一个时间槽只能被1个任务占用
                    violations += count - 1
        return violations

    def _count_process_order_violations_tasks(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> int:
        """统计工序顺序违反次数。"""
        order_tasks: dict[str, list[ScheduledTask]] = {}
        for task in tasks:
            item = self._item_by_id.get(task.order_item_id)
            if item:
                order_tasks.setdefault(item.dp_code or item.id, []).append(task)

        violations = 0
        for _order_no, order_task_list in order_tasks.items():
            if len(order_task_list) <= 1:
                continue
            sorted_tasks = sorted(order_task_list, key=lambda t: t.seq)
            for i in range(1, len(sorted_tasks)):
                if sorted_tasks[i].start_slot < sorted_tasks[i - 1].end_slot:
                    violations += 1
        return violations

    def _count_compatibility_violations_tasks(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> int:
        """统计兼容性违反次数。

        V2 工序级排产：检查 (产线, 工序) 对是否在产线工艺配置中。
        """
        violations = 0
        for task in tasks:
            process_id = task.process_id
            wc_id = task.workcenter_id
            if not process_id or not wc_id:
                continue
            # V2: 检查 (wc_id, process_id) 是否在 _lpc_by_line_process 中
            lpc = self._lpc_by_line_process.get((wc_id, process_id))
            if lpc is None:
                # 旧模式回退：检查产线是否在兼容列表中
                item = self._item_by_id.get(task.order_item_id)
                if item is None:
                    continue
                idx = next(
                    (i for i, it in enumerate(problem.demand_plans or problem.order_items or []) if it.id == item.id),
                    None,
                )
                if idx is not None:
                    compatible = self._compatible_wcs.get(idx, [])
                    if compatible and wc_id not in compatible:
                        violations += 1
        return violations

    # ── 进化操作 ───────────────────────────────────────────────────────────

    def _evolve_one_generation(
        self,
        population: list,
        toolbox: base.Toolbox,
        cx_rate: float,
        mut_rate: float,
    ) -> tuple[list, Any]:
        """执行一代进化，返回 (新种群, 当代最优个体)。"""
        # 选择
        offspring = toolbox.select(population, len(population))
        offspring = [toolbox.clone(ind) for ind in offspring]

        # 交叉（个体长度 < 2 时跳过，cxPartialyMatched 要求至少 2 个基因）
        for i in range(1, len(offspring), 2):
            if random.random() < cx_rate and len(offspring[i - 1]) >= 2:
                offspring[i - 1], offspring[i] = toolbox.mate(
                    offspring[i - 1], offspring[i]
                )
                del offspring[i - 1].fitness.values
                del offspring[i].fitness.values

        # 变异（个体长度 < 2 时跳过，mutShuffleIndexes 要求至少 2 个基因）
        for ind in offspring:
            if random.random() < mut_rate and len(ind) >= 2:
                toolbox.mutate(ind)
                del ind.fitness.values

        # 评估无效适应度的个体
        invalid = [ind for ind in offspring if not ind.fitness.valid]
        for ind in invalid:
            ind.fitness.values = toolbox.evaluate(ind)

        # 替换
        population[:] = offspring

        best = tools.selBest(population, 1)[0]
        return population, best

    # ── 初始种群多样化 ─────────────────────────────────────────────────────

    def _generate_seeded_population(
        self, toolbox: base.Toolbox, problem: SchedulingProblem, n: int
    ) -> list:
        """生成混合初始种群。

        30% 按优先级排序（P1 优先）
        30% 按交期排序（紧急优先）
        20% 按换线属性聚类（成组技术）
        20% 随机
        """
        population: list = []
        n_priority = int(n * 0.3)
        n_due_date = int(n * 0.3)
        n_cluster = int(n * 0.2)
        n_random = n - n_priority - n_due_date - n_cluster

        items = problem.demand_plans or problem.order_items or []

        # 30% 按优先级排序
        priority_map = {"紧急": 0, "特急": 0, "P1": 0, "P2": 1, "高": 1, "普通": 2, "P3": 2, "低": 3}
        sorted_by_priority = sorted(
            range(len(items)),
            key=lambda i: priority_map.get(items[i].priority, 2),
        )
        for _ in range(n_priority):
            ind = creator.Individual(list(sorted_by_priority))
            # 加入少量随机扰动
            self._perturb(ind, 0.1)
            population.append(ind)

        # 30% 按交期排序
        sorted_by_due = sorted(
            range(len(items)),
            key=lambda i: items[i].due_date or "",
        )
        for _ in range(n_due_date):
            ind = creator.Individual(list(sorted_by_due))
            self._perturb(ind, 0.1)
            population.append(ind)

        # 20% 按产品聚类（减少换线）
        sorted_by_product = sorted(
            range(len(items)),
            key=lambda i: items[i].product_id or "",
        )
        for _ in range(n_cluster):
            ind = creator.Individual(list(sorted_by_product))
            self._perturb(ind, 0.1)
            population.append(ind)

        # 20% 随机
        for _ in range(n_random):
            ind = toolbox.individual()
            population.append(ind)

        return population

    def _perturb(self, individual: list, prob: float) -> None:
        """对个体施加少量随机扰动（swap）。"""
        n = len(individual)
        if n < 2:
            return
        for _ in range(max(1, int(n * prob))):
            if random.random() < prob:
                i, j = random.sample(range(n), 2)
                individual[i], individual[j] = individual[j], individual[i]

    def _init_phase2_population(
        self,
        toolbox: base.Toolbox,
        problem: SchedulingProblem,
        best_ind: Any,
    ) -> list:
        """从阶段1最优个体初始化阶段2种群。"""
        population: list = []

        # 保留最优个体
        elite = toolbox.clone(best_ind)
        population.append(elite)

        # 最优个体的扰动版本
        for _ in range(PHASE2_POP_SIZE // 2 - 1):
            ind = toolbox.clone(best_ind)
            self._perturb(ind, 0.3)
            del ind.fitness.values
            population.append(ind)

        # 随机个体补充
        while len(population) < PHASE2_POP_SIZE:
            ind = toolbox.individual()
            population.append(ind)

        return population

    # ── 目标值计算 ─────────────────────────────────────────────────────────

    def _compute_objectives(
        self, tasks: list[ScheduledTask], problem: SchedulingProblem
    ) -> dict[str, float]:
        """计算各软规则的独立目标值。"""
        objectives: dict[str, float] = {}
        active_rules = set(problem.soft_rules) if problem.soft_rules else set(SoftRule)

        if SoftRule.OTD_PRIORITY in active_rules:
            objectives["otd_score"] = self._score_otd_tasks(tasks, problem)

        if SoftRule.SETUP_MINIMIZATION in active_rules or SoftRule.MINIMIZE_CHANGEOVER in active_rules:
            objectives["changeover_score"] = self._score_changeover_tasks(tasks, problem)

        if SoftRule.LOAD_BALANCING in active_rules or SoftRule.BALANCE_LOAD in active_rules:
            objectives["balance_score"] = self._score_balance_tasks(tasks, problem)

        if SoftRule.DRUM_UTILIZATION in active_rules:
            objectives["drum_score"] = self._score_balance_tasks(tasks, problem)

        if SoftRule.PRIORITY_FIRST in active_rules:
            objectives["priority_score"] = self._score_priority_tasks(tasks, problem)

        if SoftRule.DUE_DATE_FIRST in active_rules:
            objectives["due_date_score"] = self._score_due_date_tasks(tasks, problem)

        if SoftRule.MINIMIZE_MAKESPAN in active_rules:
            objectives["makespan_score"] = self._score_makespan_tasks(tasks, problem)

        return objectives
