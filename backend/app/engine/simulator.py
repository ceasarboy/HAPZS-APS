"""基于 SimPy 的离散事件仿真评估器。

模拟排产方案在真实车间中的执行过程，评估方案的实际执行效果。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import simpy
from loguru import logger

from app.engine.models import (
    Buffer,
    HardRule,
    ProductProcess,
    ProductionLine,
    SchedulingProblem,
    ScheduledTask,
)

# 旧名别名，保持向后兼容
WorkCenter = ProductionLine


# ── 仿真数据模型 ──────────────────────────────────────────────────────────


@dataclass
class BufferStatus:
    """缓冲区实时状态。"""

    buffer_id: str
    current_level: float  # 当前库存/在制品水平
    max_level: float  # 最大容量
    green_zone: float  # 安全区阈值
    yellow_zone: float  # 警戒区阈值
    red_zone: float  # 危险区阈值
    zone: str = "green"  # 当前所在区域


@dataclass
class SimEvent:
    """仿真事件。"""

    time: float
    event_type: str  # "start" / "end" / "changeover" / "buffer_enter" / "buffer_exit" / "wait"
    workcenter_id: str
    order_item_id: str
    product: str
    quantity: float
    detail: str = ""


@dataclass
class WorkcenterStats:
    """工作中心统计。"""

    workcenter_id: str
    total_work_time: float
    total_changeover_time: float
    total_idle_time: float
    utilization: float
    changeover_count: int


@dataclass
class SimulationResult:
    """仿真结果。"""

    total_time: float  # 总仿真时长
    workcenter_stats: Dict[str, WorkcenterStats]  # 各产线统计
    buffer_timeline: Dict[str, List[Tuple[float, float, str]]]  # buffer_id → [(time, level, zone)]
    events: List[SimEvent]  # 事件日志
    completion_times: Dict[str, float]  # order_item_id → 完工时间
    total_output: float  # 总产量
    total_changeover_time: float  # 总换线时间
    total_changeover_count: int  # 总换线次数
    avg_utilization: float  # 平均利用率
    buffer_violations: int  # 缓冲区进入红区次数
    hard_violations: List[str]  # 硬规则违反描述列表


# ── 默认参数 ──────────────────────────────────────────────────────────────

_DEFAULT_CHANGEOVER_HOURS = 0.5  # 默认换线时间（小时）
_BUFFER_MONITOR_INTERVAL = 0.1  # 缓冲区监控间隔（小时）


# ── 仿真器 ────────────────────────────────────────────────────────────────


class ShopFloorSimulator:
    """车间仿真器：模拟排产方案在真实车间中的执行过程。"""

    def __init__(self, problem: SchedulingProblem) -> None:
        self.problem = problem
        self.env: simpy.Environment | None = None
        self.workcenters: Dict[str, simpy.Resource] = {}
        self.buffers: Dict[str, BufferStatus] = {}
        self.event_log: List[SimEvent] = []
        self.hard_violations: List[str] = []
        self.buffer_violations: int = 0
        # 产线上最后一个加工的产品，用于判断换线
        self._last_product: Dict[str, str] = {}
        # 产线累计时间统计
        self._wc_work_time: Dict[str, float] = defaultdict(float)
        self._wc_changeover_time: Dict[str, float] = defaultdict(float)
        self._wc_changeover_count: Dict[str, int] = defaultdict(int)
        # 订单完工时间
        self._completion_times: Dict[str, float] = {}
        # 缓冲区水位时间线
        self._buffer_timeline: Dict[str, List[Tuple[float, float, str]]] = defaultdict(list)
        # 工作中心信息
        self._wc_map: Dict[str, ProductionLine] = {}
        # 工艺路径：product_id → steps（按 step_order 排序）
        self._route_map: Dict[str, list] = {}
        # 订单项的工序完成记录：order_item_id → set of step_order
        self._completed_steps: Dict[str, set] = defaultdict(set)

    def simulate(
        self, plan: List[ScheduledTask], until: float | None = None
    ) -> SimulationResult:
        """运行仿真，返回仿真结果。

        Args:
            plan: 排产结果任务列表
            until: 仿真截止时间（小时），None 表示仿真到所有任务完成

        Returns:
            SimulationResult: 仿真结果
        """
        # 处理空 plan
        if not plan:
            logger.info("仿真：plan 为空，返回空结果")
            return SimulationResult(
                total_time=0.0,
                workcenter_stats={},
                buffer_timeline={},
                events=[],
                completion_times={},
                total_output=0.0,
                total_changeover_time=0.0,
                total_changeover_count=0,
                avg_utilization=0.0,
                buffer_violations=0,
                hard_violations=[],
            )

        # 初始化
        self._init_sim_state()

        # 创建 SimPy 环境
        self.env = simpy.Environment()

        # 为每个工作中心创建 Resource（容量=1）
        for line in (self.problem.production_lines or self.problem.workcenters):
            self.workcenters[line.id] = simpy.Resource(self.env, capacity=1)

        # 初始化缓冲区
        self._init_buffers()

        # 计算仿真截止时间：所有任务的预估结束时间
        sim_end_time = self._estimate_end_time(plan)

        # 启动缓冲区监控进程
        for buf_id in self.buffers:
            self.env.process(self._monitor_buffer(buf_id, sim_end_time))

        # 按 start_time 排序，依次调度任务
        sorted_tasks = sorted(plan, key=lambda t: self._task_start_hours(t))

        for task in sorted_tasks:
            # 跳过 quantity=0 的任务
            if task.quantity <= 0:
                logger.debug("跳过 quantity=0 的任务: {}", task.order_item_id)
                continue
            self.env.process(self._run_task(task))

        # 运行仿真
        if until is not None:
            self.env.run(until=until)
        else:
            self.env.run(until=sim_end_time)

        # total_time 取最后一个任务的实际完成时间；如果任务未完成则用 env.now
        if self._completion_times:
            total_time = max(self._completion_times.values())
        elif self.env is not None:
            total_time = self.env.now
        else:
            total_time = 0.0

        # 构建结果
        return self._build_result(total_time)

    # ------------------------------------------------------------------
    # 初始化
    # ------------------------------------------------------------------

    def _init_sim_state(self) -> None:
        """重置仿真状态。"""
        self.workcenters = {}
        self.buffers = {}
        self.event_log = []
        self.hard_violations = []
        self.buffer_violations = 0
        self._last_product = {}
        self._wc_work_time = defaultdict(float)
        self._wc_changeover_time = defaultdict(float)
        self._wc_changeover_count = defaultdict(int)
        self._completion_times = {}
        self._buffer_timeline = defaultdict(list)
        self._completed_steps = defaultdict(set)

        # 构建工作中心索引
        self._wc_map = {wc.id: wc for wc in (self.problem.production_lines or self.problem.workcenters)}

        # 构建工艺路径索引（V2: 优先使用 product_processes，兼容 process_routes）
        self._route_map.clear()
        if self.problem.product_processes:
            pp_by_product: Dict[str, list] = defaultdict(list)
            for pp in self.problem.product_processes:
                pp_by_product[pp.product_id].append(pp)
            for pid in pp_by_product:
                pp_by_product[pid].sort(key=lambda p: p.seq)
            self._route_map = dict(pp_by_product)
        else:
            for route in self.problem.process_routes:
                sorted_steps = sorted(route.steps, key=lambda s: s.step_order)
                self._route_map[route.product_id] = sorted_steps

    def _init_buffers(self) -> None:
        """初始化缓冲区状态。"""
        for buf in self.problem.buffers:
            buf_id = buf.id or f"{buf.from_workcenter_id}->{buf.to_workcenter_id}"
            self.buffers[buf_id] = BufferStatus(
                buffer_id=buf_id,
                current_level=buf.green_zone,  # 初始水位设为绿区
                max_level=buf.green_zone * 3 if buf.green_zone > 0 else 100.0,
                green_zone=buf.green_zone,
                yellow_zone=buf.yellow_zone,
                red_zone=buf.red_zone,
                zone="green",
            )

    # ------------------------------------------------------------------
    # 任务执行进程
    # ------------------------------------------------------------------

    def _run_task(self, task: ScheduledTask):
        """SimPy process：执行单个排产任务。"""
        start_h = self._task_start_hours(task)
        wc_id = task.workcenter_id
        product = task.product or task.product_id
        order_item_id = task.order_item_id or task.item_id

        # 等待到 start_time
        if self.env.now < start_h:
            yield self.env.timeout(start_h - self.env.now)

        # 检查资源兼容性
        wc = self._wc_map.get(wc_id)
        if wc and wc.compatible_products and product not in wc.compatible_products:
            violation = f"资源兼容违反: 产品 {product} 不兼容产线 {wc_id} (任务 {order_item_id})"
            self.hard_violations.append(violation)
            logger.warning(violation)

        # 检查工艺顺序
        self._check_process_order(task)

        # 请求工作中心资源
        if wc_id not in self.workcenters:
            logger.warning("未知工作中心: {}, 跳过任务 {}", wc_id, order_item_id)
            return

        with self.workcenters[wc_id].request() as req:
            # 等待资源可用
            yield req

            actual_start = self.env.now

            # 换线
            last_prod = self._last_product.get(wc_id)
            if last_prod and last_prod != product:
                co_time = self._get_changeover_time(wc_id, last_prod, product)
                if co_time > 0:
                    self._wc_changeover_time[wc_id] += co_time
                    self._wc_changeover_count[wc_id] += 1
                    self.event_log.append(
                        SimEvent(
                            time=actual_start,
                            event_type="changeover",
                            workcenter_id=wc_id,
                            order_item_id=order_item_id,
                            product=product,
                            quantity=0.0,
                            detail=f"换线: {last_prod} → {product}, 耗时 {co_time:.2f}h",
                        )
                    )
                    yield self.env.timeout(co_time)

            # 记录开始事件
            self.event_log.append(
                SimEvent(
                    time=self.env.now,
                    event_type="start",
                    workcenter_id=wc_id,
                    order_item_id=order_item_id,
                    product=product,
                    quantity=task.quantity,
                    detail=f"开始加工, 数量={task.quantity:.1f}",
                )
            )

            # 计算加工时长
            duration = self._calc_duration(task, wc)
            if duration <= 0:
                duration = 0.01  # 最小加工时长

            # 更新缓冲区（任务开始时消耗前序缓冲区）
            self._buffer_on_task_start(task)

            # 执行加工
            yield self.env.timeout(duration)

            # 记录结束事件
            self.event_log.append(
                SimEvent(
                    time=self.env.now,
                    event_type="end",
                    workcenter_id=wc_id,
                    order_item_id=order_item_id,
                    product=product,
                    quantity=task.quantity,
                    detail=f"加工完成, 耗时 {duration:.2f}h",
                )
            )

            # 更新统计
            self._wc_work_time[wc_id] += duration
            self._last_product[wc_id] = product
            self._completion_times[order_item_id] = self.env.now

            # 更新缓冲区（任务完成时填充后续缓冲区）
            self._buffer_on_task_end(task)

            # 记录工序完成
            self._completed_steps[order_item_id].add(task.step_order)

    # ------------------------------------------------------------------
    # 换线时间
    # ------------------------------------------------------------------

    def _get_changeover_time(
        self, wc_id: str, from_product: str, to_product: str
    ) -> float:
        """从换线矩阵获取换线时间。"""
        # 优先查 changeover_matrix
        for entry in self.problem.changeover_matrix:
            if entry.from_product_id == from_product and entry.to_product_id == to_product:
                return entry.changeover_time

        # 其次查 changeover_rules
        for rule in self.problem.changeover_rules:
            if rule.from_product == from_product and rule.to_product == to_product:
                return rule.changeover_hours

        return _DEFAULT_CHANGEOVER_HOURS

    # ------------------------------------------------------------------
    # 加工时长计算
    # ------------------------------------------------------------------

    def _calc_duration(self, task: ScheduledTask, wc: ProductionLine | None) -> float:
        """计算加工时长 = quantity / (hourly_capacity * oee)。"""
        hourly_cap = 0.0
        oee = 1.0

        if wc:
            hourly_cap = wc.hourly_capacity
            oee = wc.oee if wc.oee > 0 else 1.0

        if hourly_cap <= 0:
            # 从工艺路径获取标准工时
            route = self._route_map.get(task.product or task.product_id)
            if route:
                for step in route:
                    if step.workcenter_id == task.workcenter_id:
                        return step.standard_hours * task.quantity if task.quantity > 0 else step.standard_hours
            # 兜底：假设 1 小时
            return 1.0

        return task.quantity / (hourly_cap * oee)

    # ------------------------------------------------------------------
    # 缓冲区监控
    # ------------------------------------------------------------------

    def _monitor_buffer(self, buf_id: str, end_time: float):
        """持续监控缓冲区水位，记录进入红区事件。"""
        while self.env.now < end_time:
            yield self.env.timeout(_BUFFER_MONITOR_INTERVAL)

            buf_status = self.buffers.get(buf_id)
            if buf_status is None:
                continue

            # 更新 zone
            prev_zone = buf_status.zone
            if buf_status.current_level >= buf_status.green_zone:
                buf_status.zone = "green"
            elif buf_status.current_level >= buf_status.yellow_zone:
                buf_status.zone = "yellow"
            else:
                buf_status.zone = "red"

            # 进入红区时记录违反
            if buf_status.zone == "red" and prev_zone != "red":
                self.buffer_violations += 1
                violation = f"缓冲区红区违反: {buf_id} 水位 {buf_status.current_level:.1f} 低于红区阈值 {buf_status.red_zone:.1f}"
                self.hard_violations.append(violation)
                logger.warning(violation)

            # 记录时间线
            self._buffer_timeline[buf_id].append(
                (self.env.now, buf_status.current_level, buf_status.zone)
            )

    def _buffer_on_task_start(self, task: ScheduledTask) -> None:
        """任务开始时消耗前序缓冲区。"""
        for buf in self.problem.buffers:
            if buf.to_workcenter_id == task.workcenter_id:
                buf_id = buf.id or f"{buf.from_workcenter_id}->{buf.to_workcenter_id}"
                buf_status = self.buffers.get(buf_id)
                if buf_status:
                    buf_status.current_level = max(0, buf_status.current_level - task.quantity)

    def _buffer_on_task_end(self, task: ScheduledTask) -> None:
        """任务完成时填充后续缓冲区。"""
        for buf in self.problem.buffers:
            if buf.from_workcenter_id == task.workcenter_id:
                buf_id = buf.id or f"{buf.from_workcenter_id}->{buf.to_workcenter_id}"
                buf_status = self.buffers.get(buf_id)
                if buf_status:
                    buf_status.current_level = min(
                        buf_status.max_level,
                        buf_status.current_level + task.quantity,
                    )

    # ------------------------------------------------------------------
    # 硬规则检查
    # ------------------------------------------------------------------

    def _check_process_order(self, task: ScheduledTask) -> None:
        """检查工艺顺序：同一订单的前序工序必须先完成。"""
        product = task.product or task.product_id
        route = self._route_map.get(product)
        if not route:
            return

        # 找到当前工序
        current_step_order = task.step_order or task.step_no
        if current_step_order <= 0:
            return

        # 检查前序工序是否已完成
        order_item_id = task.order_item_id or task.item_id
        for step in route:
            if step.step_order < current_step_order:
                if step.step_order not in self._completed_steps.get(order_item_id, set()):
                    violation = (
                        f"工艺顺序违反: 订单 {order_item_id} 工序 {current_step_order} "
                        f"开始时，前序工序 {step.step_order}({step.step_name}) 尚未完成"
                    )
                    self.hard_violations.append(violation)
                    logger.warning(violation)
                    return  # 每个任务只记录一次

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _estimate_end_time(self, plan: List[ScheduledTask]) -> float:
        """估算所有任务完成的时间，作为仿真截止时间。"""
        wc_map = {wc.id: wc for wc in (self.problem.production_lines or self.problem.workcenters)}
        max_end = 0.0

        # 按产线分组，累加工时和换线时间
        wc_tasks: Dict[str, List[ScheduledTask]] = defaultdict(list)
        for task in plan:
            if task.quantity <= 0:
                continue
            wc_tasks[task.workcenter_id].append(task)

        for wc_id, tasks in wc_tasks.items():
            tasks_sorted = sorted(tasks, key=lambda t: self._task_start_hours(t))
            wc = wc_map.get(wc_id)
            timeline = 0.0
            last_product = ""
            for task in tasks_sorted:
                start_h = self._task_start_hours(task)
                if start_h > timeline:
                    timeline = start_h
                # 换线
                product = task.product or task.product_id
                if last_product and last_product != product:
                    timeline += self._get_changeover_time(wc_id, last_product, product)
                # 加工
                duration = self._calc_duration(task, wc)
                timeline += max(duration, 0.01)
                last_product = product
            max_end = max(max_end, timeline)

        # 留一点余量确保监控进程能记录最终状态
        return max_end + _BUFFER_MONITOR_INTERVAL * 2

    def _task_start_hours(self, task: ScheduledTask) -> float:
        """将任务的 start_time 转换为小时数。"""
        if task.start_time is not None:
            # datetime → 相对于 0 点的小时偏移
            # 使用 timestamp 转换，取相对值
            import datetime

            if isinstance(task.start_time, datetime.datetime):
                # 以 0 为基准，转换为小时
                epoch = datetime.datetime(2000, 1, 1)
                delta = task.start_time - epoch
                return delta.total_seconds() / 3600.0
            return float(task.start_time)
        # 兜底：使用 slot_id
        if task.start_slot > 0:
            return float(task.start_slot)
        return 0.0

    # ------------------------------------------------------------------
    # 构建结果
    # ------------------------------------------------------------------

    def _build_result(self, total_time: float) -> SimulationResult:
        """根据仿真数据构建结果。"""
        # 各工作中心统计
        wc_stats: Dict[str, WorkcenterStats] = {}
        for wc in (self.problem.production_lines or self.problem.workcenters):
            work_time = self._wc_work_time.get(wc.id, 0.0)
            co_time = self._wc_changeover_time.get(wc.id, 0.0)
            co_count = self._wc_changeover_count.get(wc.id, 0)
            idle_time = max(0.0, total_time - work_time - co_time)
            utilization = (work_time + co_time) / total_time if total_time > 0 else 0.0

            wc_stats[wc.id] = WorkcenterStats(
                workcenter_id=wc.id,
                total_work_time=work_time,
                total_changeover_time=co_time,
                total_idle_time=idle_time,
                utilization=utilization,
                changeover_count=co_count,
            )

        # 汇总统计
        total_co_time = sum(self._wc_changeover_time.values())
        total_co_count = sum(self._wc_changeover_count.values())
        total_output = sum(
            self._wc_work_time.get(wc.id, 0.0) * wc.hourly_capacity * wc.oee
            for wc in self.problem.workcenters
        )

        # 平均利用率
        if wc_stats:
            avg_util = sum(s.utilization for s in wc_stats.values()) / len(wc_stats)
        else:
            avg_util = 0.0

        # 有限产能检查：同一产线同一时间的任务是否有重叠
        self._check_finite_capacity()

        return SimulationResult(
            total_time=total_time,
            workcenter_stats=wc_stats,
            buffer_timeline=dict(self._buffer_timeline),
            events=self.event_log,
            completion_times=dict(self._completion_times),
            total_output=total_output,
            total_changeover_time=total_co_time,
            total_changeover_count=total_co_count,
            avg_utilization=avg_util,
            buffer_violations=self.buffer_violations,
            hard_violations=self.hard_violations,
        )

    def _check_finite_capacity(self) -> None:
        """检查有限产能违反：同一产线同一时间的任务是否有重叠。"""
        # 按产线分组
        wc_tasks: Dict[str, List[ScheduledTask]] = defaultdict(list)
        for task in (self.problem.demand_plans or self.problem.order_items or []):
            pass  # 不从 order_items 检查

        # 通过事件日志检查：如果同一产线有重叠的 start/end 事件
        # 简化：通过事件日志中的 start 和 end 事件对检查
        wc_active: Dict[str, List[Tuple[float, float, str]]] = defaultdict(list)
        for evt in self.event_log:
            if evt.event_type == "start":
                wc_active[evt.workcenter_id].append(
                    (evt.time, -1, evt.order_item_id)  # -1 占位 end_time
                )
            elif evt.event_type == "end":
                # 找到对应的 start 并更新
                for i, (s, e, oid) in enumerate(wc_active.get(evt.workcenter_id, [])):
                    if oid == evt.order_item_id and e == -1:
                        wc_active[evt.workcenter_id][i] = (s, evt.time, oid)
                        break

        # 检查重叠
        for wc_id, intervals in wc_active.items():
            intervals.sort()
            for i in range(len(intervals)):
                for j in range(i + 1, len(intervals)):
                    s1, e1, oid1 = intervals[i]
                    s2, e2, oid2 = intervals[j]
                    if e1 == -1 or e2 == -1:
                        continue
                    if s2 < e1:  # 重叠
                        violation = (
                            f"有限产能违反: 产线 {wc_id} 上任务 {oid1}({s1:.2f}-{e1:.2f}h) "
                            f"与任务 {oid2}({s2:.2f}-{e2:.2f}h) 时间重叠"
                        )
                        self.hard_violations.append(violation)
                        break  # 每个任务只报告一次
