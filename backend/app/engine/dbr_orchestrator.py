"""DBR（鼓-缓冲-绳）编排器，实现约束理论排产核心逻辑。

包含四个子组件和一个主编排器：
- BottleneckIdentifier: 瓶颈识别
- DirectionStrategy: 方向策略（顺排/倒排）
- BufferCalculator: 缓冲计算
- BatchPlanner: 批量策略
- DBROrchestrator: 主编排器
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta

from loguru import logger

from app.engine.models import (
    BatchGroup,
    BatchPlan,
    Buffer,
    BufferType,
    DBRPlan,
    Item,
    ProductProcess,
    ProcessInfo,
    ProductionLine,
    ScheduledOp,
    TimeSlot,
)

# 旧名别名，保持向后兼容
WorkCenter = ProductionLine
ProcessRoute = type("ProcessRoute", (), {})  # 旧名占位，实际使用 ProductProcess

# ── 常量 ──────────────────────────────────────────────────

LC_THRESHOLD = 0.95           # L/C 瓶颈阈值
VARIABILITY_FACTOR = 0.3      # 波动率系数
MTTR_DEFAULT = 0.5            # 平均修复时间（小时）
LOGISTICS_BASE = 1.0          # 物流缓冲基础时间（小时）
LOGISTICS_MARGIN = 0.5        # 物流缓冲波动余量（小时）
TRANSFER_RATIO = 4            # 流转批量 = 加工批量 / 此值
GREEN_RATIO = 1.0             # 绿区 = 缓冲时长 × 100%
YELLOW_RATIO = 0.66           # 黄区 = 缓冲时长 × 66%
RED_RATIO = 0.33              # 红区 = 缓冲时长 × 33%

PRIORITY_ORDER = {"紧急": 0, "高": 1, "P1": 0, "P2": 1, "普通": 2, "P3": 2, "低": 3}


# ── BottleneckIdentifier ──────────────────────────────────


class BottleneckIdentifier:
    """瓶颈识别器，通过 L/C 比识别瓶颈工作中心。"""

    def identify(
        self,
        items: list[Item],
        workcenters: list[ProductionLine],
        process_routes: list[ProductProcess],
        time_slots: list[TimeSlot],
    ) -> list[str]:
        """计算各工作中心 L/C 比，返回瓶颈 ID 列表（按 L/C 降序）。

        Args:
            items: 订单列表
            workcenters: 产线列表（V2 ProductionLine）
            process_routes: 产品工序列表（V2 ProductProcess）
            time_slots: 可用时间槽列表

        Returns:
            瓶颈工作中心 ID 列表，L/C 最高的排最前
        """
        # 计算各工作中心的总负荷
        load_map: dict[str, float] = defaultdict(float)
        # V2: ProductProcess 按 product_id 分组，按 seq 排序
        pp_by_product: dict[str, list[ProductProcess]] = defaultdict(list)
        for pp in process_routes:
            pp_by_product[pp.product_id].append(pp)
        for pid in pp_by_product:
            pp_by_product[pid].sort(key=lambda p: p.seq)

        for item in items:
            pp_list = pp_by_product.get(item.product, [])
            for pp in pp_list:
                # cycle_time 单位为秒，转换为小时
                cycle_hours = pp.cycle_time / 3600.0 if pp.cycle_time > 100 else pp.cycle_time
                load_map[pp.process_id] += cycle_hours * item.quantity

        # 计算各工作中心的有效产能
        capacity_map: dict[str, float] = defaultdict(float)
        wc_map = {wc.id: wc for wc in workcenters}
        for slot in time_slots:
            wc = wc_map.get(slot.workcenter_id)
            oee = wc.oee if wc else 0.85
            cap = slot.available_hours if slot.available_hours > 0 else slot.available_capacity
            capacity_map[slot.workcenter_id] += cap * oee

        # 计算 L/C 比
        lc_map: dict[str, float] = {}
        for wc_id in capacity_map:
            load = load_map.get(wc_id, 0.0)
            cap = capacity_map[wc_id]
            lc = load / cap if cap > 0 else 0.0
            lc_map[wc_id] = lc

        # 筛选瓶颈：L/C > 95%
        drums = [
            wc_id for wc_id, lc in lc_map.items()
            if lc > LC_THRESHOLD
        ]
        drums.sort(key=lambda w: lc_map[w], reverse=True)

        logger.info(
            "瓶颈识别完成，L/C 分布: {}，瓶颈: {}",
            {k: round(v, 3) for k, v in lc_map.items()},
            drums,
        )
        return drums


# ── DirectionStrategy ─────────────────────────────────────


class DirectionStrategy:
    """方向策略，按 DBR 三段式排产：Drum 顺排、前段倒排、后段顺排。"""

    def plan(
        self,
        drum_ids: list[str],
        items: list[Item],
        process_routes: list[ProductProcess],
        time_slots: list[TimeSlot],
    ) -> tuple[list[ScheduledOp], dict[str, str]]:
        """执行 DBR 方向排产。

        Args:
            drum_ids: 瓶颈工作中心 ID 列表
            items: 订单列表
            process_routes: 产品工序列表（V2 ProductProcess）
            time_slots: 可用时间槽列表

        Returns:
            (排产工序列表, 投料时间映射 {item_no: start_time})
        """
        drum_set = set(drum_ids)
        # V2: ProductProcess 按 product_id 分组
        pp_by_product: dict[str, list[ProductProcess]] = defaultdict(list)
        for pp in process_routes:
            pp_by_product[pp.product_id].append(pp)
        for pid in pp_by_product:
            pp_by_product[pid].sort(key=lambda p: p.seq)

        # 按优先级排序订单
        sorted_items = sorted(
            items,
            key=lambda it: PRIORITY_ORDER.get(it.priority, 2),
        )

        # 构建各工作中心的时间槽队列
        slot_queue = _build_slot_queue(time_slots)

        ops: list[ScheduledOp] = []
        rope_times: dict[str, str] = {}

        for item in sorted_items:
            pp_list = pp_by_product.get(item.product, [])
            if not pp_list:
                continue

            # 将工序分为三段：drum 前 / drum / drum 后
            # V2: ProductProcess 没有 workcenter_id，用 process_id 判断是否在 drum_set
            pre_drum, drum_steps, post_drum = _split_route_v2(pp_list, drum_set)

            # ── Drum 工序：有限产能顺排 ──
            drum_ops = _forward_schedule(
                item.order_no, drum_steps, slot_queue, is_drum=True,
            )
            ops.extend(drum_ops)

            # Drum 最早开工时间（用于前段倒排基准）
            drum_start = drum_ops[0].start_time if drum_ops else ""

            # ── Drum 前工序：以 Drum 开工为基准倒排 ──
            pre_ops = _backward_schedule(
                item.order_no, pre_drum, drum_start, slot_queue,
            )
            ops.extend(pre_ops)

            # 投料时间 = 前段首工序的开工时间（若无前段则取 Drum 开工时间）
            if pre_ops:
                rope_times[item.order_no] = pre_ops[0].start_time
            elif drum_start:
                rope_times[item.order_no] = drum_start

            # ── Drum 后工序：按 Drum 产出节拍顺排 ──
            drum_end = drum_ops[-1].end_time if drum_ops else ""
            post_ops = _forward_schedule(
                item.order_no, post_drum, slot_queue,
                start_after=drum_end,
            )
            ops.extend(post_ops)

        logger.info("方向策略排产完成，工序数: {}，投料订单数: {}", len(ops), len(rope_times))
        return ops, rope_times


# ── BufferCalculator ──────────────────────────────────────


class BufferCalculator:
    """缓冲计算器，计算时间/物流/工艺三种缓冲及三色阈值。"""

    def calculate(
        self,
        drum_ids: list[str],
        process_routes: list[ProductProcess],
        workcenters: list[ProductionLine],
    ) -> dict[str, list[Buffer]]:
        """为每个瓶颈工作中心计算三种缓冲。

        Args:
            drum_ids: 瓶颈工作中心 ID 列表
            process_routes: 产品工序列表（V2 ProductProcess）
            workcenters: 产线列表（V2 ProductionLine）

        Returns:
            缓冲字典 {drum_id: [Buffer, ...]}
        """
        result: dict[str, list[Buffer]] = {}

        # 统计各工作中心的前置时间和工艺等待
        lead_time_map: dict[str, float] = defaultdict(float)
        process_wait_map: dict[str, float] = defaultdict(float)
        step_count_map: dict[str, int] = defaultdict(int)

        # V2: ProductProcess 按 product_id 分组
        pp_by_product: dict[str, list[ProductProcess]] = defaultdict(list)
        for pp in process_routes:
            pp_by_product[pp.product_id].append(pp)
        for pid in pp_by_product:
            pp_by_product[pid].sort(key=lambda p: p.seq)

        for _product_id, pp_list in pp_by_product.items():
            drum_idx = None
            for i, pp in enumerate(pp_list):
                if pp.process_id in drum_ids:
                    drum_idx = i
                    break

            if drum_idx is None:
                continue

            # Drum 前所有工序的节拍时间之和 = 前置时间
            for pp in pp_list[:drum_idx]:
                cycle_hours = pp.cycle_time / 3600.0 if pp.cycle_time > 100 else pp.cycle_time
                lead_time_map[pp.process_id] += cycle_hours
                step_count_map[pp.process_id] += 1

        for seq, drum_id in enumerate(drum_ids):
            buffers: list[Buffer] = []

            # ── 时间缓冲 = (平均前置时间 × 波动率系数) + MTTR ──
            avg_lead = (
                lead_time_map[drum_id] / step_count_map[drum_id]
                if step_count_map[drum_id] > 0
                else 0.0
            )
            time_buf = avg_lead * VARIABILITY_FACTOR + MTTR_DEFAULT
            buffers.append(Buffer(
                id=f"BUF-T-{drum_id}-{seq}",
                from_workcenter_id=drum_id,
                to_workcenter_id=drum_id,
                buffer_type=BufferType.TIME,
                duration_hours=round(time_buf, 2),
                green_zone=round(time_buf * GREEN_RATIO, 2),
                yellow_zone=round(time_buf * YELLOW_RATIO, 2),
                red_zone=round(time_buf * RED_RATIO, 2),
                description=f"时间缓冲: {avg_lead:.1f}h × {VARIABILITY_FACTOR} + {MTTR_DEFAULT}h",
            ))

            # ── 物流缓冲 = 物理转移时间 + 波动余量 ──
            log_buf = LOGISTICS_BASE + LOGISTICS_MARGIN
            buffers.append(Buffer(
                id=f"BUF-L-{drum_id}-{seq}",
                from_workcenter_id=drum_id,
                to_workcenter_id=drum_id,
                buffer_type=BufferType.LOGISTICS,
                duration_hours=round(log_buf, 2),
                green_zone=round(log_buf * GREEN_RATIO, 2),
                yellow_zone=round(log_buf * YELLOW_RATIO, 2),
                red_zone=round(log_buf * RED_RATIO, 2),
                description=f"物流缓冲: {LOGISTICS_BASE}h + {LOGISTICS_MARGIN}h",
            ))

            # ── 工艺缓冲 = 固化/晾干等强制等待（非占用式） ──
            proc_wait = process_wait_map.get(drum_id, 0.0)
            if proc_wait > 0:
                buffers.append(Buffer(
                    id=f"BUF-P-{drum_id}-{seq}",
                    from_workcenter_id=drum_id,
                    to_workcenter_id=drum_id,
                    buffer_type=BufferType.PROCESS,
                    duration_hours=round(proc_wait, 2),
                    green_zone=round(proc_wait * GREEN_RATIO, 2),
                    yellow_zone=round(proc_wait * YELLOW_RATIO, 2),
                    red_zone=round(proc_wait * RED_RATIO, 2),
                    description=f"工艺缓冲: 固化/晾干等待 {proc_wait:.1f}h",
                ))

            result[drum_id] = buffers

        total = sum(len(v) for v in result.values())
        logger.info("缓冲计算完成，共 {} 个缓冲", total)
        return result


# ── BatchPlanner ──────────────────────────────────────────


class BatchPlanner:
    """批量策略，用成组技术聚类订单并设定加工/流转批量。"""

    def plan(
        self,
        items: list[Item],
        changeover_matrix: dict[str, dict[str, float]],
    ) -> BatchPlan:
        """按 changeover_attr 聚类订单，组内按换线时间排序。

        Args:
            items: 订单列表
            changeover_matrix: 换线时间矩阵 {from_attr: {to_attr: hours}}

        Returns:
            批量计划
        """
        # 按 changeover_attr 分组（成组技术聚类）
        groups_map: dict[str, list[Item]] = defaultdict(list)
        for item in items:
            key = item.changeover_attr or item.product
            groups_map[key].append(item)

        groups: list[BatchGroup] = []
        for group_key, group_items in groups_map.items():
            # 组内按换线时间排序（贪心：每次选换线最短的下一个）
            sorted_items = self._sort_by_changeover(group_items, changeover_matrix)

            # 加工批量 = 组内总数量
            total_qty = sum(it.quantity for it in sorted_items)
            process_batch = total_qty
            transfer_batch = process_batch / TRANSFER_RATIO

            groups.append(BatchGroup(
                group_key=group_key,
                item_nos=[it.order_no for it in sorted_items],
                process_batch_size=round(process_batch, 2),
                transfer_batch_size=round(transfer_batch, 2),
            ))

        plan = BatchPlan(groups=groups, overlap_enabled=True)
        logger.info("批量计划完成，分组数: {}，重叠启用: {}", len(groups), plan.overlap_enabled)
        return plan

    @staticmethod
    def _sort_by_changeover(
        items: list[Item],
        matrix: dict[str, dict[str, float]],
    ) -> list[Item]:
        """贪心排序：每次选换线时间最短的下一个订单。"""
        if len(items) <= 1:
            return items

        remaining = list(items)
        sorted_list = [remaining.pop(0)]

        while remaining:
            current_attr = sorted_list[-1].changeover_attr or sorted_list[-1].product
            best_idx = 0
            best_cost = float("inf")

            for i, candidate in enumerate(remaining):
                cand_attr = candidate.changeover_attr or candidate.product
                cost = matrix.get(current_attr, {}).get(cand_attr, 0.0)
                if cost < best_cost:
                    best_cost = cost
                    best_idx = i

            sorted_list.append(remaining.pop(best_idx))

        return sorted_list


# ── DBROrchestrator ───────────────────────────────────────


class DBROrchestrator:
    """DBR 主编排器，串联瓶颈识别、方向策略、缓冲计算、批量策略。"""

    def __init__(self) -> None:
        self.bottleneck_id = BottleneckIdentifier()
        self.direction = DirectionStrategy()
        self.buffer_calc = BufferCalculator()
        self.batch_planner = BatchPlanner()

    def orchestrate(
        self,
        items: list[Item],
        workcenters: list[ProductionLine],
        process_routes: list[ProductProcess],
        changeover_matrix: dict[str, dict[str, float]],
        time_slots: list[TimeSlot],
        manual_drum: list[str] | None = None,
    ) -> DBRPlan:
        """执行 DBR 编排全流程。

        Args:
            items: 订单列表
            workcenters: 产线列表（V2 ProductionLine）
            process_routes: 产品工序列表（V2 ProductProcess）
            changeover_matrix: 换线时间矩阵
            time_slots: 可用时间槽列表
            manual_drum: 人工指定瓶颈列表（可选）

        Returns:
            DBRPlan 编排结果
        """
        logger.info("DBR 编排开始，订单数: {}，工作中心数: {}", len(items), len(workcenters))

        # 1. 瓶颈识别
        drum_ids = manual_drum if manual_drum else self.bottleneck_id.identify(
            items, workcenters, process_routes, time_slots,
        )
        logger.info("瓶颈工作中心: {}", drum_ids)

        # 2. 方向策略排产
        ops, rope_times = self.direction.plan(
            drum_ids, items, process_routes, time_slots,
        )

        # 3. 缓冲计算
        buffer_dict = self.buffer_calc.calculate(drum_ids, process_routes, workcenters)
        all_buffers = [b for buf_list in buffer_dict.values() for b in buf_list]

        # 4. 批量策略
        batch_plan = self.batch_planner.plan(items, changeover_matrix)

        # 5. 将批量信息写入排产工序
        batch_map: dict[str, BatchGroup] = {}
        for group in batch_plan.groups:
            for order_no in group.item_nos:
                batch_map[order_no] = group

        for op in ops:
            bg = batch_map.get(op.item_no)
            if bg:
                op.batch_no = bg.group_key
                op.process_batch_size = bg.process_batch_size
                op.transfer_batch_size = bg.transfer_batch_size

        # 6. 设置工作中心瓶颈标记
        wc_map = {wc.id: wc for wc in workcenters}
        for drum_id in drum_ids:
            if drum_id in wc_map:
                wc_map[drum_id].is_bottleneck = True

        plan = DBRPlan(
            drum_workcenter_id=drum_ids[0] if drum_ids else "",
            drum_ids=drum_ids,
            buffers=all_buffers,
            scheduled_ops=ops,
            rope_times=rope_times,
            batch_plan=batch_plan,
            metadata={
                "item_count": len(items),
                "drum_count": len(drum_ids),
                "buffer_count": len(all_buffers),
                "op_count": len(ops),
                "manual_drum": manual_drum is not None,
            },
        )

        logger.info(
            "DBR 编排完成，瓶颈: {}，缓冲: {}，工序: {}，投料: {}",
            len(drum_ids), len(all_buffers), len(ops), len(rope_times),
        )
        return plan


# ── 工具函数 ──────────────────────────────────────────────


def _parse_time(t: str) -> datetime:
    """解析时间字符串，支持 'YYYY-MM-DD HH:MM' 和 'HH:MM' 格式。"""
    try:
        return datetime.strptime(t, "%Y-%m-%d %H:%M")
    except ValueError:
        return datetime.strptime(t, "%H:%M").replace(
            year=2000, month=1, day=1,
        )


def _fmt_time(dt: datetime) -> str:
    """格式化时间为 'YYYY-MM-DD HH:MM'。"""
    return dt.strftime("%Y-%m-%d %H:%M")


def _split_route(
    steps: list, drum_set: set[str],
) -> tuple[list, list, list]:
    """将工序步骤分为 drum 前 / drum / drum 后三段。"""
    pre, drum, post = [], [], []
    drum_found = False
    post_drum = False

    for step in steps:
        if post_drum:
            post.append(step)
        elif step.workcenter_id in drum_set and not drum_found:
            drum_found = True
            drum.append(step)
        elif drum_found and step.workcenter_id in drum_set:
            drum.append(step)
        elif drum_found:
            post_drum = True
            post.append(step)
        else:
            pre.append(step)

    # 若无 drum 工序，全部视为前段（顺排）
    if not drum:
        pre = list(steps)

    return pre, drum, post


def _split_route_v2(
    pp_list: list[ProductProcess], drum_set: set[str],
) -> tuple[list[ProductProcess], list[ProductProcess], list[ProductProcess]]:
    """V2 版本：将 ProductProcess 列表分为 drum 前 / drum / drum 后三段。"""
    pre, drum, post = [], [], []
    drum_found = False
    post_drum = False

    for pp in pp_list:
        if post_drum:
            post.append(pp)
        elif pp.process_id in drum_set and not drum_found:
            drum_found = True
            drum.append(pp)
        elif drum_found and pp.process_id in drum_set:
            drum.append(pp)
        elif drum_found:
            post_drum = True
            post.append(pp)
        else:
            pre.append(pp)

    # 若无 drum 工序，全部视为前段（顺排）
    if not drum:
        pre = list(pp_list)

    return pre, drum, post


def _build_slot_queue(
    time_slots: list[TimeSlot],
) -> dict[str, list[TimeSlot]]:
    """按工作中心分组并按时间排序时间槽。"""
    queue: dict[str, list[TimeSlot]] = defaultdict(list)
    for slot in time_slots:
        if slot.workcenter_id:
            queue[slot.workcenter_id].append(slot)
    for wc_id in queue:
        queue[wc_id].sort(key=lambda s: (s.date, s.start_time))
    return queue


def _forward_schedule(
    item_no: str,
    steps: list,
    slot_queue: dict[str, list[TimeSlot]],
    is_drum: bool = False,
    start_after: str = "",
) -> list[ScheduledOp]:
    """顺排（Forward Scheduling），按工序顺序紧密排列。"""
    ops: list[ScheduledOp] = []
    cursor = start_after

    for step in steps:
        slots = slot_queue.get(step.workcenter_id, [])
        start, end = _find_next_slot(slots, step.duration_hours, after=cursor)
        ops.append(ScheduledOp(
            item_no=item_no,
            step_no=step.step_no,
            workcenter_id=step.workcenter_id,
            start_time=start,
            end_time=end,
            is_drum=is_drum,
        ))
        cursor = end

    return ops


def _backward_schedule(
    item_no: str,
    steps: list,
    anchor_time: str,
    slot_queue: dict[str, list[TimeSlot]],
) -> list[ScheduledOp]:
    """倒排（Backward Scheduling），以 anchor_time 为基准逆推。"""
    if not anchor_time or not steps:
        return []

    ops: list[ScheduledOp] = []
    cursor = anchor_time

    for step in reversed(steps):
        slots = slot_queue.get(step.workcenter_id, [])
        start, end = _find_prev_slot(slots, step.duration_hours, before=cursor)
        ops.append(ScheduledOp(
            item_no=item_no,
            step_no=step.step_no,
            workcenter_id=step.workcenter_id,
            start_time=start,
            end_time=end,
        ))
        cursor = start

    ops.reverse()
    return ops


def _find_next_slot(
    slots: list[TimeSlot],
    duration: float,
    after: str = "",
) -> tuple[str, str]:
    """在时间槽列表中找到下一个能容纳 duration 的槽位（顺排）。"""
    after_dt = _parse_time(after) if after else datetime(2000, 1, 1)

    for slot in slots:
        slot_start = _parse_time(f"{slot.date} {slot.start_time}")
        slot_end = _parse_time(f"{slot.date} {slot.end_time}")

        if slot_end <= after_dt:
            continue

        actual_start = max(slot_start, after_dt)
        available = (slot_end - actual_start).total_seconds() / 3600

        if available >= duration:
            actual_end = actual_start + timedelta(hours=duration)
            return _fmt_time(actual_start), _fmt_time(actual_end)

    logger.warning("未找到足够时间槽，duration={}h, after={}", duration, after)
    return "", ""


def _find_prev_slot(
    slots: list[TimeSlot],
    duration: float,
    before: str = "",
) -> tuple[str, str]:
    """在时间槽列表中逆推找到能容纳 duration 的槽位（倒排）。"""
    if not before:
        return "", ""

    before_dt = _parse_time(before)

    for slot in reversed(slots):
        slot_start = _parse_time(f"{slot.date} {slot.start_time}")
        slot_end = _parse_time(f"{slot.date} {slot.end_time}")

        if slot_start >= before_dt:
            continue

        actual_end = min(slot_end, before_dt)
        available = (actual_end - slot_start).total_seconds() / 3600

        if available >= duration:
            actual_start = actual_end - timedelta(hours=duration)
            return _fmt_time(actual_start), _fmt_time(actual_end)

    logger.warning("倒排未找到足够时间槽，duration={}h, before={}", duration, before)
    return "", ""
