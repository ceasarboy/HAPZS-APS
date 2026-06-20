"""排产方案评估器。

核心功能：评估排产方案质量，支持 What-if 模拟和方案对比。
"""

from __future__ import annotations

import copy
from collections import defaultdict
from typing import Dict, List, Set

from loguru import logger

from app.engine.models import (
    CompareResult,
    DemandPlan,
    EvaluationResult,
    KPI,
    SchedulingProblem,
    ScheduledTask,
    Violation,
    WhatIfEvent,
    WhatIfResult,
)

# 旧名别名，保持向后兼容
OrderItem = DemandPlan

# 硬规则违反的惩罚系数
_HARD_VIOLATION_PENALTY = 1000.0


class Evaluator:
    """排产方案评估器。"""

    def evaluate(
        self,
        plan: List[ScheduledTask],
        problem: SchedulingProblem,
    ) -> EvaluationResult:
        """评估一个排产方案的综合得分。

        Args:
            plan: 排产结果任务列表
            problem: 排产问题定义

        Returns:
            EvaluationResult: 包含硬规则违反、软规则评分、综合得分和 KPI
        """
        violations = self._check_hard_rules(plan, problem)
        kpi = self._compute_kpi(plan, problem)
        soft_scores = self._compute_soft_scores(plan, problem, kpi)
        overall = self._compute_overall_score(soft_scores, violations, problem)

        result = EvaluationResult(
            hard_violations=violations,
            soft_scores=soft_scores,
            overall_score=overall,
            kpi=kpi,
        )
        logger.info(
            "评估完成: overall={:.2f}, hard_violations={}, otd={:.2%}",
            overall,
            len(violations),
            kpi.otd_rate,
        )
        return result

    def what_if(
        self,
        base_plan: List[ScheduledTask],
        problem: SchedulingProblem,
        event: WhatIfEvent,
    ) -> WhatIfResult:
        """模拟一个事件对计划的影响。

        Args:
            base_plan: 基准排产方案
            problem: 排产问题定义
            event: What-if 事件

        Returns:
            WhatIfResult: 模拟结果
        """
        original = self.evaluate(base_plan, problem)

        # 根据事件类型构造新的 problem
        simulated_problem = copy.deepcopy(problem)
        simulated_plan = copy.deepcopy(base_plan)

        if event.event_type == "urgent_order":
            self._apply_urgent_order(simulated_problem, simulated_plan, event)
        elif event.event_type == "equipment_failure":
            self._apply_equipment_failure(simulated_problem, simulated_plan, event)
        elif event.event_type == "material_delay":
            self._apply_material_delay(simulated_problem, simulated_plan, event)
        else:
            logger.warning("未知的 What-if 事件类型: {}", event.event_type)

        simulated = self.evaluate(simulated_plan, simulated_problem)

        # 计算受影响的订单
        affected_orders = self._find_affected_orders(base_plan, simulated_plan)

        # 缓冲区状态变化
        buffer_status = self._compute_buffer_status(simulated_problem, simulated.kpi)

        # 生成建议
        recommendation = self._generate_recommendation(event, original, simulated)

        score_delta = simulated.overall_score - original.overall_score
        result = WhatIfResult(
            original_score=original.overall_score,
            simulated_score=simulated.overall_score,
            score_delta=score_delta,
            affected_orders=affected_orders,
            buffer_status=buffer_status,
            recommendation=recommendation,
        )
        logger.info(
            "What-if 模拟完成: event={}, score_delta={:.2f}, affected_orders={}",
            event.event_type,
            score_delta,
            len(affected_orders),
        )
        return result

    def compare(
        self,
        plan_a: List[ScheduledTask],
        plan_b: List[ScheduledTask],
        problem: SchedulingProblem,
    ) -> CompareResult:
        """对比两个方案。

        Args:
            plan_a: 方案 A
            plan_b: 方案 B
            problem: 排产问题定义

        Returns:
            CompareResult: 对比结果
        """
        eval_a = self.evaluate(plan_a, problem)
        eval_b = self.evaluate(plan_b, problem)

        kpi_diff = eval_a.kpi - eval_b.kpi

        if eval_a.overall_score > eval_b.overall_score:
            winner = "A"
        elif eval_b.overall_score > eval_a.overall_score:
            winner = "B"
        else:
            winner = "tie"

        result = CompareResult(
            plan_a_score=eval_a.overall_score,
            plan_b_score=eval_b.overall_score,
            kpi_diff=kpi_diff,
            winner=winner,
        )
        logger.info(
            "方案对比完成: A={:.2f}, B={:.2f}, winner={}",
            eval_a.overall_score,
            eval_b.overall_score,
            winner,
        )
        return result

    # ------------------------------------------------------------------
    # 硬规则校验
    # ------------------------------------------------------------------

    def _check_hard_rules(
        self,
        plan: List[ScheduledTask],
        problem: SchedulingProblem,
    ) -> List[Violation]:
        """遍历每个 ScheduledTask，检查是否违反硬规则。"""
        violations: List[Violation] = []

        # 构建索引
        wc_map = {wc.id: wc for wc in (problem.production_lines or problem.workcenters)}

        # 按产线+时间槽分组，检查产能
        slot_load: Dict[str, Dict[int, float]] = defaultdict(lambda: defaultdict(float))
        for task in plan:
            for slot in range(task.start_slot, task.end_slot + 1):
                slot_load[task.workcenter_id][slot] += task.quantity

        # 1. 有限产能校验
        for wc_id, slots in slot_load.items():
            wc = wc_map.get(wc_id)
            if wc is None:
                continue
            cap = getattr(wc, "capacity_per_slot", wc.daily_capacity)
            for slot_idx, load in slots.items():
                if cap > 0 and load > cap:
                    violations.append(Violation(
                        rule_name="有限产能",
                        task_id=f"{wc_id}@slot{slot_idx}",
                        detail=f"负荷 {load:.1f} 超过产能 {cap:.1f}",
                    ))

        # 2. 资源兼容性校验
        for task in plan:
            wc = wc_map.get(task.workcenter_id)
            if wc and wc.compatible_products and task.product not in wc.compatible_products:
                violations.append(Violation(
                    rule_name="资源兼容",
                    task_id=task.order_item_id,
                    detail=f"产品 {task.product} 不兼容产线 {task.workcenter_id}",
                ))

        # 3. 冻结窗口校验
        freeze = problem.freeze_horizon
        if freeze > 0:
            for task in plan:
                if task.start_slot < freeze:
                    violations.append(Violation(
                        rule_name="冻结窗口",
                        task_id=task.order_item_id,
                        detail=f"任务在冻结窗口内（slot {task.start_slot}）被修改",
                    ))

        return violations

    # ------------------------------------------------------------------
    # KPI 计算
    # ------------------------------------------------------------------

    def _compute_kpi(
        self,
        plan: List[ScheduledTask],
        problem: SchedulingProblem,
    ) -> KPI:
        """计算关键绩效指标。"""
        # OTD 率：按时交付的订单数 / 总订单数
        total_orders = len(problem.demand_plans or problem.order_items or [])
        on_time_orders = 0
        order_tasks: Dict[str, List[ScheduledTask]] = defaultdict(list)
        for task in plan:
            order_tasks[task.order_item_id].append(task)

        for order in (problem.demand_plans or problem.order_items or []):
            tasks = order_tasks.get(order.id, [])
            if not tasks:
                continue
            scheduled_qty = sum(t.quantity for t in tasks)
            if scheduled_qty >= order.quantity:
                on_time_orders += 1

        otd_rate = on_time_orders / total_orders if total_orders > 0 else 0.0

        # 换线次数和时长
        changeover_count, changeover_hours = self._compute_changeover(plan, problem)

        # Drum 利用率
        drum_utilization = self._compute_drum_utilization(plan, problem)

        # 产线均衡率
        line_balance_rate = self._compute_line_balance(plan, problem)

        # WIP 水平：未完工的订单数量
        wip_level = 0.0
        for order in (problem.demand_plans or problem.order_items or []):
            tasks = order_tasks.get(order.id, [])
            if tasks:
                scheduled_qty = sum(t.quantity for t in tasks)
                if scheduled_qty < order.quantity:
                    wip_level += 1

        # 总产量
        total_output = sum(t.quantity for t in plan)

        return KPI(
            otd_rate=otd_rate,
            changeover_count=changeover_count,
            changeover_hours=changeover_hours,
            drum_utilization=drum_utilization,
            line_balance_rate=line_balance_rate,
            wip_level=wip_level,
            total_output=total_output,
        )

    def _compute_changeover(
        self,
        plan: List[ScheduledTask],
        problem: SchedulingProblem,
    ) -> tuple[int, float]:
        """计算换线次数和总时长。"""
        # 构建换线时间查找表：优先 changeover_rules，其次 changeover_matrix
        co_map: Dict[tuple[str, str], float] = {}
        for rule in problem.changeover_rules:
            co_map[(rule.from_product, rule.to_product)] = rule.changeover_hours
        for entry in problem.changeover_matrix:
            key = (entry.from_product_id, entry.to_product_id)
            if key not in co_map:
                co_map[key] = entry.changeover_time

        # 按产线分组，按时间槽排序
        wc_tasks: Dict[str, List[ScheduledTask]] = defaultdict(list)
        for task in plan:
            wc_tasks[task.workcenter_id].append(task)

        count = 0
        hours = 0.0
        for wc_id, tasks in wc_tasks.items():
            tasks_sorted = sorted(tasks, key=lambda t: t.start_slot)
            for i in range(len(tasks_sorted) - 1):
                if tasks_sorted[i].product != tasks_sorted[i + 1].product:
                    count += 1
                    co_time = co_map.get(
                        (tasks_sorted[i].product, tasks_sorted[i + 1].product),
                        0.0,
                    )
                    hours += co_time

        return count, hours

    def _compute_drum_utilization(
        self,
        plan: List[ScheduledTask],
        problem: SchedulingProblem,
    ) -> float:
        """计算 Drum 工作中心的利用率。"""
        drum_ids = set(problem.drum_workcenter_ids)
        if not drum_ids:
            return 0.0

        total_slots = len(problem.time_slots)
        if total_slots == 0:
            return 0.0

        wc_tasks: Dict[str, List[ScheduledTask]] = defaultdict(list)
        for task in plan:
            wc_tasks[task.workcenter_id].append(task)

        utilizations = []
        for wc_id in drum_ids:
            tasks = wc_tasks.get(wc_id, [])
            used_slots = len({t.start_slot for t in tasks})
            utilizations.append(used_slots / total_slots)

        return sum(utilizations) / len(utilizations)

    def _compute_line_balance(
        self,
        plan: List[ScheduledTask],
        problem: SchedulingProblem,
    ) -> float:
        """计算产线均衡率 = 1 - (max负荷 - min负荷) / max负荷。"""
        if not (problem.production_lines or problem.workcenters):
            return 0.0

        wc_load: Dict[str, float] = defaultdict(float)
        for task in plan:
            wc_load[task.workcenter_id] += task.quantity

        loads = list(wc_load.values())
        # 未排产的产线负荷为 0
        for wc in (problem.production_lines or problem.workcenters):
            if wc.id not in wc_load:
                loads.append(0.0)

        if not loads:
            return 0.0

        max_load = max(loads)
        min_load = min(loads)

        if max_load == 0:
            return 1.0

        return 1.0 - (max_load - min_load) / max_load

    # ------------------------------------------------------------------
    # 软规则评分
    # ------------------------------------------------------------------

    def _compute_soft_scores(
        self,
        plan: List[ScheduledTask],
        problem: SchedulingProblem,
        kpi: KPI,
    ) -> Dict[str, float]:
        """计算各软规则的实际值，归一化到 [0, 1]。"""
        scores: Dict[str, float] = {}

        # OTD 得分：直接使用 otd_rate
        scores["otd"] = kpi.otd_rate

        # 换线得分：换线越少越好，用 1 - (换线次数 / 最大可能换线数)
        max_changeovers = len(problem.production_lines or problem.workcenters) * max(len(problem.time_slots) - 1, 1)
        scores["changeover"] = 1.0 - min(kpi.changeover_count / max(max_changeovers, 1), 1.0)

        # 产线均衡得分：直接使用 line_balance_rate
        scores["line_balance"] = kpi.line_balance_rate

        # WIP 得分：WIP 越少越好
        max_wip = len(problem.demand_plans or problem.order_items or [])
        scores["wip"] = 1.0 - min(kpi.wip_level / max(max_wip, 1), 1.0)

        # Drum 利用率得分：直接使用 drum_utilization
        scores["drum_utilization"] = kpi.drum_utilization

        # 稳定性得分：无旧方案对比时默认 1.0
        scores["stability"] = 1.0

        return scores

    def _compute_overall_score(
        self,
        soft_scores: Dict[str, float],
        violations: List[Violation],
        problem: SchedulingProblem,
    ) -> float:
        """计算综合得分 = Σ(soft_rule_score × weight) - Σ(hard_violation × 1000)。"""
        # objective_weights 可能是 dict[SoftRule, float] 或 dict[str, float]
        weights = problem.objective_weights
        # 构建字符串 → 权重的映射，兼容枚举 key 和字符串 key
        str_weights: Dict[str, float] = {}
        for k, v in weights.items():
            key_str = k.value if hasattr(k, "value") else str(k)
            # 将枚举名映射到评估器使用的短名
            name_map = {
                "OTD_PRIORITY": "otd",
                "SETUP_MINIMIZATION": "changeover",
                "MINIMIZE_CHANGEOVER": "changeover",
                "LOAD_BALANCING": "line_balance",
                "BALANCE_LOAD": "line_balance",
                "WIP_CONTROL": "wip",
                "DRUM_UTILIZATION": "drum_utilization",
                "PLAN_STABILITY": "stability",
            }
            short_name = name_map.get(key_str, key_str.lower())
            str_weights[short_name] = v

        weighted_sum = 0.0
        for rule, score in soft_scores.items():
            weight = str_weights.get(rule, 0.0)
            weighted_sum += score * weight

        penalty = len(violations) * _HARD_VIOLATION_PENALTY
        return weighted_sum - penalty

    # ------------------------------------------------------------------
    # What-if 事件应用
    # ------------------------------------------------------------------

    def _apply_urgent_order(
        self,
        problem: SchedulingProblem,
        plan: List[ScheduledTask],
        event: WhatIfEvent,
    ) -> None:
        """插单：将新订单加入 problem。"""
        if event.order_item is None:
            return
        items = problem.demand_plans or problem.order_items or []
        orders = problem.orders or items
        items.append(event.order_item)
        if orders is not items:
            orders.append(event.order_item)
        logger.info("What-if 插单: order_id={}", event.order_item.id)

    def _apply_equipment_failure(
        self,
        problem: SchedulingProblem,
        plan: List[ScheduledTask],
        event: WhatIfEvent,
    ) -> None:
        """设备故障：将故障产线的产能设为 0，移除受影响时间槽的任务。"""
        for wc in (problem.production_lines or problem.workcenters):
            if wc.id == event.workcenter_id:
                if hasattr(wc, "capacity_per_slot"):
                    wc.capacity_per_slot = 0.0
                wc.daily_capacity = 0.0
                logger.info("What-if 设备故障: wc_id={}", event.workcenter_id)

        # 移除受影响时间槽上的任务
        affected_slots = set(event.affected_slots)
        if affected_slots:
            plan[:] = [
                t for t in plan
                if not (t.workcenter_id == event.workcenter_id and t.start_slot in affected_slots)
            ]

    def _apply_material_delay(
        self,
        problem: SchedulingProblem,
        plan: List[ScheduledTask],
        event: WhatIfEvent,
    ) -> None:
        """物料延迟：将受影响产品的 material_ready 时间推迟。"""
        affected_slots = set(event.affected_slots)
        if not affected_slots:
            return

        # 简化：移除受影响时间槽上的任务
        plan[:] = [
            t for t in plan
            if t.start_slot not in affected_slots
        ]
        logger.info("What-if 物料延迟: delay_hours={}", event.delay_hours)

    # ------------------------------------------------------------------
    # What-if 辅助方法
    # ------------------------------------------------------------------

    def _find_affected_orders(
        self,
        base_plan: List[ScheduledTask],
        simulated_plan: List[ScheduledTask],
    ) -> List[str]:
        """找出受影响的订单编号。"""
        base_keys = {(t.order_item_id, t.start_slot, t.workcenter_id) for t in base_plan}
        sim_keys = {(t.order_item_id, t.start_slot, t.workcenter_id) for t in simulated_plan}

        added = sim_keys - base_keys
        removed = base_keys - sim_keys

        affected: Set[str] = set()
        for task in simulated_plan:
            if (task.order_item_id, task.start_slot, task.workcenter_id) in added:
                affected.add(task.order_id or task.order_item_id)
        for task in base_plan:
            if (task.order_item_id, task.start_slot, task.workcenter_id) in removed:
                affected.add(task.order_id or task.order_item_id)

        return sorted(affected)

    def _compute_buffer_status(
        self,
        problem: SchedulingProblem,
        kpi: KPI,
    ) -> Dict[str, str]:
        """计算缓冲区状态变化（绿/黄/红）。"""
        status: Dict[str, str] = {}
        for buf in problem.buffers:
            target_wc = buf.to_workcenter_id or buf.from_workcenter_id
            if kpi.drum_utilization >= buf.green_zone:
                status[target_wc] = "绿"
            elif kpi.drum_utilization >= buf.yellow_zone:
                status[target_wc] = "黄"
            else:
                status[target_wc] = "红"
        return status

    def _generate_recommendation(
        self,
        event: WhatIfEvent,
        original: EvaluationResult,
        simulated: EvaluationResult,
    ) -> str:
        """生成系统建议。"""
        delta = simulated.overall_score - original.overall_score

        if event.event_type == "urgent_order":
            if delta >= 0:
                return "插单对整体计划影响为正面或中性，建议接受。"
            elif delta > -5:
                return "插单对计划影响较小，建议接受并微调后续排产。"
            else:
                return "插单对计划影响较大，建议评估是否调整优先级或延后交付。"

        elif event.event_type == "equipment_failure":
            if delta >= -5:
                return "设备故障影响可控，建议将受影响任务转移到备用产线。"
            else:
                return "设备故障影响严重，建议启动应急预案，重新排产。"

        elif event.event_type == "material_delay":
            if delta >= -5:
                return "物料延迟影响有限，建议调整受影响订单的排产时间。"
            else:
                return "物料延迟影响较大，建议与供应链协调加急，并重新评估交期。"

        return "建议根据实际情况调整排产方案。"
