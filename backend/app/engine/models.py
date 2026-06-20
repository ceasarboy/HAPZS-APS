"""排产引擎核心数据模型，基于 TOC/DBR 理论。"""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


# ── 枚举 ──────────────────────────────────────────────────────────────────


class WorkCenterType(str, enum.Enum):
    """工作中心类型。"""
    PRODUCTION_LINE = "PRODUCTION_LINE"
    EQUIPMENT = "EQUIPMENT"
    STATION = "STATION"


class WorkCenterStatus(str, enum.Enum):
    """工作中心状态。"""
    AVAILABLE = "AVAILABLE"
    MAINTENANCE = "MAINTENANCE"
    DOWN = "DOWN"


class OrderPriority(str, enum.Enum):
    """订单优先级。"""
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class OrderStatus(str, enum.Enum):
    """订单状态。"""
    PENDING = "PENDING"
    SCHEDULING = "SCHEDULING"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class OrderItemStatus(str, enum.Enum):
    """订单明细状态。"""
    PENDING = "PENDING"
    SCHEDULING = "SCHEDULING"
    SCHEDULED = "SCHEDULED"
    IN_PRODUCTION = "IN_PRODUCTION"
    COMPLETED = "COMPLETED"


class BufferType(str, enum.Enum):
    """缓冲类型。"""
    TIME = "TIME"
    INVENTORY = "INVENTORY"
    TRANSFER = "TRANSFER"
    CURING = "CURING"
    LOGISTICS = "LOGISTICS"
    PROCESS = "PROCESS"


class SolveStatus(str, enum.Enum):
    """求解状态。"""
    OPTIMAL = "OPTIMAL"
    FEASIBLE = "FEASIBLE"
    INFEASIBLE = "INFEASIBLE"
    TIMEOUT = "TIMEOUT"


class HardRule(str, enum.Enum):
    """硬规则枚举。"""
    FINITE_CAPACITY = "FINITE_CAPACITY"
    MATERIAL_READY = "MATERIAL_READY"
    PROCESS_ORDER = "PROCESS_ORDER"
    RESOURCE_COMPATIBILITY = "RESOURCE_COMPATIBILITY"
    SKILL_MATRIX = "SKILL_MATRIX"
    FREEZE_WINDOW = "FREEZE_WINDOW"
    CURING_TIME = "CURING_TIME"
    TRANSFER_TIME = "TRANSFER_TIME"
    SINGLE_PRODUCT_PER_SLOT = "SINGLE_PRODUCT_PER_SLOT"


class SoftRule(str, enum.Enum):
    """软规则枚举。"""
    OTD_PRIORITY = "OTD_PRIORITY"
    SETUP_MINIMIZATION = "SETUP_MINIMIZATION"
    LOAD_BALANCING = "LOAD_BALANCING"
    WIP_CONTROL = "WIP_CONTROL"
    DRUM_UTILIZATION = "DRUM_UTILIZATION"
    PLAN_STABILITY = "PLAN_STABILITY"
    MINIMIZE_CHANGEOVER = "MINIMIZE_CHANGEOVER"
    PRIORITY_FIRST = "PRIORITY_FIRST"
    DUE_DATE_FIRST = "DUE_DATE_FIRST"
    BALANCE_LOAD = "BALANCE_LOAD"
    MINIMIZE_MAKESPAN = "MINIMIZE_MAKESPAN"


# ── 基础实体 ──────────────────────────────────────────────────────────────


@dataclass
class ProductionLine:
    """产线（V2，替代 WorkCenter）。"""
    id: str
    line_code: str = ""
    line_name: str = ""
    line_type: str = "主产线"  # 主产线/辅助线/特种线/灵活线
    daily_capacity: int = 0
    line_load: float = 0.0
    efficiency: float = 100.0
    location: str = ""
    status: str = "运行中"
    # 兼容旧字段
    hourly_capacity: int = 0  # = daily_capacity // 12
    is_bottleneck: bool = False
    compatible_products: list[str] = field(default_factory=list)
    # 兼容 WorkCenter 属性名
    code: str = ""
    name: str = ""
    oee: float = 1.0

    def __post_init__(self) -> None:
        if self.daily_capacity and not self.hourly_capacity:
            self.hourly_capacity = self.daily_capacity // 12
        if not self.code:
            self.code = self.line_code
        if not self.name:
            self.name = self.line_name
        if not self.oee or self.oee == 1.0:
            self.oee = self.efficiency / 100.0


@dataclass
class WorkCenter:
    """工作中心。"""
    id: str
    code: str = ""
    name: str = ""
    type: WorkCenterType = WorkCenterType.PRODUCTION_LINE
    oee: float = 1.0
    daily_capacity: float = 0.0
    hourly_capacity: float = 0.0
    status: WorkCenterStatus = WorkCenterStatus.AVAILABLE
    is_bottleneck: bool = False
    compatible_products: list[str] = field(default_factory=list)


@dataclass
class ProductionLineInfo:
    """产线信息（V2，求解器用，替代 WorkcenterInfo）。"""
    id: str
    name: str = ""
    daily_capacity: int = 0
    hourly_capacity: int = 0
    efficiency: float = 100.0


@dataclass
class WorkcenterInfo:
    """产线信息（求解器用）。"""
    id: str
    name: str = ""
    capacity_per_slot: float = 100.0
    compatible_products: list[str] = field(default_factory=list)
    oee: float = 1.0
    is_drum: bool = False


@dataclass
class ProductInfo:
    """产品信息（求解器 / benchmark 使用）。"""
    id: str = ""
    name: str = ""
    compatible_workcenters: list[str] = field(default_factory=list)
    changeover_group: str = ""


@dataclass
class Product:
    """产品。"""
    id: str
    code: str = ""
    name: str = ""
    changeover_attr: str = ""
    output_rate: float = 1.0
    batch_size: int = 1
    processing_batch: int = 1
    transfer_batch: int = 1
    compatible_workcenters: list[str] = field(default_factory=list)


@dataclass
class ProcessStep:
    """工序步骤。"""
    step_order: int = 0
    step_name: str = ""
    workcenter_id: str = ""
    standard_hours: float = 0.0
    is_drum: bool = False
    curing_time: float = 0.0
    transfer_time: float = 0.0
    is_resource_occupying: bool = True
    # 以下字段供 dbr_orchestrator 使用
    step_no: int = 0
    duration_hours: float = 0.0
    process_type: str = ""

    def __post_init__(self) -> None:
        # step_no 和 step_order 互相同步
        if self.step_no and not self.step_order:
            self.step_order = self.step_no
        if self.step_order and not self.step_no:
            self.step_no = self.step_order
        # duration_hours 和 standard_hours 互相同步
        if self.duration_hours and not self.standard_hours:
            self.standard_hours = self.duration_hours
        if self.standard_hours and not self.duration_hours:
            self.duration_hours = self.standard_hours


@dataclass
class ProcessRoute:
    """工艺路径，一个产品一条路径。"""
    id: str = ""
    product_id: str = ""
    steps: list[ProcessStep] = field(default_factory=list)
    # 兼容字段
    product: str = ""
    item_no: str = ""

    def __post_init__(self) -> None:
        if self.product and not self.product_id:
            self.product_id = self.product
        if self.product_id and not self.product:
            self.product = self.product_id
        if self.item_no and not self.product_id:
            self.product_id = self.item_no
            self.product = self.item_no


@dataclass
class ProcessInfo:
    """工序信息（V2 新增）。"""
    id: str
    proc_code: str = ""
    proc_name: str = ""
    proc_type: str = ""  # 成型/焊接/处理/组装/检测
    constraint_type: str = ""  # 机时约束/人员工时约束
    cycle_time: float = 0.0  # 标准节拍(秒)
    setup_time: float = 0.0  # 换型时间(分钟)
    wait_time: float = 0.0  # 等待时间(分钟)
    wait_includes_offhours: bool = True  # 等待时间是否计入下班时间（自然等待=True，工作时间等待=False）
    prep_time: float = 0.0  # 准备时间(分钟)
    is_qc_point: bool = False  # 是否质检点
    status: str = "启用"


@dataclass
class ProductProcess:
    """产品工艺（V2，替代 ProcessRoute 的产品维度部分）。"""
    id: str = ""
    product_id: str = ""  # 关联产品 rowId
    process_id: str = ""  # 关联工序 rowId
    seq: int = 0  # 工序顺序（同 seq 值的工序互为并行）
    std_time: float = 0.0  # 标准工时(秒)
    dependency_type: str = "FS"  # 依赖类型：FS/SS/FF/SF
    is_key: bool = False  # 是否关键工序
    remark: str = ""


@dataclass
class ProcessDependency:
    """工序依赖关系（V3 DAG 并行支持）。

    表示 from_process 必须在 to_process 之前完成。
    如果没有显式依赖，则从 ProductProcess 的 seq 自动推导：
    - 同一 seq 值的工序互为并行
    - seq=N 的工序，前驱是 seq=N-1 的所有工序
    """
    id: str = ""
    product_id: str = ""  # 关联产品
    from_process: str = ""  # 前驱工序 ID
    to_process: str = ""  # 后继工序 ID


@dataclass
class LineProcessConfig:
    """产线工艺配置（V2 新增）。"""
    id: str = ""
    line_id: str = ""  # 关联产线 rowId
    process_id: str = ""  # 关联工序 rowId
    daily_capacity: int = 0
    efficiency: float = 100.0
    min_batch: int = 0
    is_bottleneck: bool = False
    equipment_count: int = 0
    worker_count: int = 0
    status: str = "启用"


@dataclass
class Order:
    """生产订单。"""
    id: str = ""
    order_no: str = ""
    priority: OrderPriority = OrderPriority.P2
    delivery_date: datetime | None = None
    status: OrderStatus = OrderStatus.PENDING
    description: str = ""
    # 兼容字段
    quantity: float = 0.0
    material_ready: str = ""


@dataclass
class OrderItem:
    """订单明细。"""
    id: str = ""
    order_id: str = ""
    product_id: str = ""
    demand_qty: float = 0.0
    scheduled_qty: float = 0.0
    delivery_date: datetime | None = None
    status: OrderItemStatus = OrderItemStatus.PENDING
    # 兼容字段（solver_ga / benchmark 使用）
    order_no: str = ""
    product: str = ""
    quantity: float = 0.0
    priority: str = "普通"
    material_ready: str = ""
    changeover_group: str = ""
    compatible_workcenters: list[str] = field(default_factory=list)
    duration_slots: int = 1

    def __post_init__(self) -> None:
        if self.product and not self.product_id:
            self.product_id = self.product
        if self.product_id and not self.product:
            self.product = self.product_id
        if self.quantity and not self.demand_qty:
            self.demand_qty = self.quantity
        if self.demand_qty and not self.quantity:
            self.quantity = self.demand_qty


@dataclass
class DemandPlan:
    """需求计划（V2，替代 Order + OrderItem）。"""
    id: str = ""
    dp_code: str = ""  # 订单编号
    product_id: str = ""  # 关联产品 rowId
    quantity: int = 0  # 需求数量
    unit: str = "台"
    due_date: str = ""  # 交付日期
    priority: str = "中"  # 优先级：紧急/高/中/低
    status: str = "待确认"
    remark: str = ""
    # 兼容旧字段
    product: str = ""  # = product_id 的别名
    product_code: str = ""
    product_name: str = ""
    scheduled_qty: int = 0
    compatible_workcenters: list[str] = field(default_factory=list)
    process_route: list[ProductProcess] = field(default_factory=list)

    def __post_init__(self):
        if not self.product and self.product_id:
            self.product = self.product_id


@dataclass
class ChangeoverMatrix:
    """换线矩阵。"""
    from_product_id: str = ""
    to_product_id: str = ""
    changeover_time: float = 0.0
    changeover_cost: float = 0.0
    similarity_score: float = 1.0


@dataclass
class ChangeoverRule:
    """换线规则（benchmark / evaluator 使用）。"""
    from_product: str = ""
    to_product: str = ""
    changeover_hours: float = 0.0


@dataclass
class ChangeoverEntry:
    """换线矩阵条目（constraint_builder 使用）。"""
    from_product: str = ""
    to_product: str = ""
    changeover_time: float = 0.0


@dataclass
class Material:
    """物料齐套。"""
    id: str = ""
    name: str = ""
    code: str = ""
    available_qty: float = 0.0
    in_transit_qty: float = 0.0
    safety_stock: float = 0.0
    available_date: datetime | None = None


@dataclass
class MaterialMaster:
    """物料主数据（V2 新增）。"""
    id: str = ""
    mat_code: str = ""
    mat_name: str = ""
    mat_type: str = ""  # 原材料/元器件/辅料/包装材料/半成品
    unit: str = ""
    safety_stock: int = 0
    stock_qty: int = 0
    in_transit: int = 0
    status: str = "正常"


@dataclass
class ProcessBOM:
    """工序 BOM（V2 新增）。"""
    id: str = ""
    product_id: str = ""  # 关联产品
    process_id: str = ""  # 关联工序
    material_id: str = ""  # 关联物料
    unit_qty: float = 0.0  # 单位用量
    reusable: bool = False  # 是否可复用
    remark: str = ""


@dataclass
class MaterialKitting:
    """物料齐套（V2，替代 Material，工序级）。"""
    id: str = ""
    demand_id: str = ""  # 关联需求计划
    product_id: str = ""  # 关联产品
    process_id: str = ""  # 关联工序
    material_id: str = ""  # 关联物料
    required_qty: int = 0
    available_qty: int = 0
    shortage_qty: int = 0
    kitting_date: str = ""
    kitting_status: str = "待确认"  # 齐套/缺料/待确认


@dataclass
class TimeSlot:
    """时间槽。"""
    date: str = ""
    hour: int = 0
    workcenter_id: str = ""
    available_capacity: float = 0.0
    # V2 工序级字段
    process_id: str = ""  # 关联工序 rowId（资源日历中每行对应一个产线+工序+时段）
    # 兼容字段
    index: int = 0
    slot_id: int = 0
    start_time: str = "08:00"
    end_time: str = "20:00"
    shift: str = ""
    capacity: dict[str, float] = field(default_factory=dict)
    is_frozen: bool = False
    available_hours: float = 0.0

    def __post_init__(self) -> None:
        if self.slot_id and not self.index:
            self.index = self.slot_id
        if self.index and not self.slot_id:
            self.slot_id = self.index


# ── DBR 相关 ──────────────────────────────────────────────────────────────


@dataclass
class Buffer:
    """缓冲配置。"""
    id: str = ""
    from_workcenter_id: str = ""
    to_workcenter_id: str = ""
    buffer_type: BufferType = BufferType.TIME
    duration_hours: float = 0.0
    green_zone: float = 0.0
    yellow_zone: float = 0.0
    red_zone: float = 0.0
    # 兼容字段
    workcenter_id: str = ""
    description: str = ""

    def __post_init__(self) -> None:
        if self.workcenter_id and not self.from_workcenter_id:
            self.from_workcenter_id = self.workcenter_id


@dataclass
class BatchGroup:
    """批量分组。"""
    group_key: str = ""
    item_nos: list[str] = field(default_factory=list)
    process_batch_size: float = 0.0
    transfer_batch_size: float = 0.0


@dataclass
class BatchPlan:
    """批量策略。"""
    processing_batch: int = 1
    transfer_batch: int = 1
    overlap_enabled: bool = False
    groups: list[BatchGroup] = field(default_factory=list)


@dataclass
class Item:
    """订单项（dbr_orchestrator 使用）。"""
    order_no: str = ""
    product: str = ""
    quantity: float = 0.0
    priority: str = "普通"
    changeover_attr: str = ""
    delivery_date: str = ""


@dataclass
class ScheduledOp:
    """排产工序（dbr_orchestrator 使用）。"""
    item_no: str = ""
    step_no: int = 0
    workcenter_id: str = ""
    start_time: str = ""
    end_time: str = ""
    is_drum: bool = False
    batch_no: str = ""
    process_batch_size: float = 0.0
    transfer_batch_size: float = 0.0


@dataclass
class ScheduledTask:
    """排产结果任务。"""
    id: str = ""
    order_item_id: str = ""
    product_id: str = ""
    workcenter_id: str = ""
    step_order: int = 0
    start_time: datetime | None = None
    end_time: datetime | None = None
    quantity: float = 0.0
    buffer_before: float = 0.0
    buffer_type: BufferType | None = None
    plan_id: str = ""
    # V2 工序关联字段
    process_id: str = ""  # 关联工序 rowId
    process_code: str = ""  # 工序编码
    process_name: str = ""  # 工序名称
    seq: int = 0  # 工序顺序
    constraint_type: str = ""  # 约束类型
    # V3 依赖关系字段
    dependency_type: str = ""  # 依赖类型：FS/SS/FF/SF
    wait_time: float = 0.0  # 等待时间(分钟)
    prep_time: float = 0.0  # 准备时间(分钟)
    # 兼容字段（solver_ga / benchmark / evaluator 使用）
    item_id: str = ""
    time_slot: int = 0
    task_id: str = ""
    order_id: str = ""
    slot_id: int = 0
    step_no: int = 0
    product: str = ""
    start_slot: int = 0
    end_slot: int = 0

    def __post_init__(self) -> None:
        if self.item_id and not self.order_item_id:
            self.order_item_id = self.item_id
        if self.order_item_id and not self.item_id:
            self.item_id = self.order_item_id
        if self.time_slot and not self.slot_id:
            self.slot_id = self.time_slot
        if self.slot_id and not self.time_slot:
            self.time_slot = self.slot_id
        if self.product_id and not self.product:
            self.product = self.product_id
        if self.product and not self.product_id:
            self.product_id = self.product
        if self.step_order and not self.step_no:
            self.step_no = self.step_order
        if self.step_no and not self.step_order:
            self.step_order = self.step_no
        if not self.task_id:
            self.task_id = self.id or f"{self.order_item_id}@{self.workcenter_id}"


@dataclass
class DBRPlan:
    """DBR 编排结果。"""
    drum_workcenter_id: str = ""
    drum_ids: list[str] = field(default_factory=list)
    drum_schedule: list[ScheduledTask] = field(default_factory=list)
    pre_drum_schedule: list[ScheduledTask] = field(default_factory=list)
    post_drum_schedule: list[ScheduledTask] = field(default_factory=list)
    buffers: list[Buffer] = field(default_factory=list)
    rope_points: list[dict[str, Any]] = field(default_factory=dict)
    batch_plan: BatchPlan | None = None
    # 兼容字段
    scheduled_ops: list[ScheduledOp] = field(default_factory=list)
    rope_times: dict[str, str] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


# ── 求解器接口 ────────────────────────────────────────────────────────────


@dataclass
class SchedulingProblem:
    """求解问题，求解器输入。"""
    production_lines: list[ProductionLine] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)
    demand_plans: list[DemandPlan] = field(default_factory=list)
    time_slots: list[TimeSlot] = field(default_factory=list)
    changeover_matrix: list[ChangeoverMatrix] = field(default_factory=list)
    buffers: list[Buffer] = field(default_factory=list)
    # V2 新增字段
    process_info: list[ProcessInfo] = field(default_factory=list)
    product_processes: list[ProductProcess] = field(default_factory=list)
    line_process_configs: list[LineProcessConfig] = field(default_factory=list)
    material_masters: list[MaterialMaster] = field(default_factory=list)
    process_boms: list[ProcessBOM] = field(default_factory=list)
    material_kittings: list[MaterialKitting] = field(default_factory=list)
    process_dependencies: list[ProcessDependency] = field(default_factory=list)
    # V1 兼容字段
    workcenters: list[ProductionLine] = field(default_factory=list)  # alias
    items: list[DemandPlan] = field(default_factory=list)  # alias
    order_items: list[DemandPlan] = field(default_factory=list)  # alias
    orders: list[DemandPlan] = field(default_factory=list)  # alias
    process_routes: list[ProcessRoute] = field(default_factory=list)
    hard_rules: list[HardRule] = field(default_factory=list)
    soft_rules: list[SoftRule] = field(default_factory=list)
    objective_weights: dict[SoftRule, float] = field(default_factory=dict)
    changeover_rules: list[ChangeoverRule] = field(default_factory=list)
    soft_rule_weights: dict[str, float] = field(default_factory=dict)
    freeze_horizon: int = 0
    drum_workcenter_ids: list[str] = field(default_factory=list)
    solver_params: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 同步 production_lines ↔ workcenters
        if self.production_lines and not self.workcenters:
            self.workcenters = self.production_lines
        if self.workcenters and not self.production_lines:
            self.production_lines = self.workcenters
        # 同步 demand_plans ↔ order_items ↔ items ↔ orders
        if self.demand_plans and not self.order_items:
            self.order_items = self.demand_plans
        if self.order_items and not self.demand_plans:
            self.demand_plans = self.order_items
        if self.demand_plans and not self.items:
            self.items = self.demand_plans
        if self.items and not self.demand_plans:
            self.demand_plans = self.items
        if self.demand_plans and not self.orders:
            self.orders = self.demand_plans
        if self.orders and not self.demand_plans:
            self.demand_plans = self.orders


@dataclass
class SolveResult:
    """求解结果，求解器输出。"""
    status: SolveStatus = SolveStatus.INFEASIBLE
    tasks: list[ScheduledTask] = field(default_factory=list)
    objective_values: dict[str, float] = field(default_factory=dict)
    solve_time_seconds: float = 0.0
    solver_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    # 兼容字段（solver_ga 使用）
    fitness: float = 0.0
    hard_violations: int = 0
    generations: int = 0


@dataclass
class SolverCapabilities:
    """求解器能力声明。"""
    solver_name: str = ""
    supported_hard_rules: list[HardRule] = field(default_factory=list)
    supported_soft_rules: list[SoftRule] = field(default_factory=list)
    max_items: int = 0
    max_workcenters: int = 0
    max_time_slots: int = 0


class BaseSolver(ABC):
    """求解器基类，所有求解器必须实现此接口。"""

    @abstractmethod
    def solve(self, problem: SchedulingProblem) -> SolveResult:
        """输入统一的问题描述，输出统一的结果格式。"""

    @abstractmethod
    def get_capabilities(self) -> SolverCapabilities:
        """声明求解器能力。"""


# ── 评估 ──────────────────────────────────────────────────────────────────


@dataclass
class KPI:
    """关键指标。"""
    otd_rate: float = 0.0
    changeover_count: int = 0
    changeover_hours: float = 0.0
    drum_utilization: float = 0.0
    line_balance_rate: float = 0.0
    wip_level: float = 0.0
    total_output: float = 0.0

    def __sub__(self, other: KPI) -> KPI:
        return KPI(
            otd_rate=self.otd_rate - other.otd_rate,
            changeover_count=self.changeover_count - other.changeover_count,
            changeover_hours=self.changeover_hours - other.changeover_hours,
            drum_utilization=self.drum_utilization - other.drum_utilization,
            line_balance_rate=self.line_balance_rate - other.line_balance_rate,
            wip_level=self.wip_level - other.wip_level,
            total_output=self.total_output - other.total_output,
        )


@dataclass
class Violation:
    """硬规则违反。"""
    rule_name: str = ""
    task_id: str = ""
    detail: str = ""


@dataclass
class EvaluationResult:
    """评估结果。"""
    hard_violations: list[Violation] = field(default_factory=list)
    soft_scores: dict[str, float] = field(default_factory=dict)
    overall_score: float = 0.0
    kpi: KPI = field(default_factory=KPI)


@dataclass
class WhatIfEvent:
    """What-if 模拟事件。"""
    event_type: str = ""
    order_item: OrderItem | None = None
    workcenter_id: str = ""
    affected_slots: list[int] = field(default_factory=list)
    delay_hours: float = 0.0


@dataclass
class WhatIfResult:
    """What-if 模拟结果。"""
    original_score: float = 0.0
    simulated_score: float = 0.0
    score_delta: float = 0.0
    affected_orders: list[str] = field(default_factory=list)
    buffer_status: dict[str, str] = field(default_factory=dict)
    recommendation: str = ""


@dataclass
class CompareResult:
    """方案对比结果。"""
    plan_a_score: float = 0.0
    plan_b_score: float = 0.0
    kpi_diff: KPI = field(default_factory=KPI)
    winner: str = ""


# ── V1 兼容别名 ──────────────────────────────────────────────────────────
# 保留旧类名，避免其他模块大量报错
# 旧类（WorkCenter, WorkcenterInfo, Order, OrderItem, ProcessRoute, Material）
# 仍保留原始类定义，此处不再重复别名。

# V2 新类 → V1 旧名的别名（方便 V1 代码逐步迁移）
# 注意：WorkCenter 和 ProductionLine 是两个独立类，不做别名绑定
# 如需统一引用，建议使用 ProductionLine


