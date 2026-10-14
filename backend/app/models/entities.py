"""业务实体 ORM 模型，继承 SyncBase，使用 SQLAlchemy 2.0 mapped_column 风格。"""

from sqlalchemy import String, Integer, Float, Boolean, Date, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from .base import SyncBase


# ────────────────────────────────────────────
# 1. 产品主数据
# ────────────────────────────────────────────
class Product(SyncBase):
    __tablename__ = "products"

    prod_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True, comment="产品编码")
    prod_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="产品名称")
    prod_category: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="产品分类")
    prod_spec: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="产品规格")
    changeover_attr: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="换线属性")
    output_rate: Mapped[float | None] = mapped_column(Float, nullable=True, comment="出件率")
    batch_size: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="整批量")


# ────────────────────────────────────────────
# 2. 工艺信息
# ────────────────────────────────────────────
class ProcessInfo(SyncBase):
    __tablename__ = "process_info"

    proc_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True, comment="工序编码")
    proc_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="工序名称")
    proc_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="工序类型")
    constraint_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="约束类型")
    is_qc_point: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, comment="是否质检点")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="启用", index=True, comment="状态")


# ────────────────────────────────────────────
# 3. 产线
# ────────────────────────────────────────────
class ProductionLine(SyncBase):
    __tablename__ = "production_lines"

    line_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True, comment="产线编码")
    line_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="产线名称")
    line_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="产线类型")
    location: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="位置")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="启用", index=True, comment="状态")


# ────────────────────────────────────────────
# 4. 产品工艺
# ────────────────────────────────────────────
class ProductProcess(SyncBase):
    __tablename__ = "product_processes"

    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("products.id"), nullable=False, index=True, comment="关联产品")
    process_id: Mapped[str] = mapped_column(String(36), ForeignKey("process_info.id"), nullable=False, index=True, comment="关联工序")
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="工序顺序")
    auto_type: Mapped[str | None] = mapped_column(String(20), nullable=True, default="非自动", comment="工艺类型（自动/非自动）")
    cycle_time: Mapped[float | None] = mapped_column(Float, nullable=True, comment="节拍时间（秒）")
    max_units_per_beat: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1, comment="单节拍最大数量（自动工艺用，如治具数）")
    prep_time: Mapped[float | None] = mapped_column(Float, nullable=True, comment="准备时间（分钟）")
    wait_time: Mapped[float | None] = mapped_column(Float, nullable=True, comment="等待时间（分钟）")
    dependency_type: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="依赖类型")
    wait_includes_offhours: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, comment="下班时间是否可计入等待时间")
    is_key: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, comment="是否关键工序")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


# ────────────────────────────────────────────
# 5. 产线工艺配置
# ────────────────────────────────────────────
class LineProcessConfig(SyncBase):
    __tablename__ = "line_process_configs"

    lpc_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True, comment="独立编号")
    line_id: Mapped[str] = mapped_column(String(36), ForeignKey("production_lines.id"), nullable=False, index=True, comment="关联产线")
    process_id: Mapped[str] = mapped_column(String(36), ForeignKey("process_info.id"), nullable=False, index=True, comment="关联工序")
    auto_type: Mapped[str | None] = mapped_column(String(20), nullable=True, default="非自动", comment="工艺类型（自动/非自动）")
    is_bottleneck: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, comment="是否瓶颈")
    equipment_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="设备数量")
    worker_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="人员数量")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="启用", index=True, comment="状态")


# ────────────────────────────────────────────
# 6. 物料主数据
# ────────────────────────────────────────────
class MaterialMaster(SyncBase):
    __tablename__ = "material_masters"

    mat_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True, comment="物料编码")
    mat_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="物料名称")
    mat_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="物料类型")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="计量单位")
    safety_stock: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="安全库存")
    stock_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="库存数量")
    in_transit: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="在途数量")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="启用", index=True, comment="状态")


# ────────────────────────────────────────────
# 7. 工序BOM
# ────────────────────────────────────────────
class ProcessBOM(SyncBase):
    __tablename__ = "process_boms"

    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("products.id"), nullable=False, index=True, comment="关联产品")
    process_id: Mapped[str] = mapped_column(String(36), ForeignKey("process_info.id"), nullable=False, index=True, comment="关联工序")
    material_id: Mapped[str] = mapped_column(String(36), ForeignKey("material_masters.id"), nullable=False, index=True, comment="关联物料")
    unit_qty: Mapped[float | None] = mapped_column(Float, nullable=True, comment="单位用量")
    reusable: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False, comment="是否可复用")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


# ────────────────────────────────────────────
# 8. 物料齐套
# ────────────────────────────────────────────
class MaterialKitting(SyncBase):
    __tablename__ = "material_kittings"

    demand_id: Mapped[str] = mapped_column(String(36), ForeignKey("demand_plans.id"), nullable=False, index=True, comment="关联需求计划")
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("products.id"), nullable=False, index=True, comment="关联产品")
    process_id: Mapped[str] = mapped_column(String(36), ForeignKey("process_info.id"), nullable=False, index=True, comment="关联工序")
    material_id: Mapped[str] = mapped_column(String(36), ForeignKey("material_masters.id"), nullable=False, index=True, comment="关联物料")
    required_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="需求数量")
    available_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="可用数量")
    shortage_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="缺料数量")
    kitting_date: Mapped[str | None] = mapped_column(Date, nullable=True, index=True, comment="齐套日期")
    kitting_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True, comment="齐套状态")


# ────────────────────────────────────────────
# 9. 需求计划
# ────────────────────────────────────────────
class DemandPlan(SyncBase):
    __tablename__ = "demand_plans"

    dp_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True, comment="需求编码")
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("products.id"), nullable=False, index=True, comment="关联产品")
    quantity: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="需求数量")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="单位")
    due_date: Mapped[str | None] = mapped_column(Date, nullable=True, index=True, comment="交货日期")
    priority: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="优先级")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="待排", index=True, comment="状态")
    scheduled_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0, comment="已排数量")
    completed_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0, comment="已完成数量")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


# ────────────────────────────────────────────
# 10. 排产结果
# ────────────────────────────────────────────
class ScheduleResult(SyncBase):
    __tablename__ = "schedule_results"

    plan_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True, comment="关联排产方案编码")
    product_id: Mapped[str] = mapped_column(String(36), ForeignKey("products.id"), nullable=False, index=True, comment="关联产品")
    process_id: Mapped[str] = mapped_column(String(36), ForeignKey("process_info.id"), nullable=False, index=True, comment="关联工序")
    line_id: Mapped[str] = mapped_column(String(36), ForeignKey("production_lines.id"), nullable=False, index=True, comment="关联产线")
    demand_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("demand_plans.id"), nullable=True, index=True, comment="关联需求计划")
    pso_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("process_schedule_orders.id"), nullable=True, index=True, comment="关联工序排产单")
    pdp_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("process_delivery_plans.id"), nullable=True, index=True, comment="关联工序交付计划(V3.8)")
    sr_date: Mapped[str | None] = mapped_column(Date, nullable=True, index=True, comment="排产日期")
    sr_time_slot: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="时间段")
    sr_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="排产数量")
    sr_status: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True, comment="状态")
    process_code: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="工序编码（冗余）")
    constraint_type: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="约束类型（冗余）")
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="工序顺序")
    dependency_type: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="依赖类型")
    wait_time: Mapped[float | None] = mapped_column(Float, nullable=True, comment="等待时间")
    prep_time: Mapped[float | None] = mapped_column(Float, nullable=True, comment="准备时间")
    sr_completed_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0, comment="已完成数量")
    sr_unfinished_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="未完成数量")


# ────────────────────────────────────────────
# 11. 资源日历
# ────────────────────────────────────────────
class ResourceCalendar(SyncBase):
    __tablename__ = "resource_calendars"

    rc_code: Mapped[str] = mapped_column(String(100), nullable=False, comment="资源编码")
    rc_date: Mapped[str | None] = mapped_column(Date, nullable=True, index=True, comment="日期")
    rc_hour: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="小时时段")
    line_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("production_lines.id"), nullable=True, index=True, comment="关联产线")
    process_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("process_info.id"), nullable=True, index=True, comment="关联工序")
    available_capacity: Mapped[float | None] = mapped_column(Float, nullable=True, comment="可用产能")
    is_working: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=True, comment="是否工作时段")


# ────────────────────────────────────────────
# 12. 换线矩阵
# ────────────────────────────────────────────
class ChangeoverMatrix(SyncBase):
    __tablename__ = "changeover_matrices"

    from_product_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("products.id"), nullable=True, index=True, comment="源产品")
    to_product_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("products.id"), nullable=True, index=True, comment="目标产品")
    from_lpc_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("line_process_configs.id"), nullable=True, index=True, comment="源产线工艺配置")
    to_lpc_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("line_process_configs.id"), nullable=True, index=True, comment="目标产线工艺配置")
    changeover_type: Mapped[str | None] = mapped_column(String(20), nullable=True, default="产品换线", comment="换线类型（产品换线/产线切换）")
    setup_time: Mapped[float | None] = mapped_column(Float, nullable=True, comment="换线时间（分钟）")


# ────────────────────────────────────────────
# 13. 缓冲配置
# ────────────────────────────────────────────
class BufferConfig(SyncBase):
    __tablename__ = "buffer_configs"

    process_id: Mapped[str] = mapped_column(String(36), ForeignKey("process_info.id"), nullable=False, index=True, comment="关联工序")
    buffer_time: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="缓冲时间（分钟）")


# ────────────────────────────────────────────
# 14. 排产方案
# ────────────────────────────────────────────
class SchedulePlan(SyncBase):
    __tablename__ = "schedule_plans"

    sp_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="方案名称")
    sp_status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="草稿", index=True, comment="方案状态")
    sp_start_date: Mapped[str | None] = mapped_column(Date, nullable=True, comment="排产开始日期")
    sp_end_date: Mapped[str | None] = mapped_column(Date, nullable=True, comment="排产结束日期")
    sp_solver: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="求解器类型")
    sp_solve_status: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="求解状态")
    sp_solve_time: Mapped[float | None] = mapped_column(Float, nullable=True, comment="求解耗时（秒）")
    sp_task_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="任务数量")
    sp_total_output: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="总产量")


# ────────────────────────────────────────────
# 15. 报工工单
# ────────────────────────────────────────────
class ReportWorkOrder(SyncBase):
    __tablename__ = "report_work_orders"

    rw_code: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True, comment="报工单编号")
    dispatch_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("schedule_results.id"), nullable=True, index=True, comment="关联派工单")
    product_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("products.id"), nullable=True, index=True, comment="关联产品")
    process_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("process_info.id"), nullable=True, index=True, comment="关联工序")
    line_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("production_lines.id"), nullable=True, index=True, comment="关联产线")
    rw_date: Mapped[str | None] = mapped_column(Date, nullable=True, index=True, comment="报工日期")
    rw_time_slot: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="报工时段")
    rw_plan_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="计划数量")
    rw_actual_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="实际完成数量")
    rw_defect_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0, comment="不良数量")
    rw_status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="待报工", index=True, comment="报工状态")
    rw_remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


# ────────────────────────────────────────────
# 16. 工序排产单
# ────────────────────────────────────────────
class ProcessScheduleOrder(SyncBase):
    """工序计划单：跟踪每道工序的计划、排产和完成情况（工序级唯一）。

    V3.9.3: 重命名自"工序排产单"，改为工序级唯一（每需求×工序一条）。
    - planned_qty（计划数量）= 需求计划中产品的需求数量，排产时写入，固定不变
    - pso_quantity（排产数量）= 该工序所有派工单（ScheduleResult）排产数量之和，派工时累加
    - pso_completed_qty（已完成数量）= 报工时累加
    - pso_unfinished_qty（未完成数量）= planned_qty - pso_completed_qty
    派工单（ScheduleResult）作为工序计划单的执行记录，一对多关系。
    """
    __tablename__ = "process_schedule_orders"

    pso_code: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True, index=True, comment="工序计划单编号(PSO-YYYYMMDD-序号)")
    demand_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("demand_plans.id"), nullable=True, index=True, comment="关联需求计划")
    product_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("products.id"), nullable=True, index=True, comment="关联产品")
    process_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("process_info.id"), nullable=True, index=True, comment="关联工序")
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="工序顺序")
    line_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("production_lines.id"), nullable=True, index=True, comment="关联产线（工序级汇总，可能为空）")
    prev_pso_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True, comment="前道工序计划单ID")
    plan_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True, comment="关联排产方案编码")
    pso_date: Mapped[str | None] = mapped_column(Date, nullable=True, index=True, comment="首次排产日期")
    pso_time_slot: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="时间段（工序级汇总，可能为空）")
    planned_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="计划数量(=需求计划需求数量，固定不变)")
    pso_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="排产数量(=该工序所有派工单排产数量之和)")
    pso_completed_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0, comment="已完成数量（报工时累加）")
    pso_unfinished_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="未完成数量(=计划数量-已完成数量)")
    pso_status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="待排产", index=True, comment="状态(待排产/已排产/报工中/已完成/已失效)")
    dependency_type: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="依赖类型(FS/SS/FF/SF)")
    wait_time: Mapped[float | None] = mapped_column(Float, nullable=True, comment="等待时间(分钟)")


# ────────────────────────────────────────────
# 16.1 工序交付计划（V3.8 新增）
# ────────────────────────────────────────────
class ProcessDeliveryPlan(SyncBase):
    """工序交付计划：持久化的工序级别计划，记录各工序的计划和完成情况。

    与 process_schedule_orders（工序排产单）的区别：
    - 工序交付计划是持久化的，日终不清理，记录工序的整体计划和完成进度
    - 工序排产单是每次排产的结果，日终会清理未报工的

    数据流：
    - 首次排产时生成，planned_qty=需求数量
    - 排产单（schedule_results）关联到工序交付计划（一对多）
    - 报工时累计更新 completed_qty
    - 当 completed_qty=planned_qty 时，更新 planned_finish_time
    - 最后一道工序完成时，反馈到 demand_plans.completed_qty
    """
    __tablename__ = "process_delivery_plans"

    pdp_code: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True, index=True, comment="工序交付计划编号(PDP-YYYYMMDD-序号)")
    demand_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("demand_plans.id"), nullable=True, index=True, comment="关联需求计划")
    product_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("products.id"), nullable=True, index=True, comment="关联产品")
    process_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("process_info.id"), nullable=True, index=True, comment="关联工序")
    seq: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="工序顺序")
    line_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("production_lines.id"), nullable=True, index=True, comment="关联产线")
    prev_pdp_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True, comment="前道工序交付计划ID（在制品流转）")
    plan_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True, comment="关联排产方案编码")

    planned_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="计划数量(=需求数量)")
    completed_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0, comment="已完成数量（报工时累计更新）")
    unfinished_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="未完成数量")

    # V3.8: 计划开始时间=有派工的第一天，计划完成时间=completed_qty=planned_qty的当天
    planned_start_time: Mapped[str | None] = mapped_column(Date, nullable=True, index=True, comment="计划开始时间（有派工的第一天）")
    planned_finish_time: Mapped[str | None] = mapped_column(Date, nullable=True, index=True, comment="计划完成时间（completed_qty=planned_qty的当天）")

    pdp_status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="待排产", index=True, comment="状态(待排产/排产中/已完成)")
    dependency_type: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="依赖类型(FS/SS/FF/SF)")
    wait_time: Mapped[float | None] = mapped_column(Float, nullable=True, comment="等待时间(分钟)")


# ────────────────────────────────────────────
# 17. 工作时间模式（V3.9 新增）
# ────────────────────────────────────────────
class WorkTimePattern(SyncBase):
    """工作时间模式：定义不同日期类型的工作时间和休息时间。

    V3.9: 替代硬编码的8:00-20:00工作时间，支持灵活配置。
    - 周一到周五：8小时（常规）/ 10小时（加班）
    - 周六周日：7小时
    - 午休：11:45-12:45
    - 晚饭（加班时）：14:30-15:00

    work_periods: JSON 格式的工作时段
      [{"start": "08:00", "end": "11:45"}, {"start": "12:45", "end": "17:15"}]
    break_periods: JSON 格式的休息时段
      [{"start": "11:45", "end": "12:45", "type": "lunch"}]
    """
    __tablename__ = "work_time_patterns"

    pattern_code: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True, index=True, comment="模式编号")
    pattern_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="模式名称")
    day_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True, comment="日期类型: weekday_normal/weekday_overtime/weekend")
    work_hours: Mapped[float | None] = mapped_column(Float, nullable=True, comment="每日工时(小时)")
    slot_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True, default=15, comment="时间槽粒度(分钟)")

    # 工作时段和休息时段（JSON 字符串）
    work_periods: Mapped[str | None] = mapped_column(Text, nullable=True, comment="工作时段JSON: [{start,end},...]")
    break_periods: Mapped[str | None] = mapped_column(Text, nullable=True, comment="休息时段JSON: [{start,end,type},...]")
    description: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="描述")
    is_active: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=True, comment="是否启用")


# ────────────────────────────────────────────
# 18. 系统配置
# ────────────────────────────────────────────
class SystemConfig(Base):
    __tablename__ = "system_config"

    key: Mapped[str] = mapped_column(String(100), primary_key=True, comment="配置键")
    value: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="配置值")
