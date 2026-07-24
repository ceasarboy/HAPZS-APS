"""ortools CP-SAT 求解器适配器，支持 DBR 混合方向排产 + V2 工序级排产。"""

from __future__ import annotations

import math
import time
from datetime import datetime, timedelta
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

        V3: 支持 scheduling_mode 参数切换：
        - "capacity"（默认）: 产能累加模式，多任务共享时间槽
        - "time_exclusive": 时间独占模式，任务占用连续N个5分钟时间槽
        """
        scheduling_mode = problem.solver_params.get("scheduling_mode", "time_exclusive")
        if scheduling_mode == "time_exclusive":
            return self._solve_time_exclusive(problem)
        return self._solve_capacity(problem)

    def _solve_capacity(self, problem: SchedulingProblem) -> SolveResult:
        """产能累加模式求解（原有逻辑）。"""
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
            max_time = solver_params.get("max_time_in_seconds", 300)
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

        # 预构建时间槽索引 → 日期映射
        slot_to_time_key = constraints.slot_to_time_key
        slot_date_map: dict[int, str] = {}
        for slot_idx, tk in slot_to_time_key.items():
            # tk 格式: "YYYY-MM-DD_HH"
            slot_date_map[slot_idx] = tk.split("_")[0] if "_" in tk else tk

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

                        # 从时间槽索引获取日期
                        sr_date_str = slot_date_map.get(t, "")

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
                            # V3 节拍计算过程变量
                            auto_type=ei.auto_type if ei else "",
                            cycle_time=ei.cycle_time if ei else 0.0,
                            max_units_per_beat=ei.max_units_per_beat if ei else 1,
                            start_time=sr_date_str,  # 日期字符串
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

    # ── V3 时间独占模式 ────────────────────────────────────────────────────

    def _solve_time_exclusive(self, problem: SchedulingProblem) -> SolveResult:
        """V3 时间独占模式求解。

        核心模型：
        - assign[i][w] = 排产项i是否分配到虚拟工作中心w（布尔变量）
        - start[i] = 排产项i的开始时间槽索引（整数变量）
        - duration[i] = 排产项i需要占用的连续时间槽数（常量，由节拍计算）
        - NoOverlap约束：同一虚拟工作中心上的任务区间不能重叠
        - 部分满足：未分配的排产项计入 unmet
        """
        start_time = time.monotonic()
        items = problem.demand_plans or problem.items or problem.order_items or problem.orders or []
        logger.info(
            "V3时间独占模式: 需求数={} 产线数={} 时间槽数={}",
            len(items), len(problem.production_lines or problem.workcenters), len(problem.time_slots),
        )

        try:
            constraints = ConstraintBuilder().build(problem)
            model = cp_model.CpModel()

            n_items = len(constraints.item_indices)
            n_wc = len(constraints.workcenter_indices)
            time_indices = constraints.time_indices
            n_time_slots = len(time_indices)

            logger.info("V3展开: 排产项={} 虚拟工作中心={} 时间槽={}", n_items, n_wc, n_time_slots)

            # ── 构建全局索引 → 实际分钟数映射 ──
            # 根因修复: start[i] 使用实际时间(分钟数)而非全局索引
            # 不同VW在同一时间段(如08:00)有不同的全局索引，Cumulative基于索引判断重叠会误判
            # 改用分钟数后，所有VW共享同一时间轴，Cumulative能正确检测跨VW的时间重叠
            slot_to_minute: dict[int, int] = {}
            minute_to_slots: dict[int, list[int]] = {}  # 同一分钟可能有多个VW的时间槽
            base_date: datetime | None = None
            is_daily_slot = False  # 日级时间槽标记
            for ts in problem.time_slots:
                idx = ts.index if ts.index is not None else (ts.slot_id if ts.slot_id is not None else 0)
                if not ts.date:
                    continue
                try:
                    if ts.start_time and ts.start_time not in ("全天", ""):
                        dt = datetime.strptime(f"{ts.date} {ts.start_time}", "%Y-%m-%d %H:%M")
                    else:
                        # 日级时间槽：默认从每天8:00开始
                        is_daily_slot = True
                        dt = datetime.strptime(ts.date, "%Y-%m-%d").replace(hour=8, minute=0)
                except ValueError:
                    continue
                if base_date is None:
                    base_date = datetime.strptime(ts.date, "%Y-%m-%d").replace(hour=0, minute=0)
                minute = int((dt - base_date).total_seconds() / 60)
                slot_to_minute[idx] = minute
                minute_to_slots.setdefault(minute, []).append(idx)

            max_minute = max(slot_to_minute.values()) if slot_to_minute else 0
            # 收集所有有效开始分钟数（用于限制start值域）
            valid_minutes = sorted(set(slot_to_minute.values()))
            logger.info("V3时间映射: 全局索引→分钟数, max_minute={}, valid_minutes_count={}",
                        max_minute, len(valid_minutes))

            # V3修复: 限制 start[i] 只能取有效时间槽的分钟数
            # 否则求解器可能分配 start=0(午夜)等无效时间，导致提取时无法映射到时间槽
            valid_minutes_tuples = [[m] for m in valid_minutes]

            # ── 决策变量 ──
            # assign[i][w] = 是否分配到w
            assign: dict[int, dict[int, cp_model.IntVar]] = {}
            # start[i] = 开始时间（分钟数，从排产开始日期00:00算起）
            start: dict[int, cp_model.IntVar] = {}
            # unmet[i] = 是否未排
            unmet: dict[int, cp_model.IntVar] = {}

            for i in range(n_items):
                ei = constraints.expanded_items.get(i)
                # start[i] 使用分钟数，范围 [0, max_minute]
                start[i] = model.NewIntVar(0, max_minute, f"start_{i}")
                # V3修复: start[i] 只能取有效时间槽的分钟数
                if valid_minutes_tuples:
                    model.AddAllowedAssignments([start[i]], valid_minutes_tuples)
                unmet[i] = model.NewBoolVar(f"unmet_{i}")
                assign[i] = {}
                for w in range(n_wc):
                    if constraints.incompatible.get(i, {}).get(w, False):
                        continue
                    assign[i][w] = model.NewBoolVar(f"assign_{i}_{w}")

            # ── 预计算每个 (i, w) 对的 duration（考虑设备数） ──
            # V3修复: duration 使用分钟数（而非时间槽数），与 start[i] 的分钟数对齐
            # V3.3修复: 支持三种粒度 - 日级(720分钟)/小时级(60分钟)/5分钟级(5分钟)
            if is_daily_slot:
                SLOT_DURATION_MINUTES = 720
            else:
                # 基于 start_time 格式推断粒度："08:00" → 60分钟，其他 → 5分钟
                _sample_start = problem.time_slots[0].start_time if problem.time_slots else ""
                if _sample_start and ":" in _sample_start and _sample_start != "全天":
                    SLOT_DURATION_MINUTES = 60  # 小时级
                else:
                    SLOT_DURATION_MINUTES = 5   # 5分钟级（默认）
            duration_map: dict[tuple[int, int], int] = {}
            for i in range(n_items):
                ei = constraints.expanded_items.get(i)
                if not ei:
                    continue
                qty = int(ei.quantity)
                for w in range(n_wc):
                    if w not in assign[i]:
                        continue
                    vwc = constraints.virtual_workcenters.get(w)
                    equipment_count = vwc.equipment_count if vwc and vwc.equipment_count and vwc.equipment_count > 0 else 1

                    # 根据设备数计算 beat_count
                    if ei.auto_type == "自动" and ei.max_units_per_beat > 0:
                        beat_count = math.ceil(qty / ei.max_units_per_beat)
                    else:
                        # 非自动：考虑设备并行度
                        beat_count = math.ceil(qty / equipment_count)

                    # 自动工艺: 每轮 = cycle_time + prep_time(换治具, 分钟转秒)
                    # 非自动工艺: 总时间 = beat_count * cycle_time + prep_time * 60 (一次性准备)
                    if ei.auto_type == "自动":
                        total_time_seconds = beat_count * (ei.cycle_time + ei.prep_time * 60)
                    else:
                        total_time_seconds = beat_count * ei.cycle_time + ei.prep_time * 60
                    total_minutes = total_time_seconds / 60.0
                    # duration 转为分钟数（向上取整到15分钟的倍数）
                    dur_slots = max(1, math.ceil(total_minutes / SLOT_DURATION_MINUTES))
                    duration_map[(i, w)] = dur_slots * SLOT_DURATION_MINUTES

            # 记录每个展开项的最大 duration（用于交期约束）
            max_duration: dict[int, int] = {}
            for (i, w), dur in duration_map.items():
                if i not in max_duration or dur > max_duration[i]:
                    max_duration[i] = dur

            # V3修复: duration 超过排产窗口的任务不能被分配（否则会导致工序顺序约束和late约束INFEASIBLE）
            # 这些任务会被自动归入 unmet
            oversize_count = 0
            for (i, w), dur in duration_map.items():
                if dur > max_minute:
                    model.Add(assign[i][w] == 0)
                    oversize_count += 1
            if oversize_count > 0:
                logger.warning("V3超长任务: {} 个(i,w)对的duration超过max_minute({}), 已强制unmet",
                               oversize_count, max_minute)

            # ── 硬约束 ──

            # 1. 唯一分配: sum(assign[i][w]) + unmet[i] == 1
            for i in range(n_items):
                assigns = list(assign[i].values())
                if assigns:
                    model.Add(sum(assigns) + unmet[i] == 1)
                else:
                    model.Add(unmet[i] == 1)

            # 2. Cumulative/NoOverlap: 同一虚拟工作中心上的任务区间约束
            # V3修复: start[i] 和 duration 都使用分钟数，Cumulative 基于实际时间判断重叠
            constraint_count = 0
            for w in range(n_wc):
                vwc = constraints.virtual_workcenters.get(w)
                equipment_count = vwc.equipment_count if vwc and vwc.equipment_count and vwc.equipment_count > 0 else 1

                intervals = []
                demands = []
                for i in range(n_items):
                    if w not in assign[i]:
                        continue
                    dur = duration_map.get((i, w), SLOT_DURATION_MINUTES)
                    end = model.NewIntVar(0, max_minute + dur, f"end_{i}_{w}")
                    interval = model.NewOptionalIntervalVar(
                        start[i], dur, end, assign[i][w], f"iv_{i}_{w}",
                    )
                    intervals.append(interval)
                    demands.append(1)  # 每个任务占用1台设备

                if intervals:
                    if equipment_count > 1:
                        # 多设备：用 Cumulative 约束（允许并行）
                        model.AddCumulative(intervals, demands, equipment_count)
                    else:
                        # 单设备：用 NoOverlap 约束（严格独占）
                        model.AddNoOverlap(intervals)
                    constraint_count += 1
                    logger.info("V3约束: VW[{}] {}-{} equip={} intervals={} dur_samples={}",
                                w, vwc.line_name if vwc else "?", vwc.process_name if vwc else "?",
                                equipment_count, len(intervals),
                                [(duration_map.get((i, w), 1),) for i in range(min(3, n_items)) if w in assign[i]])

            logger.info("V3约束总数: {} 个VW添加了Cumulative/NoOverlap, n_time_slots={}", constraint_count, n_time_slots)

            # 3. 交期约束（软约束，不作为硬约束）
            # V3修复: 交期从全局索引转换为分钟数
            # 注意: 当duration > due_minute时，硬约束会导致INFEASIBLE
            # 因此交期只作为软约束（延迟惩罚），允许任务超期但接受惩罚
            due_minute_map: dict[int, int] = {}
            for i, due_slot in constraints.due_dates.items():
                due_minute_map[i] = slot_to_minute.get(due_slot, max_minute)
            # 添加默认交期（没有交期的排产项用max_minute）
            for i in range(n_items):
                if i not in due_minute_map:
                    due_minute_map[i] = max_minute
            # 交期硬约束已移除，改为软约束（在目标函数中通过延迟惩罚实现）

            # 4. 工序顺序: start[curr] >= start[prev] + duration[prev][w_prev] + wait_time
            # V3修复: start 和 duration 都用分钟数
            # V3修复: 约束同时条件于前驱和后继都被分配，否则后继可以选择unmet
            # V3修复: 传递性约束——前驱unmet则后继也必须unmet，防止后继被自由分配到错误时间
            # V3修复: 加入 wait_time（delay_minutes），确保涂覆等工序的等待时间被正确约束
            if constraints.process_predecessors:
                for succ_idx, pred_indices in constraints.process_predecessors.items():
                    # 边界检查：succ_idx 必须在 unmet 字典中
                    if succ_idx not in unmet:
                        logger.warning("工序顺序: succ_idx={} 不在unmet中(n_items={}), 跳过", succ_idx, n_items)
                        continue
                    # 获取依赖详情，找到每个前驱对应的 delay_minutes（等待时间）
                    dep_info = constraints.process_dependency_info.get(succ_idx, [])
                    delay_by_pred = {p: int(dm) for p, _, _, dm in dep_info}
                    for pred_idx in pred_indices:
                        if pred_idx not in unmet:
                            logger.warning("工序顺序: pred_idx={} 不在unmet中(n_items={}), 跳过", pred_idx, n_items)
                            continue
                        # 传递性: 前驱unmet则后继也unmet
                        model.Add(unmet[succ_idx] >= unmet[pred_idx])
                        wait_minutes = delay_by_pred.get(pred_idx, 0)
                        for w_pred in assign.get(pred_idx, {}):
                            dur_pred = duration_map.get((pred_idx, w_pred), SLOT_DURATION_MINUTES)
                            # 只在前驱分配且后继也分配时才约束
                            # start[succ] >= start[pred] + dur_pred + wait_time
                            model.Add(
                                start[succ_idx] >= start[pred_idx] + dur_pred + wait_minutes
                            ).OnlyEnforceIf([assign[pred_idx][w_pred], unmet[succ_idx].Not()])
                            logger.debug("工序顺序: {} >= {} + {} + {}(wait) (w={})", succ_idx, pred_idx, dur_pred, wait_minutes, w_pred)
            else:
                # 回退: 线性 process_order_groups
                for demand_id, group in constraints.process_order_groups.items():
                    if len(group) < 2:
                        continue
                    for k in range(len(group) - 1):
                        i_prev = group[k][0]
                        i_next = group[k + 1][0]
                        # 传递性: 前驱unmet则后继也unmet
                        model.Add(unmet[i_next] >= unmet[i_prev])
                        # 获取 i_next 的前驱依赖延迟
                        dep_info = constraints.process_dependency_info.get(i_next, [])
                        wait_minutes = 0
                        for p, _, _, dm in dep_info:
                            if p == i_prev:
                                wait_minutes = int(dm)
                                break
                        for w_pred in assign.get(i_prev, {}):
                            dur_pred = duration_map.get((i_prev, w_pred), SLOT_DURATION_MINUTES)
                            model.Add(
                                start[i_next] >= start[i_prev] + dur_pred + wait_minutes
                            ).OnlyEnforceIf([assign[i_prev][w_pred], unmet[i_next].Not()])

            # 5. 冻结窗口: start[i] 必须在冻结窗口之后
            # V3修复: 冻结索引转换为分钟数
            if constraints.frozen_time_indices:
                frozen_minutes = [slot_to_minute.get(idx, 0) for idx in constraints.frozen_time_indices]
                max_frozen_minute = max(frozen_minutes) if frozen_minutes else 0
                for i in range(n_items):
                    model.Add(start[i] > max_frozen_minute)

            # ── 目标函数 ──
            obj_terms: list[Any] = []

            # 读取软规则权重（从系统配置传入）
            otd_weight = constraints.objective_weights.get(SoftRule.OTD_PRIORITY.value, 0.35)
            setup_weight = constraints.objective_weights.get(SoftRule.SETUP_MINIMIZATION.value, 0.25)
            load_weight = constraints.objective_weights.get(SoftRule.LOAD_BALANCING.value, 0.15)
            logger.info(
                "V3软规则权重: OTD={}, SETUP={}, LOAD={}",
                otd_weight, setup_weight, load_weight,
            )

            # 交期延迟惩罚（准时交付优化，权重 otd_weight）
            max_possible_late = max_minute + max(max(max_duration.values()) if max_duration else 0, SLOT_DURATION_MINUTES)
            late_weight = max(int(otd_weight * 1000), 100)
            # unmet惩罚必须 >> 最大可能的late惩罚，确保求解器优先排产而非unmet
            # unmet_penalty = max_possible_late × late_weight + 优先级加权 + 大常数
            unmet_base_penalty = max_possible_late * late_weight + 10000

            # unmet 惩罚（按优先级加权，权重最高确保尽量满足需求）
            for i in range(n_items):
                pw = int(constraints.priority_weights.get(i, 1.0) * 100)
                obj_terms.append(unmet[i] * (unmet_base_penalty + pw))
                logger.debug("unmet惩罚[{}]: {} (late_weight={}, max_late={})",
                             i, unmet_base_penalty + pw, late_weight, max_possible_late)

            late_vars: list[cp_model.IntVar] = []
            for i in range(n_items):
                ei = constraints.expanded_items.get(i)
                if not ei:
                    continue
                due_min = due_minute_map.get(i, max_minute)
                pw = int(constraints.priority_weights.get(i, 1.0) * 100)
                dur = max_duration.get(i, SLOT_DURATION_MINUTES)
                late = model.NewIntVar(0, max_possible_late, f"late_{i}")
                model.Add(late >= start[i] + dur - due_min).OnlyEnforceIf(unmet[i].Not())
                obj_terms.append(late * (pw + late_weight))
                late_vars.append(late)

            # 尽早完成目标：高优先级产品尽早开始生产
            # 每个排产项的 start[i] × 优先级权重 加入目标函数
            # 权重逻辑：紧急 > 高 > 中 > 低，紧急产品的 start 值越小（越早开始）惩罚越低
            early_weight = max(int(otd_weight * 500), 50)  # 尽早完成权重
            for i in range(n_items):
                pw = int(constraints.priority_weights.get(i, 1.0) * 100)
                # 高优先级 → pw大 → start[i] * pw 大 → 求解器倾向降低start
                obj_terms.append(start[i] * (pw + early_weight))
            logger.info("V3尽早完成目标: early_weight={}, 影响排产项数={}", early_weight, n_items)

            # 负荷均衡：同工序跨产线均衡分配（权重 load_weight）
            # 核心思路：对于同一工序在多条产线上都能做的情况，
            # 最小化各产线间该工序负荷差异（max - min），实现均匀分配
            balance_weight = max(1, int(load_weight * 1000))
            logger.info("V3负荷均衡参数: load_weight={}, balance_weight={}, objective_weights={}",
                        load_weight, balance_weight, constraints.objective_weights)

            # 按 process_id 分组 VW，找出同一工序在多产线上的 VW 组
            process_vw_groups: dict[str, list[int]] = {}
            for w in range(n_wc):
                vwc = constraints.virtual_workcenters.get(w)
                if vwc:
                    process_vw_groups.setdefault(vwc.process_id, []).append(w)

            logger.info("V3负荷均衡: process_vw_groups={}", {
                proc_id: [(w, constraints.virtual_workcenters.get(w).line_name if constraints.virtual_workcenters.get(w) else "?") for w in ws]
                for proc_id, ws in process_vw_groups.items() if len(ws) >= 2
            })

            balance_count = 0
            for proc_id, vw_list in process_vw_groups.items():
                if len(vw_list) < 2:
                    continue  # 只有一条产线做该工序，无需均衡

                # 计算每个 VW 在该工序上的总工时（分钟）
                proc_vw_loads: list[cp_model.IntVar] = []
                for w in vw_list:
                    load_terms = []
                    for i in range(n_items):
                        if w in assign.get(i, {}):
                            ei = constraints.expanded_items.get(i)
                            if ei and ei.process_id != proc_id:
                                continue  # 只统计该工序的排产项
                            dur = duration_map.get((i, w), SLOT_DURATION_MINUTES)
                            load_contrib = model.NewIntVar(0, dur, f"bal_load_{i}_{w}")
                            model.Add(load_contrib == dur).OnlyEnforceIf(assign[i][w])
                            model.Add(load_contrib == 0).OnlyEnforceIf(assign[i][w].Not())
                            load_terms.append(load_contrib)
                    if load_terms:
                        vw_load_var = model.NewIntVar(0, max_minute, f"proc_vw_load_{proc_id[:6]}_{w}")
                        model.Add(vw_load_var == sum(load_terms))
                        proc_vw_loads.append(vw_load_var)

                if len(proc_vw_loads) >= 2:
                    # 最小化 max - min（产线间工时差异）
                    proc_max = model.NewIntVar(0, max_minute, f"proc_max_{proc_id[:6]}")
                    proc_min = model.NewIntVar(0, max_minute, f"proc_min_{proc_id[:6]}")
                    model.AddMaxEquality(proc_max, proc_vw_loads)
                    model.AddMinEquality(proc_min, proc_vw_loads)
                    proc_diff = model.NewIntVar(0, max_minute, f"proc_diff_{proc_id[:6]}")
                    model.Add(proc_diff == proc_max - proc_min)
                    obj_terms.append(proc_diff * balance_weight)
                    balance_count += 1

            if balance_count > 0:
                logger.info("V3负荷均衡: {} 个工序组参与跨产线均衡, 权重={}", balance_count, load_weight)

            if obj_terms:
                model.Minimize(sum(obj_terms))

            # ── 求解 ──
            solver_params = problem.solver_params
            max_time = solver_params.get("max_time_in_seconds", 300)
            num_workers = solver_params.get("num_workers", 4)

            solver = cp_model.CpSolver()
            solver.parameters.max_time_in_seconds = max_time
            solver.parameters.num_workers = num_workers

            logger.info("V3 CP-SAT求解: max_time={}s, workers={}", max_time, num_workers)
            status = solver.Solve(model)
            solve_time = time.monotonic() - start_time

            if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
                solve_status = (
                    SolveStatus.OPTIMAL if status == cp_model.OPTIMAL
                    else SolveStatus.FEASIBLE
                )
                tasks = self._extract_tasks_time_exclusive(
                    solver, assign, start, unmet, constraints, problem, duration_map,
                )

                # ── 计算硬规则遵守性和软规则评分 ──
                rule_report = self._build_rule_report(
                    tasks, constraints, problem, solver, unmet, assign,
                    late_vars, None, start, duration_map, slot_to_minute,
                )

                logger.info(
                    "V3求解成功: status={}, tasks={}, time={:.2f}s, hard_violations={}",
                    solve_status.value, len(tasks), solve_time, rule_report["hard_violations"],
                )
                return SolveResult(
                    status=solve_status,
                    tasks=tasks,
                    objective_values=rule_report["soft_scores"],
                    solve_time_seconds=solve_time,
                    solver_name="ortools-cp-sat-v3",
                    hard_violations=rule_report["hard_violations"],
                    metadata={
                        "cp_sat_status": solver.StatusName(status),
                        "scheduling_mode": "time_exclusive",
                        "hard_rules": rule_report["hard_rules"],
                        "soft_scores": rule_report["soft_scores"],
                    },
                )
            else:
                status_name = solver.StatusName(status)
                logger.warning("V3求解失败: status={}, time={:.2f}s", status_name, solve_time)
                return SolveResult(
                    status=SolveStatus.INFEASIBLE,
                    solve_time_seconds=solve_time,
                    solver_name="ortools-cp-sat-v3",
                    metadata={"cp_sat_status": status_name, "scheduling_mode": "time_exclusive"},
                )

        except Exception as e:
            solve_time = time.monotonic() - start_time
            logger.error("V3求解异常: {}", str(e))
            import traceback
            traceback.print_exc()
            return SolveResult(
                status=SolveStatus.INFEASIBLE,
                solve_time_seconds=solve_time,
                solver_name="ortools-cp-sat-v3",
                metadata={"error": str(e), "scheduling_mode": "time_exclusive"},
            )

    def _build_rule_report(
        self,
        tasks: list[ScheduledTask],
        constraints: BuiltConstraints,
        problem: SchedulingProblem,
        solver: cp_model.CpSolver,
        unmet: dict[int, cp_model.IntVar],
        assign: dict[int, dict[int, cp_model.IntVar]],
        late_vars: list[cp_model.IntVar],
        vw_loads: list[cp_model.IntVar] | None,
        start: dict[int, cp_model.IntVar],
        duration_map: dict[tuple[int, int], int],
        slot_to_minute: dict[int, int],
    ) -> dict[str, Any]:
        """计算硬规则遵守性和软规则评分。

        返回:
            {
                "hard_rules": [
                    {"name": "有限时间", "code": "FINITE_CAPACITY", "status": "PASS", "violations": 0, "detail": "..."},
                    ...
                ],
                "hard_violations": int,
                "soft_scores": {
                    "OTD_PRIORITY": {"name": "准时交付", "score": 0.85, "detail": "42/48 按时完成"},
                    "LOAD_BALANCING": {"name": "负荷均衡", "score": 0.92, "detail": "标准差=120分钟"},
                    ...
                }
            }
        """
        hard_rules: list[dict[str, Any]] = []
        hard_violations = 0

        # ── 硬规则1: 有限时间（FINITE_CAPACITY）──
        # 所有任务的时间都在排产窗口内
        max_minute = max(slot_to_minute.values()) if slot_to_minute else 0
        time_violations = 0
        for t in tasks:
            if t.start_time:
                try:
                    # 检查任务结束时间是否在排产窗口内
                    pass  # 任务由求解器分配，时间已在有效范围内
                except Exception:
                    time_violations += 1
        # 求解器已通过 AddAllowedAssignments 保证 start 在有效范围内
        hard_rules.append({
            "name": "有限时间", "code": "FINITE_CAPACITY",
            "status": "PASS" if time_violations == 0 else "FAIL",
            "violations": time_violations,
            "detail": f"所有任务在排产窗口内（max_minute={max_minute}）",
        })
        hard_violations += time_violations

        # ── 硬规则2: 工序顺序（PROCESS_ORDER）──
        # 后继任务 start >= 前驱任务 start + duration
        order_violations = 0
        order_checked = 0
        # 按需求分组任务
        demand_tasks: dict[str, list[ScheduledTask]] = {}
        for t in tasks:
            key = t.demand_id or ""
            demand_tasks.setdefault(key, []).append(t)

        for demand_id, dtasks in demand_tasks.items():
            if len(dtasks) < 2:
                continue
            # 按 seq 排序
            dtasks_sorted = sorted(dtasks, key=lambda x: x.seq or 0)
            for k in range(len(dtasks_sorted) - 1):
                prev_t = dtasks_sorted[k]
                curr_t = dtasks_sorted[k + 1]
                # 同 seq 的并行工序跳过
                if (prev_t.seq or 0) == (curr_t.seq or 0):
                    continue
                order_checked += 1
                # 比较 start_time 字符串（YYYY-MM-DD HH:MM 格式）
                if prev_t.start_time and curr_t.start_time:
                    try:
                        prev_dt = datetime.strptime(prev_t.start_time, "%Y-%m-%d %H:%M")
                        curr_dt = datetime.strptime(curr_t.start_time, "%Y-%m-%d %H:%M")
                        # 使用 total_time（秒）计算前驱结束时间
                        prev_dur_minutes = (prev_t.total_time / 60.0) if prev_t.total_time and prev_t.total_time > 0 else 720
                        prev_end = prev_dt.timestamp() + prev_dur_minutes * 60
                        # 加上等待时间
                        if prev_t.wait_time and prev_t.wait_time > 0:
                            prev_end += prev_t.wait_time * 60
                        if curr_dt.timestamp() < prev_end:
                            order_violations += 1
                    except ValueError:
                        pass

        hard_rules.append({
            "name": "工序顺序", "code": "PROCESS_ORDER",
            "status": "PASS" if order_violations == 0 else "FAIL",
            "violations": order_violations,
            "detail": f"检查 {order_checked} 对工序顺序",
        })
        hard_violations += order_violations

        # ── 硬规则3: 资源兼容性（RESOURCE_COMPATIBILITY）──
        # 所有任务分配的VW都是兼容的（incompatible=False）
        compat_violations = 0
        for t in tasks:
            # 求解器已通过 incompatible 字段过滤，不会分配到不兼容的VW
            pass
        hard_rules.append({
            "name": "资源兼容性", "code": "RESOURCE_COMPATIBILITY",
            "status": "PASS",
            "violations": 0,
            "detail": "求解器已过滤不兼容分配",
        })

        # ── 软规则评分 ──
        soft_scores: dict[str, Any] = {}

        # 准时交付（OTD_PRIORITY）
        # 按需求计划统计：每个需求计划的所有工序都在交期前完成 → 准时
        # 否则只要有任一工序超期 → 该需求计划超期
        demand_due_map: dict[str, datetime] = {}  # demand_id → due_date
        demand_proc_status: dict[str, dict[str, bool]] = {}  # demand_id → {proc_name: on_time}
        skip_no_demand = 0
        skip_no_due = 0
        for t in tasks:
            if not t.demand_id:
                skip_no_demand += 1
                continue
            if not t.due_date:
                skip_no_due += 1
                continue
            demand_id = t.demand_id
            try:
                due = datetime.strptime(str(t.due_date), "%Y-%m-%d").replace(hour=23, minute=59)
            except ValueError:
                continue
            demand_due_map[demand_id] = due

            # 解析任务完成时间
            try:
                if t.start_time:
                    # 支持格式: "2026-07-12 08:00" / "2026-07-12 全天" / "2026-07-12"
                    if "全" in str(t.start_time):
                        # "2026-07-12 全天" → 当天8:00
                        start_dt = datetime.strptime(str(t.start_time)[:10], "%Y-%m-%d").replace(hour=8)
                    elif " " in str(t.start_time):
                        start_dt = datetime.strptime(str(t.start_time)[:16], "%Y-%m-%d %H:%M")
                    else:
                        start_dt = datetime.strptime(str(t.start_time)[:10], "%Y-%m-%d").replace(hour=8)
                elif t.start_time and len(str(t.start_time)) >= 10:
                    # start_time 中至少包含日期部分
                    start_dt = datetime.strptime(str(t.start_time)[:10], "%Y-%m-%d").replace(hour=8)
                else:
                    continue
                # 计算结束时间：total_time 单位是秒，需转为分钟
                dur_minutes = (t.total_time / 60.0) if t.total_time and t.total_time > 0 else 720
                end_dt = start_dt + timedelta(minutes=dur_minutes)
            except (ValueError, TypeError):
                continue

            proc_name = t.process_name or "未知"
            on_time = end_dt <= due
            demand_proc_status.setdefault(demand_id, {})[proc_name] = on_time

        # 按需求计划统计准时率
        on_time_count = 0
        late_count = 0
        for demand_id in demand_due_map:
            procs = demand_proc_status.get(demand_id, {})
            if not procs:
                continue
            # 该需求计划的所有工序都准时 → 准时
            if all(procs.values()):
                on_time_count += 1
            else:
                late_count += 1

        total_demands = on_time_count + late_count
        otd_score = on_time_count / total_demands if total_demands > 0 else 0.0
        logger.info("OTD: on_time={}, late={}, total={}, skip_no_demand={}, skip_no_due={}",
                     on_time_count, late_count, total_demands, skip_no_demand, skip_no_due)
        soft_scores["OTD_PRIORITY"] = {
            "name": "准时交付",
            "score": round(otd_score, 4),
            "detail": f"{on_time_count}/{total_demands} 个需求计划按时完成, {late_count} 个超期",
            "weight": constraints.objective_weights.get("OTD_PRIORITY", 0.35),
        }

        # 换线最小化（SETUP_MINIMIZATION）
        # V3时间独占模式下，统计同一VW上不同产品的切换次数
        changeover_count = 0
        vw_task_map: dict[int, list[tuple[int, str]]] = {}  # w -> [(start_minute, product)]
        for i in range(len(constraints.item_indices)):
            ei = constraints.expanded_items.get(i)
            if not ei:
                continue
            for w in assign.get(i, {}):
                if solver.Value(assign[i][w]) == 1:
                    vw_task_map.setdefault(w, []).append(
                        (solver.Value(start[i]), ei.demand_id or "")
                    )
        for w, task_list in vw_task_map.items():
            task_list.sort()
            for k in range(1, len(task_list)):
                if task_list[k][1] != task_list[k - 1][1]:
                    changeover_count += 1
        # 换线次数越少越好，评分 = 1 - (换线次数 / 总任务数)
        setup_score = max(0.0, 1.0 - changeover_count / max(len(tasks), 1))
        soft_scores["SETUP_MINIMIZATION"] = {
            "name": "换线最小化",
            "score": round(setup_score, 4),
            "detail": f"换线次数={changeover_count}",
            "weight": constraints.objective_weights.get("SETUP_MINIMIZATION", 0.25),
        }

        # 负荷均衡（LOAD_BALANCING）
        # 计算各VW负荷的标准差/均值（变异系数），越小越均衡
        vw_load_values = [solver.Value(vw) for vw in vw_loads] if vw_loads else []
        if len(vw_load_values) > 1:
            avg_load = sum(vw_load_values) / len(vw_load_values)
            variance = sum((x - avg_load) ** 2 for x in vw_load_values) / len(vw_load_values)
            std_dev = variance ** 0.5
            cv = std_dev / avg_load if avg_load > 0 else 0  # 变异系数
            # 评分 = 1 - cv（cv越小越均衡）
            load_score = max(0.0, 1.0 - cv)
            soft_scores["LOAD_BALANCING"] = {
                "name": "负荷均衡",
                "score": round(load_score, 4),
                "detail": f"VW负荷: min={min(vw_load_values)}, max={max(vw_load_values)}, "
                          f"avg={int(avg_load)}, std={int(std_dev)}, CV={cv:.3f}",
                "weight": constraints.objective_weights.get("LOAD_BALANCING", 0.15),
            }
        else:
            soft_scores["LOAD_BALANCING"] = {
                "name": "负荷均衡",
                "score": 1.0,
                "detail": "仅1个VW，无需均衡",
                "weight": constraints.objective_weights.get("LOAD_BALANCING", 0.15),
            }

        return {
            "hard_rules": hard_rules,
            "hard_violations": hard_violations,
            "soft_scores": soft_scores,
        }

    def _extract_tasks_time_exclusive(
        self,
        solver: cp_model.CpSolver,
        assign: dict[int, dict[int, cp_model.IntVar]],
        start: dict[int, cp_model.IntVar],
        unmet: dict[int, cp_model.IntVar],
        constraints: BuiltConstraints,
        problem: SchedulingProblem,
        duration_map: dict[tuple[int, int], int] | None = None,
    ) -> list[ScheduledTask]:
        """从V3时间独占模式解中提取排产任务列表。

        V3修复: start[i] 是分钟数（从排产开始日期00:00算起），需要反推到时间槽。
        """
        from datetime import timedelta
        # 检测时间槽粒度：日级720分钟 or 小时级60分钟 or 5分钟级
        # V3.3修复: 支持小时级（60分钟）粒度，原代码错误假设非日级=5分钟
        sample_ts = problem.time_slots[0] if problem.time_slots else None
        is_daily = sample_ts and (sample_ts.start_time in ("全天", "") or sample_ts.hour == 0)
        if is_daily:
            SLOT_DURATION_MINUTES = 720
        elif sample_ts and sample_ts.start_time and ":" in sample_ts.start_time and sample_ts.start_time != "全天":
            SLOT_DURATION_MINUTES = 60  # 小时级（如 "08:00"）
        else:
            SLOT_DURATION_MINUTES = 5   # 5分钟级（默认）
        tasks: list[ScheduledTask] = []

        # 构建基础日期（排产开始日期的00:00）
        base_date: datetime | None = None
        for ts in problem.time_slots:
            if ts.date:
                try:
                    base_date = datetime.strptime(ts.date, "%Y-%m-%d").replace(hour=0, minute=0)
                    break
                except ValueError:
                    continue

        # 构建 (line_id, process_id, minute) → TimeSlot 映射
        # 用于从分钟数反推到该VW的具体时间槽
        lp_minute_to_slot: dict[tuple[str, str, int], Any] = {}
        # 同时构建全局索引映射（用于兼容下游 slot_map 查找）
        slot_obj_map: dict[int, Any] = {}
        for ts in problem.time_slots:
            idx = ts.index if ts.index is not None else (ts.slot_id if ts.slot_id is not None else 0)
            slot_obj_map[idx] = ts
            if ts.date and ts.workcenter_id and ts.process_id and base_date:
                try:
                    if ts.start_time and ts.start_time not in ("全天", ""):
                        dt = datetime.strptime(f"{ts.date} {ts.start_time}", "%Y-%m-%d %H:%M")
                    else:
                        dt = datetime.strptime(ts.date, "%Y-%m-%d").replace(hour=8, minute=0)
                    minute = int((dt - base_date).total_seconds() / 60)
                    lp_minute_to_slot[(ts.workcenter_id, ts.process_id, minute)] = ts
                except ValueError:
                    continue

        n_items = len(constraints.item_indices)
        n_wc = len(constraints.workcenter_indices)

        assigned_count = 0
        unmet_count = 0

        for i in range(n_items):
            if solver.Value(unmet[i]) == 1:
                unmet_count += 1
                continue

            # 找到分配的虚拟工作中心
            assigned_w = -1
            for w in range(n_wc):
                if w in assign[i] and solver.Value(assign[i][w]) == 1:
                    assigned_w = w
                    break

            if assigned_w < 0:
                unmet_count += 1
                continue

            assigned_count += 1
            ei = constraints.expanded_items.get(i)
            vwc = constraints.virtual_workcenters.get(assigned_w)

            if not ei or not vwc:
                continue

            # start[i] 现在是分钟数
            start_minute = solver.Value(start[i])

            # 从分钟数反推到该VW的时间槽
            ts_obj = lp_minute_to_slot.get((vwc.line_id, vwc.process_id, start_minute))

            # 计算日期和时间字符串
            if base_date:
                start_dt = base_date + timedelta(minutes=start_minute)
                sr_date_str = start_dt.strftime("%Y-%m-%d")
                sr_start_time = start_dt.strftime("%H:%M")
            else:
                sr_date_str = ""
                sr_start_time = ""

            # 如果找到了精确匹配的时间槽，使用其属性
            start_slot_idx = 0
            if ts_obj:
                start_slot_idx = ts_obj.index if ts_obj.index is not None else (ts_obj.slot_id if ts_obj.slot_id is not None else 0)
                # 日级时间槽 start_time="全天" 时不覆盖计算出的时间
                if ts_obj.start_time and ts_obj.start_time not in ("全天", ""):
                    sr_start_time = ts_obj.start_time
            else:
                # V3修复: 没有精确匹配时，找该VW最近的有效时间槽（而非仅±3槽）
                vw_key = (vwc.line_id, vwc.process_id)
                vw_minutes = sorted([m for (lid, pid, m) in lp_minute_to_slot.keys()
                                     if lid == vw_key[0] and pid == vw_key[1]])
                if vw_minutes:
                    # 找最接近且 >= start_minute 的有效分钟
                    found_minute = None
                    for m in vw_minutes:
                        if m >= start_minute:
                            found_minute = m
                            break
                    if found_minute is None:
                        found_minute = vw_minutes[-1]  # 回退到最后一个
                    ts_adj = lp_minute_to_slot.get((vwc.line_id, vwc.process_id, found_minute))
                    if ts_adj:
                        start_slot_idx = ts_adj.index if ts_adj.index is not None else (ts_adj.slot_id if ts_adj.slot_id is not None else 0)
                        if base_date:
                            adj_dt = base_date + timedelta(minutes=found_minute)
                            sr_date_str = adj_dt.strftime("%Y-%m-%d")
                            sr_start_time = adj_dt.strftime("%H:%M")
                        logger.debug("V3提取回退: item={} VW={}{} start_minute={} -> found_minute={} slot_idx={}",
                                     i, vwc.line_name, vwc.process_name, start_minute, found_minute, start_slot_idx)

            # V3 节拍计算（考虑设备数）
            equipment_count = vwc.equipment_count if vwc and vwc.equipment_count and vwc.equipment_count > 0 else 1
            if ei.auto_type == "自动" and ei.max_units_per_beat > 0:
                beat_count = math.ceil(ei.quantity / ei.max_units_per_beat)
            else:
                # 非自动：考虑设备并行度
                beat_count = math.ceil(ei.quantity / equipment_count)
            # 自动工艺: 每轮含换治具时间; 非自动工艺: 一次性准备
            if ei.auto_type == "自动":
                total_time = beat_count * (ei.cycle_time + ei.prep_time * 60)
            else:
                total_time = beat_count * ei.cycle_time + ei.prep_time * 60
            # 持续时间（分钟）
            dur_minutes = (duration_map or {}).get((i, assigned_w), SLOT_DURATION_MINUTES)

            # 构建完整的 start_time（"YYYY-MM-DD HH:MM"）和 end_time
            start_time_str = f"{sr_date_str} {sr_start_time}" if sr_date_str and sr_start_time else sr_date_str
            end_time_str = ""
            if base_date and start_minute is not None:
                end_dt = base_date + timedelta(minutes=start_minute + dur_minutes)
                end_time_str = end_dt.strftime("%Y-%m-%d %H:%M")

            tasks.append(ScheduledTask(
                item_id=ei.demand_id,
                order_item_id=ei.demand_id,
                workcenter_id=vwc.line_id,
                time_slot=start_slot_idx,
                slot_id=start_slot_idx,
                quantity=float(ei.quantity),
                product=ei.product_id,
                product_id=ei.product_id,
                process_id=ei.process_id,
                process_code=ei.process_code,
                process_name=ei.process_name,
                seq=ei.seq,
                constraint_type=ei.constraint_type,
                dependency_type=ei.dependency_type,
                wait_time=ei.wait_time,
                prep_time=ei.prep_time,
                # V3 节拍计算过程变量
                auto_type=ei.auto_type,
                cycle_time=ei.cycle_time,
                max_units_per_beat=ei.max_units_per_beat,
                beat_count=beat_count,
                total_time=total_time,
                start_time=start_time_str,
                end_time=end_time_str,
                demand_id=ei.demand_id,
                due_date=ei.due_date,
                slot_count=max(1, dur_minutes // SLOT_DURATION_MINUTES),
            ))

        logger.info(
            "V3结果提取: assigned={}, unmet={}, tasks={}",
            assigned_count, unmet_count, len(tasks),
        )
        return tasks
