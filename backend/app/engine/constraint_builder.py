"""约束构建器，将业务规则转化为 CP-SAT 可用的约束数据结构。

V2 工序级排产：每个(需求, 工序)对作为独立排产项，每个(产线, 工序)对作为虚拟工作中心。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from app.engine.models import (
    ChangeoverEntry,
    ChangeoverMatrix,
    ChangeoverRule,
    DemandPlan,
    HardRule,
    LineProcessConfig,
    ProcessDependency,
    ProductionLine,
    ProductProcess,
    ProcessInfo,
    SchedulingProblem,
    SoftRule,
    TimeSlot,
)

# 旧名别名，保持向后兼容
OrderItem = DemandPlan
WorkCenter = ProductionLine


@dataclass
class ExpandedItem:
    """展开后的排产项：(需求, 工序) 对。"""
    key: str              # f"{demand_id}__{process_id}"
    demand_id: str        # 原始需求 ID
    process_id: str       # 工序 ID
    seq: int              # 工序顺序
    product_id: str       # 产品 ID
    quantity: float       # 需求数量（每道工序都需满足全部数量）
    priority: str         # 优先级
    due_date: str         # 交期
    process_code: str = ""
    process_name: str = ""
    constraint_type: str = ""
    dependency_type: str = "FS"  # 依赖类型：FS/SS/FF/SF
    auto_type: str = "非自动"  # 工艺类型：自动/非自动
    cycle_time: float = 0.0     # 节拍时间(秒) — 从 ProductProcess 获取
    max_units_per_beat: int = 1  # 单节拍最大数量 — 从 ProductProcess 获取
    wait_time: float = 0.0  # 等待时间(分钟)
    prep_time: float = 0.0  # 准备时间(分钟)
    # V3 时间独占模式
    beat_count: int = 0         # 节拍数
    total_time_seconds: float = 0.0  # 总加工时间(秒)
    slots_needed: int = 1       # 需要占用的连续5分钟时间槽数


@dataclass
class VirtualWorkcenter:
    """虚拟工作中心：(产线, 工序) 对。"""
    key: str              # f"{line_id}__{process_id}"
    line_id: str          # 真实产线 ID
    process_id: str       # 工序 ID
    line_name: str = ""
    process_name: str = ""
    lpc_id: str = ""      # 产线工艺配置 ID（用于换线矩阵查找）
    lpc_code: str = ""    # 产线工艺配置编号
    auto_type: str = "非自动"
    is_bottleneck: bool = False
    equipment_count: int = 1  # V3: 设备数（用于计算并行度和Cumulative约束容量）
    worker_count: int = 0     # 人员数


@dataclass
class BuiltConstraints:
    """构建完成的约束数据，供求解器直接消费。"""

    # 索引映射
    item_indices: dict[str, int]           # expanded_item_key → 索引
    workcenter_indices: dict[str, int]     # virtual_wc_key → 索引
    time_indices: list[int]                # 时间槽索引列表

    # 产能约束: capacity[w][t]
    capacity: dict[int, dict[int, float]]

    # 物料齐套: material_not_ready[i][t] = True 表示不可排
    material_not_ready: dict[int, dict[int, bool]]

    # 资源兼容: incompatible[i][w] = True 表示不可排
    incompatible: dict[int, dict[int, bool]]

    # 冻结窗口: fixed[i][t][w] = quantity
    fixed: dict[int, dict[int, dict[int, float]]]

    # 换线矩阵: changeover_time[(from_product, to_product)]
    changeover_time: dict[tuple[str, str], float] = field(default_factory=dict)

    # V3 LPC 换线矩阵: changeover_time_lpc[(from_lpc_id, to_lpc_id)]
    changeover_time_lpc: dict[tuple[str, str], float] = field(default_factory=dict)

    # 优先级权重
    priority_weights: dict[int, float] = field(default_factory=dict)

    # 交期（时间槽索引）
    due_dates: dict[int, int] = field(default_factory=dict)

    # 订单需求数量
    demands: dict[int, float] = field(default_factory=dict)

    # 产品编码
    products: dict[int, str] = field(default_factory=dict)

    # Drum 产线索引集合
    drum_workcenter_indices: set[int] = field(default_factory=set)

    # 目标权重
    objective_weights: dict[str, float] = field(default_factory=dict)

    # ── V2 工序级排产新增字段 ──

    # 展开项信息: expanded_index → ExpandedItem
    expanded_items: dict[int, ExpandedItem] = field(default_factory=dict)

    # 虚拟工作中心信息: virtual_wc_index → VirtualWorkcenter
    virtual_workcenters: dict[int, VirtualWorkcenter] = field(default_factory=dict)

    # 工序顺序组: demand_id → [(expanded_index, seq), ...] 按 seq 排序
    process_order_groups: dict[str, list[tuple[int, int]]] = field(default_factory=dict)

    # DAG 前驱依赖: expanded_index → [predecessor_expanded_index, ...]
    # 替代线性 process_order_groups，支持并行工序
    process_predecessors: dict[int, list[int]] = field(default_factory=dict)

    # DAG 依赖详情: expanded_index → [(pred_expanded_index, dependency_type, delay_slots, delay_minutes), ...]
    # dependency_type: FS/SS/FF/SF
    # delay_slots: 延迟的时间槽数（仅用于GA等基于槽位的求解器）
    # delay_minutes: 延迟的自然时间分钟数（用于ortools基于时间差的约束）
    process_dependency_info: dict[int, list[tuple[int, str, int, float]]] = field(default_factory=dict)

    # 原始需求映射: expanded_index → demand_id
    original_demand_map: dict[int, str] = field(default_factory=dict)

    # V3.6: 各展开项的已完成数量（用于工序顺序约束考虑在制品流转）
    item_seq_completed: dict[int, int] = field(default_factory=dict)

    # 时间槽索引 → 时间键 "YYYY-MM-DD_HH"，用于跨产线工序顺序约束对齐
    slot_to_time_key: dict[int, str] = field(default_factory=dict)

    # 冻结窗口内的时间槽索引集合（前 N 天锁定，不允许新任务分配）
    frozen_time_indices: set[int] = field(default_factory=set)

    # V3.7: 周末约束 - 不能在周末排产的 item 索引集合
    # 根据优先级决定：
    #   - 紧急：周六周日都可排（不在此集合）
    #   - 高：周日不可排（如果周日在排产窗口内，需禁止）
    #   - 中/低/普通：周六周日都不可排
    weekend_blocked_items: set[int] = field(default_factory=set)

    # V3.7: 周日约束 - 仅周日不可排产的 item 索引集合（高优先级）
    sunday_blocked_items: set[int] = field(default_factory=set)

    # V3.7: 周末时间槽索引集合（用于约束应用）
    weekend_time_indices: set[int] = field(default_factory=set)
    sunday_time_indices: set[int] = field(default_factory=set)


class ConstraintBuilder:
    """约束构建器，从 SchedulingProblem 提取约束数据。

    V2 工序级排产：
    - 将每个需求展开为多个(需求, 工序)排产项
    - 将每个(产线, 工序)组合作为虚拟工作中心
    - 添加工序顺序约束
    """

    def build(self, problem: SchedulingProblem) -> BuiltConstraints:
        """构建约束数据。"""
        items = problem.demand_plans or problem.items or problem.order_items or problem.orders or []
        workcenters = problem.production_lines or problem.workcenters
        time_slots = problem.time_slots
        product_processes = problem.product_processes
        line_process_configs = problem.line_process_configs
        process_info_list = problem.process_info

        # ── 1. 构建虚拟工作中心 ──
        virtual_wcs: list[VirtualWorkcenter] = []
        # 构建 process_id → ProcessInfo 映射
        process_info_map: dict[str, ProcessInfo] = {pi.id: pi for pi in process_info_list}
        # 构建 line_id → ProductionLine 映射
        line_map: dict[str, ProductionLine] = {wc.id: wc for wc in workcenters}

        for lpc in line_process_configs:
            line = line_map.get(lpc.line_id)
            pi = process_info_map.get(lpc.process_id)
            vwc = VirtualWorkcenter(
                key=f"{lpc.line_id}__{lpc.process_id}",
                line_id=lpc.line_id,
                process_id=lpc.process_id,
                line_name=line.line_name if line else "",
                process_name=pi.proc_name if pi else "",
                lpc_id=lpc.id,
                lpc_code=lpc.lpc_code or "",
                auto_type=lpc.auto_type,
                is_bottleneck=lpc.is_bottleneck,
                equipment_count=lpc.equipment_count or 1,
                worker_count=lpc.worker_count or 0,
            )
            virtual_wcs.append(vwc)

        workcenter_indices = {vwc.key: i for i, vwc in enumerate(virtual_wcs)}
        logger.info("虚拟工作中心数: {}", len(virtual_wcs))

        # ── 2. 展开排产项 ──
        # 每个(需求, 工序)对作为一个排产项
        # 产品工艺路线: product_id → [ProductProcess] 按 seq 排序
        pp_by_product: dict[str, list[ProductProcess]] = {}
        for pp in product_processes:
            pp_by_product.setdefault(pp.product_id, []).append(pp)
        for pid in pp_by_product:
            pp_by_product[pid].sort(key=lambda p: p.seq)

        expanded_items_list: list[ExpandedItem] = []
        item_seq_completed_map: dict[int, int] = {}  # V3.6: 展开项 → 已完成数量
        process_order_groups: dict[str, list[tuple[int, int]]] = {}
        # DAG 前驱依赖: expanded_index → [predecessor_expanded_index, ...]
        process_predecessors: dict[int, list[int]] = {}
        # DAG 依赖详情: expanded_index → [(pred_expanded_index, dependency_type, delay_slots), ...]
        process_dependency_info: dict[int, list[tuple[int, str, int]]] = {}

        # 构建显式依赖索引: (product_id, to_process) → [from_process, ...]
        explicit_deps: dict[tuple[str, str], list[str]] = {}
        for dep in problem.process_dependencies:
            explicit_deps.setdefault((dep.product_id, dep.to_process), []).append(dep.from_process)

        # 时间槽数量（用于计算延迟槽位数）
        n_time_slots = len(time_slots)
        # 根据时间槽粒度推断每个时间槽的时长
        # 如果同一 (date, workcenter_id, process_id) 只有一个时间槽，则为日级（720分钟）
        # 否则为小时级（60分钟）
        _slot_keys = set()
        for ts in time_slots[:200]:  # 采样前200个判断（支持更细粒度时间槽）
            _slot_keys.add((ts.date, ts.workcenter_id, ts.process_id))
        if len(time_slots) > 0 and len(_slot_keys) == len(time_slots[:200]):
            SLOT_DURATION_MINUTES = 720  # 日级时间槽，12小时/天
        else:
            SLOT_DURATION_MINUTES = 60   # 小时级时间槽

        # 计算延迟时间槽数和延迟分钟数的辅助函数
        def _calc_delay_slots(
            dep_type: str,
            pred_pp: ProductProcess | None,
            succ_pp: ProductProcess | None,
        ) -> tuple[int, float]:
            """根据依赖类型计算延迟时间槽数和延迟分钟数。

            FS: delay = 前工序wait_time + 后工序prep_time
            SS: delay = 后工序prep_time（后工序需先准备才能开始）
            FF: delay = 0（自动对齐结束时间）
            SF: delay = 0（自动对齐）

            注意: wait_time/prep_time/wait_includes_offhours 从 ProductProcess 获取。

            Returns: (delay_slots, delay_minutes)

            注意: prep_time 已计入生产时间内（自动工艺每轮换治具，非自动工艺一次性准备），
            此处延迟只算 wait_time（工序间等待，如冷却/固化）。
            """
            if dep_type == "FS":
                wait_time = pred_pp.wait_time if pred_pp else 0
                if wait_time <= 0:
                    # FS 约束 wait_time=0：后继可立即跟随前驱（小时级时间槽下自然体现）
                    # 在 time_exclusive 模式下，前驱在 t 小时生产，后继在 t+1 小时即可开始
                    return (1, 60)
                delay_minutes = wait_time
                if pred_pp and not pred_pp.wait_includes_offhours:
                    # 只算工作时间（8:00-20:00 = 12小时/天）
                    work_hours_per_day = 12
                    work_minutes_per_day = work_hours_per_day * SLOT_DURATION_MINUTES
                    days = int(wait_time // work_minutes_per_day)
                    remaining = wait_time % work_minutes_per_day
                    slots = days * work_hours_per_day + int(remaining + SLOT_DURATION_MINUTES - 1) // SLOT_DURATION_MINUTES
                else:
                    # 自然时间
                    slots = int(wait_time + SLOT_DURATION_MINUTES - 1) // SLOT_DURATION_MINUTES
                return (max(slots, 1), delay_minutes)
            elif dep_type == "SS":
                # SS: 后工序可在前工序开始后开始，prep_time已在生产时间内
                return (0, 0)
            elif dep_type == "FF":
                return (0, 0)
            elif dep_type == "SF":
                return (0, 0)
            return (1, 60)  # 默认 FS

        for item in items:
            pp_list = pp_by_product.get(item.product_id, [])
            if not pp_list:
                # 没有工艺路线的需求，作为单工序项保留
                ei = ExpandedItem(
                    key=item.id,
                    demand_id=item.id,
                    process_id="",
                    seq=0,
                    product_id=item.product_id,
                    quantity=item.quantity or item.demand_qty if hasattr(item, 'demand_qty') else item.quantity,
                    priority=item.priority,
                    due_date=item.due_date if hasattr(item, 'due_date') else "",
                )
                expanded_items_list.append(ei)
                continue

            group: list[tuple[int, int]] = []
            # 记录 (process_id → expanded_index) 映射，用于构建前驱依赖
            proc_to_idx: dict[str, int] = {}
            # 记录 (seq → [expanded_index]) 映射，用于从 seq 推导并行关系
            seq_to_indices: dict[int, list[int]] = {}

            for pp in pp_list:
                pi = process_info_map.get(pp.process_id)
                # V3.6: 各工序独立扣减已完成数量
                raw_qty = int(item.quantity or (item.demand_qty if hasattr(item, 'demand_qty') else item.quantity) or 0)
                seq_completed = 0
                if hasattr(item, 'seq_completed_map') and item.seq_completed_map:
                    seq_completed = int(item.seq_completed_map.get(pp.seq, 0) or 0)
                seq_remaining = max(raw_qty - seq_completed, 0)
                # 该工序已全部完成，跳过（不展开）
                if seq_remaining <= 0:
                    continue
                ei = ExpandedItem(
                    key=f"{item.id}__{pp.process_id}",
                    demand_id=item.id,
                    process_id=pp.process_id,
                    seq=pp.seq,
                    product_id=item.product_id,
                    quantity=seq_remaining,
                    priority=item.priority,
                    due_date=item.due_date if hasattr(item, 'due_date') else "",
                    process_code=pi.proc_code if pi else "",
                    process_name=pi.proc_name if pi else "",
                    constraint_type=pi.constraint_type if pi else "",
                    dependency_type=pp.dependency_type or "FS",
                    auto_type=pp.auto_type or "非自动",
                    cycle_time=pp.cycle_time if pp.cycle_time else 0.0,
                    max_units_per_beat=pp.max_units_per_beat if pp.max_units_per_beat else 1,
                    wait_time=pp.wait_time if pp.wait_time else 0,
                    prep_time=pp.prep_time if pp.prep_time else 0,
                )
                # V3: 计算节拍数和占用时间槽数
                qty = int(ei.quantity)
                if ei.auto_type == "自动" and ei.max_units_per_beat > 0:
                    ei.beat_count = math.ceil(qty / ei.max_units_per_beat)
                else:
                    ei.beat_count = qty
                # 自动工艺: 每轮 = cycle_time + prep_time(换治具, 分钟转秒)
                # 非自动工艺: 总时间 = beat_count * cycle_time + prep_time * 60 (一次性准备)
                if ei.auto_type == "自动":
                    ei.total_time_seconds = ei.beat_count * (ei.cycle_time + ei.prep_time * 60)
                else:
                    ei.total_time_seconds = ei.beat_count * ei.cycle_time + ei.prep_time * 60
                total_minutes = ei.total_time_seconds / 60.0
                SLOT_DURATION = 5  # 5分钟/槽
                ei.slots_needed = max(1, math.ceil(total_minutes / SLOT_DURATION))
                expanded_idx = len(expanded_items_list)
                expanded_items_list.append(ei)
                group.append((expanded_idx, pp.seq))
                proc_to_idx[pp.process_id] = expanded_idx
                # V3.6: 记录该展开项的已完成数量（用于工序顺序约束）
                item_seq_completed_map[expanded_idx] = seq_completed
                seq_to_indices.setdefault(pp.seq, []).append(expanded_idx)

            if group:
                process_order_groups[item.id] = group

            # 构建 DAG 前驱依赖
            # 优先使用显式依赖（ProcessDependency），否则从 seq 自动推导
            has_explicit = any(
                (item.product_id, pp.process_id) in explicit_deps
                for pp in pp_list
            )

            if has_explicit:
                # 使用显式依赖
                # 构建 process_id → ProductProcess 映射
                pp_by_pid = {pp.process_id: pp for pp in pp_list}
                for pp in pp_list:
                    to_idx = proc_to_idx.get(pp.process_id)
                    if to_idx is None:
                        continue
                    from_procs = explicit_deps.get((item.product_id, pp.process_id), [])
                    preds = [proc_to_idx[fp] for fp in from_procs if fp in proc_to_idx]
                    if preds:
                        process_predecessors[to_idx] = preds
                        # 计算依赖详情
                        dep_type = pp.dependency_type or "FS"
                        dep_details = []
                        for pred_idx in preds:
                            pred_ei = expanded_items_list[pred_idx]
                            pred_pp = pp_by_pid.get(pred_ei.process_id)
                            delay_slots, delay_minutes = _calc_delay_slots(dep_type, pred_pp, pp)
                            dep_details.append((pred_idx, dep_type, delay_slots, delay_minutes))
                        process_dependency_info[to_idx] = dep_details
            else:
                # 从 seq 自动推导：seq=N 的前驱是 seq=N-1 的所有工序
                sorted_seqs = sorted(seq_to_indices.keys())
                # 构建 process_id → ProductProcess 映射
                pp_by_pid = {pp.process_id: pp for pp in pp_list}
                for seq_idx in range(1, len(sorted_seqs)):
                    prev_seq = sorted_seqs[seq_idx - 1]
                    curr_seq = sorted_seqs[seq_idx]
                    for curr_ei_idx in seq_to_indices[curr_seq]:
                        # 前驱是前一个 seq 的所有工序
                        prev_indices = seq_to_indices[prev_seq]
                        process_predecessors[curr_ei_idx] = prev_indices
                        # 计算依赖详情：同 seq 并行用 SS，不同 seq 串行用 FS
                        curr_pp = next((p for p in pp_list if proc_to_idx.get(p.process_id) == curr_ei_idx), None)
                        dep_type = curr_pp.dependency_type if curr_pp and curr_pp.dependency_type else "FS"
                        dep_details = []
                        for pred_idx in prev_indices:
                            pred_ei = expanded_items_list[pred_idx]
                            pred_pp = pp_by_pid.get(pred_ei.process_id)
                            delay_slots, delay_minutes = _calc_delay_slots(dep_type, pred_pp, curr_pp)
                            dep_details.append((pred_idx, dep_type, delay_slots, delay_minutes))
                        process_dependency_info[curr_ei_idx] = dep_details

        item_indices = {ei.key: i for i, ei in enumerate(expanded_items_list)}
        # 统计并行工序信息
        parallel_count = sum(1 for v in process_predecessors.values() if len(v) > 1)
        # 统计依赖类型分布
        dep_type_counts: dict[str, int] = {}
        total_delay_slots = 0
        for deps in process_dependency_info.values():
            for _, dep_type, delay_slots, delay_minutes in deps:
                dep_type_counts[dep_type] = dep_type_counts.get(dep_type, 0) + 1
                total_delay_slots += delay_slots
        logger.info(
            "展开排产项数: {} (原始需求数: {}), DAG前驱依赖: {} 条, 并行工序: {} 处, "
            "依赖类型: {}, 总延迟槽位: {}",
            len(expanded_items_list), len(items), len(process_predecessors), parallel_count,
            dep_type_counts, total_delay_slots,
        )

        # ── 3. 时间槽索引 ──
        time_indices = []
        slot_to_time_key: dict[int, str] = {}
        for ts in time_slots:
            idx = ts.index or ts.slot_id or 0
            time_indices.append(idx)
            # 构建时间键，用于跨产线工序顺序约束对齐
            slot_to_time_key[idx] = f"{ts.date}_{ts.hour:02d}"

        # ── 4. 产能: capacity[vwc_index][time_index] ──
        # 优先从资源日历的 TimeSlot 读取（含 process_id）
        # 如果 TimeSlot 没有 process_id，则按产线分配给该产线的所有虚拟工作中心
        capacity: dict[int, dict[int, float]] = {}

        # 预构建虚拟工作中心映射（后续多处使用）
        virtual_wcs_map = {workcenter_indices[vwc.key]: vwc for vwc in virtual_wcs}

        # 统计有 process_id 的时段数
        slots_with_process = sum(1 for ts in time_slots if ts.process_id)

        if slots_with_process > 0:
            # 有 process_id 的时段：直接映射到虚拟工作中心
            vwc_key_misses = 0
            for ts in time_slots:
                t = ts.index or ts.slot_id or 0
                if ts.process_id:
                    vwc_key = f"{ts.workcenter_id}__{ts.process_id}"
                    if vwc_key not in workcenter_indices:
                        vwc_key_misses += 1
                        continue
                    w = workcenter_indices[vwc_key]
                    cap = ts.available_capacity
                    if cap > 0:
                        capacity.setdefault(w, {})[t] = cap
            if vwc_key_misses > 0:
                logger.warning("VWC key未匹配: {}/{} 个时段", vwc_key_misses, slots_with_process)
        else:
            # 没有 process_id 的时段：按产线均分给该产线的所有虚拟工作中心
            # V3时间独占模式：产能=1.0（每个时间槽只能被一个任务占用）
            line_vwcs: dict[str, list[int]] = {}
            for vwc in virtual_wcs:
                line_vwcs.setdefault(vwc.line_id, []).append(
                    workcenter_indices[vwc.key]
                )

            for ts in time_slots:
                t = ts.index or ts.slot_id or 0
                line_id = ts.workcenter_id
                if line_id not in line_vwcs:
                    continue
                cap = ts.available_capacity
                if cap <= 0:
                    continue

                # V3: 均分给该产线的各虚拟工作中心
                n = len(line_vwcs[line_id])
                if n > 0:
                    for w in line_vwcs[line_id]:
                        capacity.setdefault(w, {})[t] = cap / n

        # 如果产能仍为空，V3时间独占模式默认产能=1.0
        if not capacity:
            for vwc in virtual_wcs:
                w = workcenter_indices[vwc.key]
                for t in time_indices:
                    capacity.setdefault(w, {})[t] = 1.0

        # ── 5. 资源兼容: incompatible[expanded_i][vwc_w] ──
        # 展开项只能分配到匹配其工序+工艺类型的虚拟工作中心
        incompatible: dict[int, dict[int, bool]] = {}
        for ei in expanded_items_list:
            i = item_indices[ei.key]
            for vwc in virtual_wcs:
                w = workcenter_indices[vwc.key]
                # 工序必须匹配
                if ei.process_id and vwc.process_id != ei.process_id:
                    incompatible.setdefault(i, {})[w] = True
                # 工艺类型必须匹配（自动/非自动）
                elif ei.auto_type and vwc.auto_type and ei.auto_type != vwc.auto_type:
                    incompatible.setdefault(i, {})[w] = True
                # 如果展开项没有工序（无工艺路线的需求），允许所有虚拟工作中心

        # ── 6. 物料齐套 ──
        material_not_ready: dict[int, dict[int, bool]] = {}

        # ── 7. 冻结窗口 ──
        fixed: dict[int, dict[int, dict[int, float]]] = {}
        # 冻结窗口内的时间槽索引集合：前 freeze_horizon 天锁定，不允许新任务
        frozen_time_indices: set[int] = set()
        freeze_horizon = problem.freeze_horizon or 0
        if freeze_horizon > 0 and time_slots:
            dates = [ts.date for ts in time_slots if ts.date]
            if dates:
                from datetime import datetime, timedelta
                start_date = min(dates)
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
                freeze_end_dt = start_dt + timedelta(days=freeze_horizon)
                freeze_end_date = freeze_end_dt.strftime("%Y-%m-%d")
                for ts in time_slots:
                    if ts.date and ts.date < freeze_end_date:
                        idx = ts.index or ts.slot_id or 0
                        frozen_time_indices.add(idx)
                if frozen_time_indices:
                    logger.info(
                        "冻结窗口: 前 {} 天 ({} 之前), 冻结 {} 个时间槽",
                        freeze_horizon, freeze_end_date, len(frozen_time_indices),
                    )

        # ── 8. 换线矩阵 ──
        # V3: 同时构建产品维度和 LPC 维度的换线时间查找表
        changeover_time: dict[tuple[str, str], float] = {}
        changeover_time_lpc: dict[tuple[str, str], float] = {}
        for entry in problem.changeover_matrix:
            from_p = entry.from_product_id or ""
            to_p = entry.to_product_id or ""
            if from_p and to_p:
                changeover_time[(from_p, to_p)] = entry.changeover_time or entry.setup_time
            from_lpc = entry.from_lpc_id or ""
            to_lpc = entry.to_lpc_id or ""
            if from_lpc and to_lpc:
                changeover_time_lpc[(from_lpc, to_lpc)] = entry.changeover_time or entry.setup_time
        for rule in problem.changeover_rules:
            changeover_time[(rule.from_product, rule.to_product)] = rule.changeover_hours
        logger.info(
            "换线矩阵: 产品维度={} 条, LPC维度={} 条",
            len(changeover_time), len(changeover_time_lpc),
        )

        # ── 9. 优先级 / 交期 / 需求 / 产品 ──
        priority_weights: dict[int, float] = {}
        due_dates: dict[int, int] = {}
        demands: dict[int, float] = {}
        products: dict[int, str] = {}
        priority_map = {
            "紧急": 5.0, "特急": 5.0, "P1": 5.0,
            "高": 3.0, "P2": 3.0,
            "中": 1.5, "普通": 1.0, "P3": 1.0,
            "低": 0.5,
        }

        for ei in expanded_items_list:
            i = item_indices[ei.key]
            priority_weights[i] = priority_map.get(ei.priority, 1.0)
            due_dates[i] = len(time_slots) - 1  # 默认最后时间槽
            demands[i] = ei.quantity
            products[i] = ei.product_id

        # V3.7: 周末约束 - 根据优先级决定哪些 item 不能在周末排产
        # 紧急：周六周日都可排
        # 高：周日不可排
        # 中/低/普通：周六周日都不可排
        weekend_blocked_items: set[int] = set()
        sunday_blocked_items: set[int] = set()
        for ei in expanded_items_list:
            i = item_indices[ei.key]
            pri = (ei.priority or "").strip()
            if pri in ("紧急", "特急", "P1"):
                continue  # 紧急：周末可排
            elif pri in ("高", "P2"):
                sunday_blocked_items.add(i)  # 高：仅周日不可排
            else:
                weekend_blocked_items.add(i)  # 中/低/普通：周六周日都不可排

        # 识别周末时间槽（基于 TimeSlot.date）
        weekend_time_indices: set[int] = set()
        sunday_time_indices: set[int] = set()
        from datetime import datetime as _dt
        for ts in time_slots:
            t = ts.index or ts.slot_id or 0
            if not ts.date:
                continue
            try:
                wd = _dt.strptime(ts.date, "%Y-%m-%d").weekday()  # 0=周一, 5=周六, 6=周日
            except ValueError:
                continue
            if wd == 5:  # 周六
                weekend_time_indices.add(t)
            elif wd == 6:  # 周日
                weekend_time_indices.add(t)
                sunday_time_indices.add(t)

        logger.info(
            "V3.7 周末约束: weekend_blocked={} items, sunday_blocked={} items, "
            "weekend_slots={}, sunday_slots={}",
            len(weekend_blocked_items), len(sunday_blocked_items),
            len(weekend_time_indices), len(sunday_time_indices),
        )

        # ── 10. Drum 产线 ──
        drum_workcenter_indices: set[int] = set()
        for vwc in virtual_wcs:
            if vwc.is_bottleneck:
                drum_workcenter_indices.add(workcenter_indices[vwc.key])

        # ── 11. 目标权重 ──
        objective_weights: dict[str, float] = {
            SoftRule.OTD_PRIORITY.value: 0.20,
            SoftRule.SETUP_MINIMIZATION.value: 0.10,
            SoftRule.LOAD_BALANCING.value: 0.50,
            SoftRule.DRUM_UTILIZATION.value: 0.10,
        }
        for rule, weight in problem.objective_weights.items():
            key = rule.value if isinstance(rule, SoftRule) else str(rule)
            objective_weights[key] = weight
        for key, weight in problem.soft_rule_weights.items():
            objective_weights[key] = weight

        # ── 12. 构建映射表 ──
        expanded_items_map = {item_indices[ei.key]: ei for ei in expanded_items_list}
        original_demand_map = {item_indices[ei.key]: ei.demand_id for ei in expanded_items_list}

        return BuiltConstraints(
            item_indices=item_indices,
            workcenter_indices=workcenter_indices,
            time_indices=time_indices,
            capacity=capacity,
            material_not_ready=material_not_ready,
            incompatible=incompatible,
            fixed=fixed,
            changeover_time=changeover_time,
            changeover_time_lpc=changeover_time_lpc,
            priority_weights=priority_weights,
            due_dates=due_dates,
            demands=demands,
            products=products,
            drum_workcenter_indices=drum_workcenter_indices,
            objective_weights=objective_weights,
            expanded_items=expanded_items_map,
            virtual_workcenters=virtual_wcs_map,
            process_order_groups=process_order_groups,
            process_predecessors=process_predecessors,
            process_dependency_info=process_dependency_info,
            original_demand_map=original_demand_map,
            item_seq_completed=item_seq_completed_map,
            slot_to_time_key=slot_to_time_key,
            frozen_time_indices=frozen_time_indices,
            weekend_blocked_items=weekend_blocked_items,
            sunday_blocked_items=sunday_blocked_items,
            weekend_time_indices=weekend_time_indices,
            sunday_time_indices=sunday_time_indices,
        )
