"""ortools CP-SAT 求解器适配器，支持 DBR 混合方向排产 + V2 工序级排产。"""

from __future__ import annotations

import math
import time
from typing import Any

from loguru import logger
from ortools.sat.python import cp_model

from app.engine.constraint_builder import BuiltConstraints, ConstraintBuilder
from app.engine.models import (
    BaseSolver,
    DemandPlan,
    HardRule,
    ScheduledTask,
    SchedulingProblem,
    SoftRule,
    SolveResult,
    SolveStatus,
    SolverCapabilities,
)

# 旧名别名，保持向后兼容
OrderItem = DemandPlan


class ORToolsSolver(BaseSolver):
    """基于 ortools CP-SAT 的排产求解器，支持 DBR 混合方向 + 工序级排产。"""

    # ── 求解器接口 ─────────────────────────────────────────────────────────

    def solve(self, problem: SchedulingProblem) -> SolveResult:
        """执行排产求解。

        流程：
        1. ConstraintBuilder 构建约束数据（含虚拟工作中心和展开项）
        2. 创建 CP-SAT 模型与决策变量
        3. 添加硬规则约束（含工序顺序约束）
        4. 构建软规则目标函数
        5. 求解并转换结果
        """
        start_time = time.monotonic()
        items = problem.demand_plans or problem.items or problem.order_items or problem.orders or []
        logger.info(
            "ORToolsSolver 开始求解，需求数={} 产线数={} 时间槽数={}",
            len(items), len(problem.production_lines or problem.workcenters), len(problem.time_slots),
        )

        try:
            constraints = ConstraintBuilder().build(problem)
            model = cp_model.CpModel()

            n_items = len(constraints.item_indices)
            n_wc = len(constraints.workcenter_indices)
            time_indices = constraints.time_indices

            logger.info(
                "展开后: 排产项={} 虚拟工作中心={}", n_items, n_wc,
            )

            # ── 决策变量 ────────────────────────────────────────────────
            # x[i][t][w] = 排产项 i 在时间槽 t 在虚拟工作中心 w 上的生产数量
            x: dict[int, dict[int, dict[int, cp_model.IntVar]]] = {}
            frozen_time_indices = constraints.frozen_time_indices
            for i in range(n_items):
                x[i] = {}
                for t in time_indices:
                    # 冻结窗口内的时间槽跳过变量创建（不允许新任务分配）
                    if t in frozen_time_indices:
                        continue
                    x[i][t] = {}
                    for w in range(n_wc):
                        # 不可排的位置跳过
                        if constraints.incompatible.get(i, {}).get(w, False):
                            continue
                        if constraints.material_not_ready.get(i, {}).get(t, False):
                            continue
                        # 冻结窗口内的固定排产
                        fixed_qty = constraints.fixed.get(i, {}).get(t, {}).get(w)
                        if fixed_qty is not None:
                            var = model.NewIntVar(
                                int(fixed_qty), int(fixed_qty),
                                f"x_{i}_{t}_{w}",
                            )
                        else:
                            cap = constraints.capacity.get(w, {}).get(t, 0)
                            upper = min(cap, constraints.demands.get(i, 0))
                            if upper <= 0:
                                continue
                            var = model.NewIntVar(0, math.ceil(upper), f"x_{i}_{t}_{w}")
                        x[i][t][w] = var

            # unmet[i] = 排产项 i 未满足数量（允许部分满足）
            unmet: dict[int, cp_model.IntVar] = {}
            for i in range(n_items):
                demand = math.ceil(constraints.demands.get(i, 0))
                unmet[i] = model.NewIntVar(0, demand, f"unmet_{i}")

            # ── 硬规则约束 ──────────────────────────────────────────────

            # 1. 有限产能: Σ x[i,t,w] ≤ capacity[w,t]
            for w in range(n_wc):
                for t in time_indices:
                    cap = math.ceil(constraints.capacity.get(w, {}).get(t, 0))
                    if cap <= 0:
                        continue
                    prod_vars = [
                        x[i][t][w]
                        for i in range(n_items)
                        if t in x[i] and w in x[i][t]
                    ]
                    if prod_vars:
                        model.Add(sum(prod_vars) <= cap)

            # 2. 需求满足: Σ x[i,t,w] + unmet[i] = demand[i]
            for i in range(n_items):
                prod_vars = [
                    x[i][t][w]
                    for t in time_indices
                    if t in x[i]
                    for w in x[i][t]
                ]
                model.Add(sum(prod_vars) + unmet[i] == math.ceil(constraints.demands.get(i, 0)))

            # 3. 工序顺序约束: 同一需求的工序N必须在工序N+1之前完成
            self._add_process_order_constraints(model, x, constraints, time_indices)

            # 4. 换线约束（可选）
            enable_changeover_constraints = problem.solver_params.get(
                "enable_changeover_constraints", False
            )
            max_products_per_slot = problem.solver_params.get("max_products_per_slot", 3)
            has: dict[int, dict[int, dict[int, cp_model.IntVar]]] = {}
            if enable_changeover_constraints:
                for i in range(n_items):
                    has[i] = {}
                    for t in time_indices:
                        has[i][t] = {}
                        for w in range(n_wc):
                            if t in x[i] and w in x[i][t]:
                                b = model.NewBoolVar(f"has_{i}_{t}_{w}")
                                model.Add(x[i][t][w] >= 1).OnlyEnforceIf(b)
                                model.Add(x[i][t][w] == 0).OnlyEnforceIf(b.Not())
                                has[i][t][w] = b

                for w in range(n_wc):
                    for t in time_indices:
                        prod_has = [
                            has[i][t][w]
                            for i in range(n_items)
                            if t in has[i] and w in has[i][t]
                        ]
                        if len(prod_has) > max_products_per_slot:
                            model.Add(sum(prod_has) <= max_products_per_slot)

            # ── DBR 支持 ────────────────────────────────────────────────
            drum_indices = constraints.drum_workcenter_indices
            if drum_indices and enable_changeover_constraints and has:
                self._add_dbr_constraints(
                    model, x, has, constraints, time_indices, drum_indices,
                )

            # ── 软规则目标函数 ──────────────────────────────────────────

            obj_terms: list[Any] = []
            obj_values_map: dict[str, Any] = {}

            # OTD
            otd_terms = self._build_otd_objective(
                model, x, unmet, constraints, time_indices,
            )
            if otd_terms:
                obj_values_map[SoftRule.OTD_PRIORITY.value] = sum(otd_terms)
                w = int(constraints.objective_weights.get(SoftRule.OTD_PRIORITY.value, 0.35) * 1000)
                obj_terms.extend(term * w for term in otd_terms)

            # 换线最小化
            if enable_changeover_constraints and has:
                changeover_terms = self._build_changeover_objective(
                    model, has, constraints, time_indices,
                )
                if changeover_terms:
                    obj_values_map[SoftRule.SETUP_MINIMIZATION.value] = sum(changeover_terms)
                    w = int(constraints.objective_weights.get(SoftRule.SETUP_MINIMIZATION.value, 0.25) * 1000)
                    obj_terms.extend(term * w for term in changeover_terms)

            # 负荷均衡
            balance_var = self._build_balance_objective(
                model, x, constraints, time_indices,
            )
            if balance_var is not None:
                obj_values_map[SoftRule.LOAD_BALANCING.value] = balance_var
                w = int(constraints.objective_weights.get(SoftRule.LOAD_BALANCING.value, 0.15) * 1000)
                obj_terms.append(balance_var * w)

            # 瓶颈利用率
            drum_util_var = self._build_drum_utilization_objective(
                model, x, constraints, time_indices, drum_indices,
            )
            if drum_util_var is not None:
                obj_values_map[SoftRule.DRUM_UTILIZATION.value] = drum_util_var
                w = int(constraints.objective_weights.get(SoftRule.DRUM_UTILIZATION.value, 0.10) * 1000)
                obj_terms.append(drum_util_var * w)

            # unmet 惩罚
            for i in range(n_items):
                pw = int(constraints.priority_weights.get(i, 1.0) * 100)
                obj_terms.append(unmet[i] * (5000 + pw))

            if obj_terms:
                model.Minimize(sum(obj_terms))

            # ── 求解 ────────────────────────────────────────────────────
            solver_params = problem.solver_params
            max_time = solver_params.get("max_time_in_seconds", 60)
            num_workers = solver_params.get("num_workers", 4)

            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max_time
            solver.parameters.num_workers = num_workers

            logger.info("CP-SAT 求解参数: max_time={}s, num_workers={}", max_time, num_workers)
            status = solver.Solve(model)
            solve_time = time.monotonic() - start_time

            # ── 结果转换 ────────────────────────────────────────────────
            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                solve_status = (
                    SolveStatus.OPTIMAL if status == cp_model.OPTIMAL
                    else SolveStatus.FEASIBLE
                )
                tasks = self._extract_tasks(solver, x, constraints, problem)
                objective_values = self._compute_objective_values(
                    solver, obj_values_map,
                )
                logger.info(
                    "求解成功: status={}, tasks={}, time={:.2f}s",
                    solve_status.value, len(tasks), solve_time,
                )
                return SolveResult(
                    status=solve_status,
                    tasks=tasks,
                    objective_values=objective_values,
                    solve_time_seconds=solve_time,
                    solver_name="ortools-cp-sat",
                    metadata={
                        "cp_sat_status": solver.StatusName(status),
                        "objective_bound": solver.BestObjectiveBound(),
                        "wall_time": solver.WallTime(),
                    },
                )
            else:
                status_name = solver.StatusName(status)
                logger.warning("求解失败: status={}, time={:.2f}s", status_name, solve_time)
                return SolveResult(
                    status=SolveStatus.INFEASIBLE,
                    solve_time_seconds=solve_time,
                    solver_name="ortools-cp-sat",
                    metadata={"cp_sat_status": status_name},
                )

        except Exception as e:
            solve_time = time.monotonic() - start_time
            logger.error("求解异常: {}", str(e))
            import traceback
            traceback.print_exc()
            return SolveResult(
                status=SolveStatus.INFEASIBLE,
                solve_time_seconds=solve_time,
                solver_name="ortools-cp-sat",
                metadata={"error": str(e)},
            )

    def get_capabilities(self) -> SolverCapabilities:
        """返回求解器能力声明。"""
        return SolverCapabilities(
            solver_name="ortools-cp-sat",
            supported_hard_rules=list(HardRule),
            supported_soft_rules=list(SoftRule),
            max_items=100,
            max_workcenters=20,
            max_time_slots=48,
        )

    # ── 工序顺序约束 ─────────────────────────────────────────────────────

    def _add_process_order_constraints(
        self,
        model: cp_model.CpModel,
        x: dict[int, dict[int, dict[int, cp_model.IntVar]]],
        constraints: BuiltConstraints,
        time_indices: list[int],
    ) -> None:
        """添加工序顺序约束：DAG 前驱依赖。

        使用累积产量约束：对每个前驱关系 (prev → curr)，
        在任意时间槽 t，curr 的累积产量 ≤ prev 的累积产量。
        这确保了后继工序不会超前于前驱工序完成。

        DAG 并行支持：同一需求的多个并行工序（同 seq 值）互不约束，
        只约束 DAG 边上的前驱→后继关系。
        """
        # 优先使用 DAG 前驱依赖（process_predecessors），回退到线性 process_order_groups
        if constraints.process_predecessors:
            self._add_dag_predecessor_constraints(model, x, constraints, time_indices)
        else:
            self._add_linear_process_order_constraints(model, x, constraints, time_indices)

    def _add_dag_predecessor_constraints(
        self,
        model: cp_model.CpModel,
        x: dict[int, dict[int, dict[int, cp_model.IntVar]]],
        constraints: BuiltConstraints,
        time_indices: list[int],
    ) -> None:
        """DAG 前驱约束：根据 dependency_type 添加不同类型的工序顺序约束。

        支持四种依赖类型：
        - FS（完成→开始）：后继在 t 的累积 ≤ 前驱在 t-delay 的累积
        - SS（开始→开始）：后继在 t 的累积 ≤ 前驱在 t-delay 的累积（delay通常=0，允许同时开始）
        - FF（完成→完成）：后继在 t 的累积 ≤ 前驱在 t 的累积（允许同时完成）
        - SF（开始→完成）：后继在 t 的累积 ≤ 前驱在 t 的累积

        当没有 process_dependency_info 时，回退到原有 FS 逻辑。
        """
        slot_to_time_key = constraints.slot_to_time_key
        all_time_keys = sorted(set(slot_to_time_key.values()))

        # 如果有依赖详情，使用新的约束逻辑
        if constraints.process_dependency_info:
            self._add_typed_dag_constraints(model, x, constraints, time_indices, all_time_keys)
            return

        # 回退：原有 FS 累积产量约束逻辑
        edge_count = 0
        for succ_idx, pred_indices in constraints.process_predecessors.items():
            for pred_idx in pred_indices:
                # 按时间键分组前驱和后继的变量
                pred_by_time: dict[str, list[cp_model.IntVar]] = {}
                for t, w_dict in x.get(pred_idx, {}).items():
                    tk = slot_to_time_key.get(t, "")
                    if not tk:
                        continue
                    for var in w_dict.values():
                        pred_by_time.setdefault(tk, []).append(var)

                succ_by_time: dict[str, list[cp_model.IntVar]] = {}
                for t, w_dict in x.get(succ_idx, {}).items():
                    tk = slot_to_time_key.get(t, "")
                    if not tk:
                        continue
                    for var in w_dict.values():
                        succ_by_time.setdefault(tk, []).append(var)

                if not pred_by_time or not succ_by_time:
                    continue

                # 累积产量约束：后继在 t 的累积 ≤ 前驱在 t-1 的累积
                pred_cum: list[Any] = []
                succ_cum: list[Any] = []
                for tk in all_time_keys:
                    if tk in succ_by_time:
                        succ_cum.extend(succ_by_time[tk])
                    if succ_cum:
                        if pred_cum:
                            model.Add(sum(succ_cum) <= sum(pred_cum))
                            edge_count += 1
                        else:
                            model.Add(sum(succ_cum) == 0)
                            edge_count += 1
                    if tk in pred_by_time:
                        pred_cum.extend(pred_by_time[tk])

        logger.debug("DAG 前驱约束已添加（FS回退），边数={}", edge_count)

    def _add_typed_dag_constraints(
        self,
        model: cp_model.CpModel,
        x: dict[int, dict[int, dict[int, cp_model.IntVar]]],
        constraints: BuiltConstraints,
        time_indices: list[int],
        all_time_keys: list[str],
    ) -> None:
        """根据 dependency_type 添加不同类型的 DAG 约束。

        FS: succ_cum(t) ≤ pred_cum(t - delay_slots)
            delay_slots = ceil((wait_time + prep_time + setup_time) / 60)
            最少 delay=1（确保后继比前驱晚至少1个时间槽）
        SS: succ_cum(t) ≤ pred_cum(t - delay_slots)
            delay_slots 通常=0（允许同时开始），或 prep_time 转换的槽位数
        FF: succ_cum(t) ≤ pred_cum(t)
            后继累积始终不超过前驱累积（同时完成）
        SF: succ_cum(t) ≤ pred_cum(t)
            前驱开始后后继才能完成
        """
        slot_to_time_key = constraints.slot_to_time_key
        edge_count = 0
        dep_type_counts: dict[str, int] = {}

        # 预计算时间键到实际时间戳的映射（用于自然时间差计算）
        # time_key 格式: "YYYY-MM-DD_HH"
        from datetime import datetime, timedelta
        tk_to_timestamp: dict[str, datetime] = {}
        parse_fail_count = 0
        for tk in all_time_keys:
            try:
                parts = tk.split("_")
                tk_to_timestamp[tk] = datetime.strptime(f"{parts[0]} {parts[1]}:00", "%Y-%m-%d %H:%M")
            except (ValueError, IndexError):
                parse_fail_count += 1
        if parse_fail_count > 0:
            logger.warning(f"时间键解析失败: {parse_fail_count}/{len(all_time_keys)}")

        for succ_idx, dep_details in constraints.process_dependency_info.items():
            for pred_idx, dep_type, delay_slots, delay_minutes in dep_details:
                dep_type_counts[dep_type] = dep_type_counts.get(dep_type, 0) + 1

                # 按时间键分组前驱和后继的变量
                pred_by_time: dict[str, list[cp_model.IntVar]] = {}
                for t, w_dict in x.get(pred_idx, {}).items():
                    tk = slot_to_time_key.get(t, "")
                    if not tk:
                        continue
                    for var in w_dict.values():
                        pred_by_time.setdefault(tk, []).append(var)

                succ_by_time: dict[str, list[cp_model.IntVar]] = {}
                for t, w_dict in x.get(succ_idx, {}).items():
                    tk = slot_to_time_key.get(t, "")
                    if not tk:
                        continue
                    for var in w_dict.values():
                        succ_by_time.setdefault(tk, []).append(var)

                if not pred_by_time or not succ_by_time:
                    continue

                if dep_type in ("FS", "SS"):
                    # FS/SS: succ_cum(t) ≤ pred_cum(t - delay_minutes)
                    # 使用实际时间差（自然时间），而非时间槽索引偏移
                    # 例如：涂覆 wait_time=720min → delay_minutes=720
                    # 涂覆在 15:00 生产的产品，组装在 15:00+720min=次日03:00 后才能使用
                    # 由于03:00不在工作时间，实际组装从次日08:00才能开始
                    n_tk = len(all_time_keys)

                    # 预计算前驱在每个时间键的累积变量列表
                    pred_cum_at: list[list[Any]] = [[] for _ in range(n_tk)]
                    running: list[Any] = []
                    for tk_idx, tk in enumerate(all_time_keys):
                        running.extend(pred_by_time.get(tk, []))
                        pred_cum_at[tk_idx] = list(running)  # 副本

                    # 预计算每个时间键对应的"前驱在 delay_minutes 之前的累积"的时间键索引
                    # 对于后继时间键 tk，找到满足 pred_time + delay_minutes ≤ succ_time 的最大 pred_idx
                    delay_td = timedelta(minutes=delay_minutes)

                    succ_running: list[Any] = []
                    for tk_idx, tk in enumerate(all_time_keys):
                        succ_running.extend(succ_by_time.get(tk, []))
                        if not succ_running:
                            continue

                        # 计算后继当前时间键对应的时间戳
                        succ_ts = tk_to_timestamp.get(tk)
                        if not succ_ts:
                            continue

                        # 前驱必须在此时间之前 delay_minutes 完成生产
                        cutoff_ts = succ_ts - delay_td

                        # 找到前驱在 cutoff_ts 之前的累积
                        # 即找到最后一个时间戳 ≤ cutoff_ts 的前驱累积
                        pred_delay_idx = -1
                        for pi in range(n_tk):
                            pts = tk_to_timestamp.get(all_time_keys[pi])
                            if pts and pts <= cutoff_ts:
                                pred_delay_idx = pi

                        if pred_delay_idx < 0:
                            # 没有前驱在 cutoff 之前生产，后继累积必须为0
                            model.Add(sum(succ_running) == 0)
                            edge_count += 1
                        elif pred_cum_at[pred_delay_idx]:
                            model.Add(sum(succ_running) <= sum(pred_cum_at[pred_delay_idx]))
                            edge_count += 1
                        else:
                            model.Add(sum(succ_running) == 0)
                            edge_count += 1

                elif dep_type in ("FF", "SF"):
                    # FF/SF: succ_cum(t) ≤ pred_cum(t)
                    # 后继在 t 的累积不超过前驱在 t 的累积
                    pred_cum: list[Any] = []
                    succ_cum: list[Any] = []
                    for tk in all_time_keys:
                        # 先累积后继
                        if tk in succ_by_time:
                            succ_cum.extend(succ_by_time[tk])
                        # 先累积前驱
                        if tk in pred_by_time:
                            pred_cum.extend(pred_by_time[tk])
                        # 添加约束：后继累积 ≤ 前驱累积
                        if succ_cum:
                            if pred_cum:
                                model.Add(sum(succ_cum) <= sum(pred_cum))
                                edge_count += 1
                            else:
                                model.Add(sum(succ_cum) == 0)
                                edge_count += 1

        logger.debug(
            "DAG 类型化约束已添加，边数={}，依赖类型分布={}",
            edge_count, dep_type_counts,
        )

    def _add_linear_process_order_constraints(
        self,
        model: cp_model.CpModel,
        x: dict[int, dict[int, dict[int, cp_model.IntVar]]],
        constraints: BuiltConstraints,
        time_indices: list[int],
    ) -> None:
        """线性工序顺序约束（向后兼容）：相邻 seq 之间的累积产量约束。

        后继在 t 的累积 ≤ 前驱在 t-1 的累积，确保工序顺序正确。
        """
        slot_to_time_key = constraints.slot_to_time_key
        all_time_keys = sorted(set(slot_to_time_key.values()))

        for demand_id, group in constraints.process_order_groups.items():
            if len(group) < 2:
                continue

            for k in range(len(group) - 1):
                i_prev = group[k][0]
                i_next = group[k + 1][0]

                # 按时间键分组
                prev_by_time: dict[str, list[cp_model.IntVar]] = {}
                for t, w_dict in x.get(i_prev, {}).items():
                    tk = slot_to_time_key.get(t, "")
                    if not tk:
                        continue
                    for var in w_dict.values():
                        prev_by_time.setdefault(tk, []).append(var)

                next_by_time: dict[str, list[cp_model.IntVar]] = {}
                for t, w_dict in x.get(i_next, {}).items():
                    tk = slot_to_time_key.get(t, "")
                    if not tk:
                        continue
                    for var in w_dict.values():
                        next_by_time.setdefault(tk, []).append(var)

                if not prev_by_time or not next_by_time:
                    continue

                # 累积产量约束：后继在 t 的累积 ≤ 前驱在 t-1 的累积
                prev_cum_vars: list[Any] = []
                next_cum_vars: list[Any] = []
                for tk in all_time_keys:
                    if tk in next_by_time:
                        next_cum_vars.extend(next_by_time[tk])
                    if next_cum_vars:
                        if prev_cum_vars:
                            model.Add(sum(next_cum_vars) <= sum(prev_cum_vars))
                        else:
                            model.Add(sum(next_cum_vars) == 0)
                    if tk in prev_by_time:
                        prev_cum_vars.extend(prev_by_time[tk])

        logger.debug("线性工序顺序约束已添加，需求组数={}", len(constraints.process_order_groups))

    # ── DBR 约束 ───────────────────────────────────────────────────────────

    def _add_dbr_constraints(
        self,
        model: cp_model.CpModel,
        x: dict[int, dict[int, dict[int, cp_model.IntVar]]],
        has: dict[int, dict[int, dict[int, cp_model.IntVar]]],
        constraints: BuiltConstraints,
        time_indices: list[int],
        drum_indices: set[int],
    ) -> None:
        """添加 DBR 约束：Drum 产线按优先级紧密排列。"""
        sorted_items = sorted(
            constraints.priority_weights.keys(),
            key=lambda i: constraints.priority_weights[i],
            reverse=True,
        )

        for rank, i in enumerate(sorted_items):
            for j in sorted_items[rank + 1:]:
                pw_i = constraints.priority_weights[i]
                pw_j = constraints.priority_weights[j]
                if pw_i <= pw_j:
                    continue
                for w in drum_indices:
                    for t_idx in range(len(time_indices) - 1):
                        i_has_any = []
                        j_has_any = []
                        for t2 in time_indices[:t_idx + 1]:
                            if t2 in has[i] and w in has[i][t2]:
                                i_has_any.append(has[i][t2][w])
                            if t2 in has[j] and w in has[j][t2]:
                                j_has_any.append(has[j][t2][w])

                        if i_has_any and j_has_any:
                            j_early = model.NewBoolVar(f"dbr_j_early_{j}_{t_idx}_{w}")
                            model.Add(sum(j_has_any) >= 1).OnlyEnforceIf(j_early)
                            model.Add(sum(j_has_any) == 0).OnlyEnforceIf(j_early.Not())

                            i_early = model.NewBoolVar(f"dbr_i_early_{i}_{t_idx}_{w}")
                            model.Add(sum(i_has_any) >= 1).OnlyEnforceIf(i_early)
                            model.Add(sum(i_has_any) == 0).OnlyEnforceIf(i_early.Not())

                            model.AddImplication(j_early, i_early)

    # ── 软规则目标函数构建 ─────────────────────────────────────────────────

    def _build_otd_objective(
        self,
        model: cp_model.CpModel,
        x: dict[int, dict[int, dict[int, cp_model.IntVar]]],
        unmet: dict[int, cp_model.IntVar],
        constraints: BuiltConstraints,
        time_indices: list[int],
    ) -> list[Any]:
        """构建 OTD 目标：延迟惩罚 × 优先级权重。"""
        terms: list[Any] = []
        n_items = len(constraints.demands)

        for i in range(n_items):
            due = constraints.due_dates.get(i, len(time_indices) - 1)
            pw = int(constraints.priority_weights.get(i, 1.0) * 100)

            late_terms = []
            for t in time_indices:
                if t > due:
                    if t in x[i]:
                        for w, var in x[i][t].items():
                            late_terms.append(var)

            if late_terms:
                late_sum = sum(late_terms)
                terms.append(late_sum * pw)

            terms.append(unmet[i] * pw)

        return terms

    def _build_changeover_objective(
        self,
        model: cp_model.CpModel,
        has: dict[int, dict[int, dict[int, cp_model.IntVar]]],
        constraints: BuiltConstraints,
        time_indices: list[int],
    ) -> list[Any]:
        """构建换线最小化目标。"""
        terms: list[Any] = []
        n_items = len(constraints.products)

        for t_idx in range(len(time_indices) - 1):
            t = time_indices[t_idx]
            t_next = time_indices[t_idx + 1]
            for w in range(len(constraints.capacity)):
                cur_items = []
                next_items = []
                for i in range(n_items):
                    if t in has[i] and w in has[i][t]:
                        cur_items.append(i)
                    if t_next in has[i] and w in has[i][t_next]:
                        next_items.append(i)

                for i_cur in cur_items:
                    for i_next in next_items:
                        if i_cur == i_next:
                            continue
                        prod_cur = constraints.products.get(i_cur, "")
                        prod_next = constraints.products.get(i_next, "")
                        ct = constraints.changeover_time.get(
                            (prod_cur, prod_next), 1,
                        )
                        switch = model.NewBoolVar(
                            f"sw_{t}_{w}_{i_cur}_{i_next}",
                        )
                        model.AddImplication(has[i_cur][t][w], switch)
                        model.AddImplication(has[i_next][t_next][w], switch)
                        model.AddImplication(has[i_cur][t][w].Not(), switch.Not())
                        model.AddImplication(has[i_next][t_next][w].Not(), switch.Not())

                        terms.append(switch * int(ct * 100))

        return terms

    def _build_balance_objective(
        self,
        model: cp_model.CpModel,
        x: dict[int, dict[int, dict[int, cp_model.IntVar]]],
        constraints: BuiltConstraints,
        time_indices: list[int],
    ) -> cp_model.IntVar | None:
        """构建负荷均衡目标（产线间均衡 + 时间维度峰值惩罚）。

        产线间均衡：各产线总负荷差异（max - min）最小化
        时间维度均衡：惩罚超过平均负荷 1.5 倍的时段，避免峰值（不过度分散任务）
        """
        n_wc = len(constraints.capacity)
        n_items = len(constraints.demands)
        balance_terms: list[Any] = []

        # 1. 产线间均衡：各产线总负荷差异
        if n_wc >= 2:
            line_totals: list[Any] = []
            for w in range(n_wc):
                total_vars = []
                for i in range(n_items):
                    for t in time_indices:
                        if t in x[i] and w in x[i][t]:
                            total_vars.append(x[i][t][w])
                if total_vars:
                    lt = model.NewIntVar(0, 10**7, f"line_total_{w}")
                    model.Add(lt == sum(total_vars))
                    line_totals.append(lt)

            if len(line_totals) >= 2:
                max_total = model.NewIntVar(0, 10**7, "max_line_total")
                min_total = model.NewIntVar(0, 10**7, "min_line_total")
                model.AddMaxEquality(max_total, line_totals)
                model.AddMinEquality(min_total, line_totals)
                line_diff = model.NewIntVar(0, 10**7, "line_balance_diff")
                model.Add(line_diff == max_total - min_total)
                balance_terms.append(line_diff)

        # 2. 时间维度均衡：惩罚超过阈值的时段负荷（避免峰值，不过度分散）
        total_demand = sum(constraints.demands.values())
        n_slots = len(time_indices)
        if total_demand > 0 and n_slots > 0:
            # 阈值 = 平均负荷 * 2.0（允许 100% 波动，避免过度分散任务）
            threshold = int(total_demand / n_slots * 2.0)
            if threshold > 0:
                over_terms: list[Any] = []
                for t in time_indices:
                    slot_vars = []
                    for i in range(n_items):
                        if t in x[i]:
                            for w in range(n_wc):
                                if w in x[i][t]:
                                    slot_vars.append(x[i][t][w])
                    if slot_vars:
                        st = model.NewIntVar(0, 10**7, f"slot_total_{t}")
                        model.Add(st == sum(slot_vars))
                        # over >= st - threshold, over >= 0
                        over = model.NewIntVar(0, 10**7, f"slot_over_{t}")
                        model.Add(over >= st - threshold)
                        over_terms.append(over)
                if over_terms:
                    balance_terms.append(sum(over_terms))

        if not balance_terms:
            return None

        total_balance = model.NewIntVar(0, 10**8, "total_balance")
        model.Add(total_balance == sum(balance_terms))
        return total_balance

    def _build_drum_utilization_objective(
        self,
        model: cp_model.CpModel,
        x: dict[int, dict[int, dict[int, cp_model.IntVar]]],
        constraints: BuiltConstraints,
        time_indices: list[int],
        drum_indices: set[int],
    ) -> cp_model.IntVar | None:
        """构建瓶颈利用率目标。"""
        if not drum_indices:
            return None

        drum_cap_total = 0
        drum_used_vars: list[Any] = []
        for w in drum_indices:
            for t in time_indices:
                cap = math.ceil(constraints.capacity.get(w, {}).get(t, 0))
                drum_cap_total += cap
                for i in range(len(constraints.demands)):
                    if t in x[i] and w in x[i][t]:
                        drum_used_vars.append(x[i][t][w])

        if not drum_used_vars:
            return None

        drum_used = model.NewIntVar(0, drum_cap_total, "drum_used")
        model.Add(drum_used == sum(drum_used_vars))

        drum_idle = model.NewIntVar(0, drum_cap_total, "drum_idle")
        model.Add(drum_idle == drum_cap_total - drum_used)
        return drum_idle

    # ── 结果提取 ───────────────────────────────────────────────────────────

    def _extract_tasks(
        self,
        solver: cp_model.CpSolver,
        x: dict[int, dict[int, dict[int, cp_model.IntVar]]],
        constraints: BuiltConstraints,
        problem: SchedulingProblem,
    ) -> list[ScheduledTask]:
        """从 CP-SAT 解中提取排产任务列表。

        V2: 使用展开项和虚拟工作中心信息，映射回真实产线+工序。
        """
        tasks: list[ScheduledTask] = []

        total_val = 0
        var_count = 0
        for i, t_dict in x.items():
            for t, w_dict in t_dict.items():
                for w, var in w_dict.items():
                    var_count += 1
                    try:
                        val = solver.Value(var)
                    except Exception:
                        val = 0
                    total_val += val
                    if val > 0:
                        # 从展开项获取需求+工序信息
                        ei = constraints.expanded_items.get(i)
                        # 从虚拟工作中心获取产线+工序信息
                        vwc = constraints.virtual_workcenters.get(w)

                        # 原始需求 ID
                        demand_id = ei.demand_id if ei else str(i)
                        product_id = ei.product_id if ei else ""

                        # 真实产线 ID 和工序信息
                        real_line_id = vwc.line_id if vwc else str(w)
                        process_id = ei.process_id if ei else ""
                        process_code = ei.process_code if ei else ""
                        process_name = ei.process_name if ei else ""
                        seq = ei.seq if ei else 0
                        constraint_type = ei.constraint_type if ei else ""

                        tasks.append(ScheduledTask(
                            item_id=demand_id,
                            order_item_id=demand_id,
                            workcenter_id=real_line_id,
                            time_slot=t,
                            slot_id=t,
                            quantity=float(val),
                            product=product_id,
                            product_id=product_id,
                            process_id=process_id,
                            process_code=process_code,
                            process_name=process_name,
                            seq=seq,
                            constraint_type=constraint_type,
                            dependency_type=ei.dependency_type if ei else "",
                            wait_time=ei.wait_time if ei else 0,
                            prep_time=ei.prep_time if ei else 0,
                        ))

        logger.debug(
            "结果提取: var_count={}, total_val={}, tasks={}",
            var_count, total_val, len(tasks),
        )

        return tasks

    def _compute_objective_values(
        self,
        solver: cp_model.CpSolver,
        obj_values_map: dict[str, Any],
    ) -> dict[str, float]:
        """计算各软规则的实际目标值。"""
        result: dict[str, float] = {}
        for name, expr in obj_values_map.items():
            try:
                result[name] = float(solver.Value(expr))
            except Exception:
                result[name] = 0.0
        return result
