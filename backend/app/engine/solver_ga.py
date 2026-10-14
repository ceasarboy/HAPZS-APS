"""遗传算法排产求解器，适合大规模搜索和软规则优化。"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from app.engine.models import (
    BaseSolver,
    HardRule,
    OrderItem,
    ScheduledTask,
    SchedulingProblem,
    SolveResult,
    SolveStatus,
    SoftRule,
    SolverCapabilities,
    WorkcenterInfo,
)

# ── 常量 ──────────────────────────────────────────────────────────────────────

HARD_VIOLATION_PENALTY = 10000
DEFAULT_POP_SIZE = 100
DEFAULT_MAX_GENERATIONS = 200
DEFAULT_TOURNAMENT_SIZE = 5
DEFAULT_ELITE_RATIO = 0.10
DEFAULT_CROSSOVER_RATE = 0.85
DEFAULT_MUTATION_RATE = 0.15
DEFAULT_REASSIGN_PROB = 0.10
DEFAULT_CONVERGENCE_PATIENCE = 30
DEFAULT_MAX_TIME_SECONDS = 60


# ── 基因与染色体 ──────────────────────────────────────────────────────────────


@dataclass
class Gene:
    """单个基因：一个订单明细在某个产线、某个时间槽的安排。"""

    order_item_id: str
    workcenter_id: str
    start_slot: int


@dataclass
class Chromosome:
    """染色体：所有订单明细的基因排列序列。"""

    genes: list[Gene] = field(default_factory=list)
    fitness: float = float("-inf")


# ── 遗传算法求解器 ────────────────────────────────────────────────────────────


class GASolver(BaseSolver):
    """基于遗传算法的排产求解器。

    编码方案：
        染色体 = 订单明细的排列序列 + 每个订单的产线分配
        gene[i] = (order_item_id, workcenter_id, start_slot)
        序列顺序决定排产优先级

    适应度函数：
        fitness = Σ(soft_rule_score × weight) - Σ(hard_violation × 10000)

    遗传操作：
        - 选择：锦标赛选择（tournament_size=5）
        - 交叉：顺序交叉 OX + 产线分配均匀交叉
        - 变异：swap 变异 + 产线重分配变异（10% 概率）
        - 精英保留：保留 top 10%
    """

    def __init__(self, **kwargs: Any) -> None:
        self.pop_size: int = kwargs.get("pop_size", DEFAULT_POP_SIZE)
        self.max_generations: int = kwargs.get("max_generations", DEFAULT_MAX_GENERATIONS)
        self.tournament_size: int = kwargs.get("tournament_size", DEFAULT_TOURNAMENT_SIZE)
        self.elite_ratio: float = kwargs.get("elite_ratio", DEFAULT_ELITE_RATIO)
        self.crossover_rate: float = kwargs.get("crossover_rate", DEFAULT_CROSSOVER_RATE)
        self.mutation_rate: float = kwargs.get("mutation_rate", DEFAULT_MUTATION_RATE)
        self.reassign_prob: float = kwargs.get("reassign_prob", DEFAULT_REASSIGN_PROB)
        self.convergence_patience: int = kwargs.get(
            "convergence_patience", DEFAULT_CONVERGENCE_PATIENCE
        )
        self.max_time_seconds: float = kwargs.get(
            "max_time_seconds", DEFAULT_MAX_TIME_SECONDS
        )
        random.seed()

    # ── 公开接口 ───────────────────────────────────────────────────────────

    def solve(self, problem: SchedulingProblem) -> SolveResult:
        """执行遗传算法排产求解。"""
        start_ts = time.time()

        if not problem.order_items or not problem.workcenters:
            logger.warning("订单或产线为空，无法求解")
            return SolveResult(status=SolveStatus.INFEASIBLE, solve_time_seconds=0.0)

        # 构建辅助索引
        self._build_indices(problem)

        # 生成初始种群
        population = self._init_population(problem)

        # 评估初始种群
        for chrom in population:
            chrom.fitness = self._evaluate(chrom, problem)

        best = max(population, key=lambda c: c.fitness)
        no_improve_count = 0

        logger.info(
            "GA 求解启动: pop_size={}, max_gen={}, items={}, workcenters={}",
            self.pop_size,
            self.max_generations,
            len(problem.order_items),
            len(problem.workcenters),
        )

        for gen in range(1, self.max_generations + 1):
            elapsed = time.time() - start_ts
            if elapsed >= self.max_time_seconds:
                logger.info("GA 超时终止，代数={}, 耗时={:.1f}s", gen - 1, elapsed)
                break

            # 选择 + 交叉 + 变异 → 新种群
            offspring = self._evolve(population, problem)

            # 评估子代
            for chrom in offspring:
                chrom.fitness = self._evaluate(chrom, problem)

            # 精英保留 + 替换
            population = self._select_next_generation(population, offspring)

            # 更新最优
            gen_best = max(population, key=lambda c: c.fitness)
            if gen_best.fitness > best.fitness:
                best = gen_best
                no_improve_count = 0
            else:
                no_improve_count += 1

            if gen % 10 == 0:
                logger.info(
                    "GA 代数={}, 最优适应度={:.2f}, 硬违反={}",
                    gen,
                    best.fitness,
                    self._count_hard_violations(best, problem),
                )

            # 收敛判定
            if no_improve_count >= self.convergence_patience:
                logger.info(
                    "GA 收敛终止，连续 {} 代无改善", self.convergence_patience
                )
                break

        elapsed = time.time() - start_ts

        # 解码最优染色体
        tasks = self._decode(best, problem)
        hard_violations = self._count_hard_violations(best, problem)
        objective_values = self._compute_objectives(best, problem)

        # 判定求解状态
        if hard_violations == 0 and tasks:
            status = SolveStatus.FEASIBLE
        else:
            status = SolveStatus.INFEASIBLE

        logger.info(
            "GA 求解完成: status={}, fitness={:.2f}, hard_violations={}, "
            "tasks={}, 耗时={:.2f}s",
            status.value,
            best.fitness,
            hard_violations,
            len(tasks),
            elapsed,
        )

        return SolveResult(
            status=status,
            tasks=tasks,
            objective_values=objective_values,
            fitness=best.fitness,
            hard_violations=hard_violations,
            solve_time_seconds=elapsed,
            generations=gen if "gen" in dir() else 0,
            metadata={"pop_size": self.pop_size},
        )

    def get_capabilities(self) -> SolverCapabilities:
        """返回遗传算法求解器能力描述。"""
        return SolverCapabilities(
            solver_name="genetic-algorithm",
            supported_soft_rules=list(SoftRule),
            supported_hard_rules=[
                HardRule.FINITE_CAPACITY,
                HardRule.PROCESS_ORDER,
                HardRule.RESOURCE_COMPATIBILITY,
            ],
            max_items=200,
            max_workcenters=20,
            max_time_slots=96,
        )

    # ── 辅助索引 ───────────────────────────────────────────────────────────

    def _build_indices(self, problem: SchedulingProblem) -> None:
        """构建产线索引和兼容性索引。"""
        self._wc_by_id: dict[str, WorkcenterInfo] = {
            wc.id: wc for wc in problem.workcenters
        }
        self._item_by_id: dict[str, OrderItem] = {
            item.id: item for item in problem.order_items
        }
        self._compatible_wcs: dict[str, list[str]] = {}
        for item in problem.order_items:
            if item.compatible_workcenters:
                self._compatible_wcs[item.id] = item.compatible_workcenters
            else:
                compatible = [
                    wc.id
                    for wc in problem.workcenters
                    if not wc.compatible_products
                    or item.product in wc.compatible_products
                ]
                self._compatible_wcs[item.id] = compatible or [
                    wc.id for wc in problem.workcenters
                ]
        self._num_slots = len(problem.time_slots) if problem.time_slots else 96

    # ── 初始种群 ───────────────────────────────────────────────────────────

    def _init_population(self, problem: SchedulingProblem) -> list[Chromosome]:
        """生成初始种群：50% 随机 + 25% 优先级排序 + 25% 换线聚类。"""
        n_random = self.pop_size // 2
        n_priority = self.pop_size // 4
        n_cluster = self.pop_size - n_random - n_priority

        population: list[Chromosome] = []

        # 50% 随机生成
        for _ in range(n_random):
            chrom = self._random_chromosome(problem)
            population.append(chrom)

        # 25% 按优先级排序（P1 优先）
        sorted_items = sorted(problem.order_items, key=lambda x: x.priority)
        for _ in range(n_priority):
            chrom = self._chromosome_from_order(problem, sorted_items)
            population.append(chrom)

        # 25% 按换线属性聚类（成组技术）
        clustered_items = sorted(
            problem.order_items, key=lambda x: x.changeover_group
        )
        for _ in range(n_cluster):
            chrom = self._chromosome_from_order(problem, clustered_items)
            population.append(chrom)

        return population

    def _random_chromosome(self, problem: SchedulingProblem) -> Chromosome:
        """随机生成一条染色体。"""
        items = list(problem.order_items)
        random.shuffle(items)
        genes: list[Gene] = []
        for item in items:
            wc_id = random.choice(self._compatible_wcs[item.id])
            start = random.randint(0, max(0, self._num_slots - item.duration_slots))
            genes.append(Gene(item.id, wc_id, start))
        return Chromosome(genes=genes)

    def _chromosome_from_order(
        self, problem: SchedulingProblem, items: list[OrderItem]
    ) -> Chromosome:
        """按给定顺序生成染色体，产线和时间槽随机。"""
        genes: list[Gene] = []
        for item in items:
            wc_id = random.choice(self._compatible_wcs[item.id])
            start = random.randint(0, max(0, self._num_slots - item.duration_slots))
            genes.append(Gene(item.id, wc_id, start))
        return Chromosome(genes=genes)

    # ── 适应度评估 ─────────────────────────────────────────────────────────

    def _evaluate(self, chrom: Chromosome, problem: SchedulingProblem) -> float:
        """计算适应度：软规则加权得分 - 硬规则违反惩罚。"""
        soft_score = self._compute_soft_score(chrom, problem)
        hard_penalty = self._count_hard_violations(chrom, problem) * HARD_VIOLATION_PENALTY
        return soft_score - hard_penalty

    def _compute_soft_score(self, chrom: Chromosome, problem: SchedulingProblem) -> float:
        """计算软规则加权得分。"""
        if not chrom.genes:
            return 0.0

        weights = problem.soft_rule_weights
        active_rules = set(problem.soft_rules) if problem.soft_rules else set(SoftRule)
        score = 0.0

        # MINIMIZE_CHANGEOVER：相邻不同换线组越少越好
        if SoftRule.MINIMIZE_CHANGEOVER in active_rules:
            changeover_score = self._score_changeover(chrom, problem)
            w = weights.get(SoftRule.MINIMIZE_CHANGEOVER.value, 1.0)
            score += changeover_score * w

        # PRIORITY_FIRST：高优先级订单排得越靠前越好
        if SoftRule.PRIORITY_FIRST in active_rules:
            priority_score = self._score_priority(chrom, problem)
            w = weights.get(SoftRule.PRIORITY_FIRST.value, 1.0)
            score += priority_score * w

        # DUE_DATE_FIRST：交期越早的排得越靠前越好
        if SoftRule.DUE_DATE_FIRST in active_rules:
            due_score = self._score_due_date(chrom, problem)
            w = weights.get(SoftRule.DUE_DATE_FIRST.value, 1.0)
            score += due_score * w

        # BALANCE_LOAD：产线负载越均衡越好
        if SoftRule.BALANCE_LOAD in active_rules:
            balance_score = self._score_balance(chrom, problem)
            w = weights.get(SoftRule.BALANCE_LOAD.value, 1.0)
            score += balance_score * w

        # MINIMIZE_MAKESPAN：最大完工时间越小越好
        if SoftRule.MINIMIZE_MAKESPAN in active_rules:
            makespan_score = self._score_makespan(chrom, problem)
            w = weights.get(SoftRule.MINIMIZE_MAKESPAN.value, 1.0)
            score += makespan_score * w

        return score

    def _score_changeover(self, chrom: Chromosome, problem: SchedulingProblem) -> float:
        """换线得分：按产线分组，计算相邻换线组变化次数，越少分越高。"""
        wc_genes: dict[str, list[Gene]] = {}
        for gene in chrom.genes:
            wc_genes.setdefault(gene.workcenter_id, []).append(gene)

        total_changes = 0
        total_adjacent = 0
        for wc_id, genes in wc_genes.items():
            sorted_genes = sorted(genes, key=lambda g: g.start_slot)
            for i in range(1, len(sorted_genes)):
                prev_item = self._item_by_id.get(sorted_genes[i - 1].order_item_id)
                curr_item = self._item_by_id.get(sorted_genes[i].order_item_id)
                if prev_item and curr_item:
                    total_adjacent += 1
                    if prev_item.changeover_group != curr_item.changeover_group:
                        total_changes += 1

        if total_adjacent == 0:
            return 1.0
        return 1.0 - (total_changes / total_adjacent)

    def _score_priority(self, chrom: Chromosome, problem: SchedulingProblem) -> float:
        """优先级得分：高优先级（数值小）排在序列前面得分高。"""
        n = len(chrom.genes)
        if n == 0:
            return 0.0
        score = 0.0
        for idx, gene in enumerate(chrom.genes):
            item = self._item_by_id.get(gene.order_item_id)
            if item:
                rank_ratio = 1.0 - (idx / n)
                score += rank_ratio / max(item.priority, 1)
        return score / n

    def _score_due_date(self, chrom: Chromosome, problem: SchedulingProblem) -> float:
        """交期得分：交期越早的排在越前面得分越高。"""
        n = len(chrom.genes)
        if n == 0:
            return 0.0
        items_with_due = [
            g for g in chrom.genes
            if self._item_by_id.get(g.order_item_id) and self._item_by_id[g.order_item_id].delivery_date
        ]
        if not items_with_due:
            return 1.0

        sorted_by_due = sorted(
            items_with_due,
            key=lambda g: self._item_by_id[g.order_item_id].delivery_date,
        )
        correct_count = 0
        for i, gene in enumerate(sorted_by_due):
            pos_in_chrom = next(
                (j for j, g in enumerate(chrom.genes) if g.order_item_id == gene.order_item_id),
                0,
            )
            if pos_in_chrom <= i + n * 0.2:
                correct_count += 1
        return correct_count / len(items_with_due)

    def _score_balance(self, chrom: Chromosome, problem: SchedulingProblem) -> float:
        """负载均衡得分：各产线负载越均衡分越高。"""
        wc_load: dict[str, float] = {}
        for gene in chrom.genes:
            item = self._item_by_id.get(gene.order_item_id)
            wc_load[gene.workcenter_id] = wc_load.get(gene.workcenter_id, 0.0) + (
                item.quantity if item else 1.0
            )

        if not wc_load:
            return 1.0
        loads = list(wc_load.values())
        avg = sum(loads) / len(loads)
        if avg == 0:
            return 1.0
        variance = sum((l - avg) ** 2 for l in loads) / len(loads)
        cv = (variance ** 0.5) / avg
        return max(0.0, 1.0 - cv)

    def _score_makespan(self, chrom: Chromosome, problem: SchedulingProblem) -> float:
        """最大完工时间得分：makespan 越小分越高。"""
        if not chrom.genes:
            return 1.0
        max_end = 0
        for gene in chrom.genes:
            item = self._item_by_id.get(gene.order_item_id)
            end = gene.start_slot + (item.duration_slots if item else 1)
            if end > max_end:
                max_end = end
        if self._num_slots == 0:
            return 1.0
        return max(0.0, 1.0 - (max_end / self._num_slots))

    # ── 硬规则违反计数 ────────────────────────────────────────────────────

    def _count_hard_violations(self, chrom: Chromosome, problem: SchedulingProblem) -> int:
        """统计硬规则违反次数。"""
        violations = 0
        active_hard = set(problem.hard_rules) if problem.hard_rules else set()

        if HardRule.FINITE_CAPACITY in active_hard:
            violations += self._count_capacity_violations(chrom, problem)

        if HardRule.PROCESS_ORDER in active_hard:
            violations += self._count_process_order_violations(chrom, problem)

        if HardRule.RESOURCE_COMPATIBILITY in active_hard:
            violations += self._count_compatibility_violations(chrom, problem)

        return violations

    def _get_wc_capacity(self, wc_id: str) -> float:
        """获取产线单槽产能，兼容 WorkCenter 和 WorkcenterInfo。"""
        wc = self._wc_by_id.get(wc_id)
        if wc is None:
            return 1.0
        # WorkcenterInfo 有 capacity_per_slot
        if hasattr(wc, "capacity_per_slot"):
            return wc.capacity_per_slot
        # WorkCenter 用 hourly_capacity 或 daily_capacity / 12
        if getattr(wc, "hourly_capacity", 0) > 0:
            return wc.hourly_capacity
        if getattr(wc, "daily_capacity", 0) > 0:
            return wc.daily_capacity / 12.0
        return 1.0

    def _count_capacity_violations(self, chrom: Chromosome, problem: SchedulingProblem) -> int:
        """统计产能违反次数：某时间槽某产线上的任务超过产能。"""
        slot_usage: dict[str, dict[int, float]] = {}
        for gene in chrom.genes:
            item = self._item_by_id.get(gene.order_item_id)
            qty = item.quantity if item else 1.0
            dur = item.duration_slots if item else 1
            wc_slots = slot_usage.setdefault(gene.workcenter_id, {})
            for s in range(gene.start_slot, gene.start_slot + dur):
                wc_slots[s] = wc_slots.get(s, 0.0) + qty

        violations = 0
        for wc_id, slots in slot_usage.items():
            cap = self._get_wc_capacity(wc_id)
            for _slot, load in slots.items():
                if load > cap:
                    violations += 1
        return violations

    def _count_process_order_violations(self, chrom: Chromosome, problem: SchedulingProblem) -> int:
        """统计工序顺序违反次数：同一订单的任务应按顺序排列。"""
        order_genes: dict[str, list[Gene]] = {}
        for gene in chrom.genes:
            order_no = self._item_by_id.get(gene.order_item_id)
            if order_no:
                key = order_no.order_no
                order_genes.setdefault(key, []).append(gene)

        violations = 0
        for _order_no, genes in order_genes.items():
            if len(genes) <= 1:
                continue
            for i in range(1, len(genes)):
                if genes[i].start_slot < genes[i - 1].start_slot:
                    violations += 1
        return violations

    def _count_compatibility_violations(self, chrom: Chromosome, problem: SchedulingProblem) -> int:
        """统计兼容性违反次数：订单分配到不兼容的产线。"""
        violations = 0
        for gene in chrom.genes:
            compatible = self._compatible_wcs.get(gene.order_item_id, [])
            if compatible and gene.workcenter_id not in compatible:
                violations += 1
        return violations

    # ── 遗传操作 ───────────────────────────────────────────────────────────

    def _evolve(
        self, population: list[Chromosome], problem: SchedulingProblem
    ) -> list[Chromosome]:
        """执行一代进化：选择 → 交叉 → 变异。"""
        elite_count = max(1, int(self.pop_size * self.elite_ratio))
        sorted_pop = sorted(population, key=lambda c: c.fitness, reverse=True)
        elites = [Chromosome(genes=list(e.genes)) for e in sorted_pop[:elite_count]]

        offspring: list[Chromosome] = []
        while len(offspring) < self.pop_size - elite_count:
            parent1 = self._tournament_select(population)
            parent2 = self._tournament_select(population)

            if random.random() < self.crossover_rate:
                child = self._crossover(parent1, parent2)
            else:
                child = Chromosome(genes=list(parent1.genes))

            self._mutate(child, problem)
            offspring.append(child)

        return elites + offspring

    def _tournament_select(self, population: list[Chromosome]) -> Chromosome:
        """锦标赛选择。"""
        candidates = random.sample(population, min(self.tournament_size, len(population)))
        return max(candidates, key=lambda c: c.fitness)

    def _crossover(self, p1: Chromosome, p2: Chromosome) -> Chromosome:
        """顺序交叉 OX（保留序列片段）+ 产线分配均匀交叉。"""
        n = len(p1.genes)
        if n <= 2:
            return Chromosome(genes=list(p1.genes))

        # OX 交叉：序列部分
        cut1, cut2 = sorted(random.sample(range(n), 2))
        child_ids: list[str | None] = [None] * n
        p1_ids = [g.order_item_id for g in p1.genes]

        # 保留 p1 的片段
        for i in range(cut1, cut2 + 1):
            child_ids[i] = p1_ids[i]

        # 从 p2 填充剩余位置
        p2_ids = [g.order_item_id for g in p2.genes]
        fill_pos = (cut2 + 1) % n
        for oid in p2_ids:
            if oid not in child_ids:
                while child_ids[fill_pos] is not None:
                    fill_pos = (fill_pos + 1) % n
                child_ids[fill_pos] = oid

        # 构建子代基因，产线分配均匀交叉
        p2_gene_map = {g.order_item_id: g for g in p2.genes}
        child_genes: list[Gene] = []
        for i, oid in enumerate(child_ids):
            if oid is None:
                continue
            g1 = p1.genes[i] if i < len(p1.genes) and p1.genes[i].order_item_id == oid else None
            g2 = p2_gene_map.get(oid)

            # 序列位置决定 start_slot：沿用对应父代的
            src = g1 if g1 and g1.order_item_id == oid else g2
            start_slot = src.start_slot if src else 0

            # 产线均匀交叉
            if random.random() < 0.5 and g1 and g1.order_item_id == oid:
                wc_id = g1.workcenter_id
            elif g2:
                wc_id = g2.workcenter_id
            elif g1 and g1.order_item_id == oid:
                wc_id = g1.workcenter_id
            else:
                wc_id = ""

            child_genes.append(Gene(oid, wc_id, start_slot))

        return Chromosome(genes=child_genes)

    def _mutate(self, chrom: Chromosome, problem: SchedulingProblem) -> None:
        """变异：swap 变异 + 产线重分配变异。"""
        if len(chrom.genes) < 2:
            return

        # swap 变异
        if random.random() < self.mutation_rate:
            i, j = random.sample(range(len(chrom.genes)), 2)
            chrom.genes[i], chrom.genes[j] = chrom.genes[j], chrom.genes[i]

        # 产线重分配变异
        for gene in chrom.genes:
            if random.random() < self.reassign_prob:
                compatible = self._compatible_wcs.get(gene.order_item_id, [])
                if compatible:
                    gene.workcenter_id = random.choice(compatible)

    def _select_next_generation(
        self, parents: list[Chromosome], offspring: list[Chromosome]
    ) -> list[Chromosome]:
        """精英保留策略：从父代精英 + 子代中选择下一代。"""
        elite_count = max(1, int(self.pop_size * self.elite_ratio))
        sorted_parents = sorted(parents, key=lambda c: c.fitness, reverse=True)
        elites = [Chromosome(genes=list(e.genes), fitness=e.fitness) for e in sorted_parents[:elite_count]]

        # 子代按适应度排序，取 pop_size - elite_count 个
        sorted_offspring = sorted(offspring, key=lambda c: c.fitness, reverse=True)
        selected = sorted_offspring[: self.pop_size - elite_count]

        return elites + selected

    # ── 解码与修复 ─────────────────────────────────────────────────────────

    def _decode(
        self, chrom: Chromosome, problem: SchedulingProblem
    ) -> list[ScheduledTask]:
        """将最优染色体解码为 List[ScheduledTask]，并执行修复。"""
        # 先修复
        self._repair(chrom, problem)

        tasks: list[ScheduledTask] = []
        for gene in chrom.genes:
            item = self._item_by_id.get(gene.order_item_id)
            if not item:
                continue
            end_slot = gene.start_slot + item.duration_slots
            tasks.append(
                ScheduledTask(
                    order_item_id=gene.order_item_id,
                    workcenter_id=gene.workcenter_id,
                    start_slot=gene.start_slot,
                    end_slot=end_slot,
                    quantity=item.quantity,
                    product=item.product,
                    order_id=item.order_no,
                )
            )
        return tasks

    def _repair(self, chrom: Chromosome, problem: SchedulingProblem) -> None:
        """修复算子：尝试修复硬规则违反。"""
        active_hard = set(problem.hard_rules) if problem.hard_rules else set()

        if HardRule.RESOURCE_COMPATIBILITY in active_hard:
            self._repair_compatibility(chrom)

        if HardRule.FINITE_CAPACITY in active_hard:
            self._repair_capacity(chrom, problem)

    def _repair_compatibility(self, chrom: Chromosome) -> None:
        """兼容性修复：如果产线不兼容，随机分配到兼容产线。"""
        for gene in chrom.genes:
            compatible = self._compatible_wcs.get(gene.order_item_id, [])
            if compatible and gene.workcenter_id not in compatible:
                gene.workcenter_id = random.choice(compatible)

    def _repair_capacity(self, chrom: Chromosome, problem: SchedulingProblem) -> None:
        """产能修复：如果某时间槽超产能，将多余量移到下一个可用槽。"""
        # 按产线分组，按 start_slot 排序
        wc_genes: dict[str, list[Gene]] = {}
        for gene in chrom.genes:
            wc_genes.setdefault(gene.workcenter_id, []).append(gene)

        for wc_id, genes in wc_genes.items():
            cap = self._get_wc_capacity(wc_id)
            sorted_genes = sorted(genes, key=lambda g: g.start_slot)

            slot_load: dict[int, float] = {}
            for gene in sorted_genes:
                item = self._item_by_id.get(gene.order_item_id)
                qty = item.quantity if item else 1.0
                dur = item.duration_slots if item else 1

                # 检查当前安排是否超产能
                needs_shift = False
                for s in range(gene.start_slot, gene.start_slot + dur):
                    current_load = slot_load.get(s, 0.0)
                    if current_load + qty > cap:
                        needs_shift = True
                        break

                if needs_shift:
                    # 寻找下一个可用时间槽
                    new_start = self._find_available_slot(
                        gene, qty, dur, cap, slot_load
                    )
                    gene.start_slot = new_start

                # 更新负载记录
                for s in range(gene.start_slot, gene.start_slot + dur):
                    slot_load[s] = slot_load.get(s, 0.0) + qty

    def _find_available_slot(
        self,
        gene: Gene,
        qty: float,
        dur: int,
        cap: float,
        slot_load: dict[int, float],
    ) -> int:
        """寻找下一个可用时间槽。"""
        item = self._item_by_id.get(gene.order_item_id)
        max_start = max(0, self._num_slots - dur)

        for start in range(gene.start_slot, max_start + 1):
            can_fit = True
            for s in range(start, start + dur):
                if slot_load.get(s, 0.0) + qty > cap:
                    can_fit = False
                    break
            if can_fit:
                return start

        # 找不到则返回原始位置（无法修复）
        return gene.start_slot

    # ── 目标值计算 ─────────────────────────────────────────────────────────

    def _compute_objectives(
        self, chrom: Chromosome, problem: SchedulingProblem
    ) -> dict[str, float]:
        """计算各软规则的独立目标值。"""
        objectives: dict[str, float] = {}

        if SoftRule.MINIMIZE_CHANGEOVER in problem.soft_rules:
            objectives["changeover_score"] = self._score_changeover(chrom, problem)

        if SoftRule.PRIORITY_FIRST in problem.soft_rules:
            objectives["priority_score"] = self._score_priority(chrom, problem)

        if SoftRule.DUE_DATE_FIRST in problem.soft_rules:
            objectives["due_date_score"] = self._score_due_date(chrom, problem)

        if SoftRule.BALANCE_LOAD in problem.soft_rules:
            objectives["balance_score"] = self._score_balance(chrom, problem)

        if SoftRule.MINIMIZE_MAKESPAN in problem.soft_rules:
            objectives["makespan_score"] = self._score_makespan(chrom, problem)

        return objectives
