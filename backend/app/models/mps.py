"""MPS 封测业务数据模型（新业务核心表）。

- 全部继承 SyncBase：id/hap_row_id/sync_status/synced_at/created_at/updated_at
- 与旧计划类表互不冲突（旧表在后续计划中被替换，数据可删）
"""
from datetime import date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import SyncBase


class ProcessMaster(SyncBase):
    """工序主数据（级别|工序|模式 唯一）。"""

    __tablename__ = "process_masters"
    __table_args__ = (UniqueConstraint("level", "op", "mode", name="uq_process_master"),)

    level: Mapped[str] = mapped_column(String(20), comment="产品级别（芯片级/模块级/组件级）")
    op: Mapped[str] = mapped_column(String(50), comment="工序名称（规范名）")
    mode: Mapped[str] = mapped_column(String(20), default="/", comment="生产模式（半自动/自动//）")
    cycle: Mapped[float] = mapped_column(Float, default=1, comment="基准装配周期（天）")
    yield_assembly: Mapped[float | None] = mapped_column(Float, nullable=True, comment="一次装配合格率（存档）")
    yield_inspect: Mapped[float | None] = mapped_column(Float, nullable=True, comment="一次检验合格率（存档）")
    yield_overall: Mapped[float | None] = mapped_column(Float, nullable=True, comment="综合成品率（纳入计算）")
    cap_station: Mapped[float | None] = mapped_column(Float, nullable=True, comment="单工位日产能")
    stations: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="工位数")
    flux_base: Mapped[float | None] = mapped_column(Float, nullable=True, comment="基准均值通量（单工位产能×工位数）")
    flux_peak: Mapped[float | None] = mapped_column(Float, nullable=True, comment="基准峰值通量（均值×峰值系数）")
    unit: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="核算单位（如 颗/天，植球数N_b）")
    feature: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="特征参数名（如 N_b）")
    split_rule: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="分流规则说明")
    split_threshold: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="分流阈值（只）")
    cycle_note: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="周期调节说明")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class ProcessSet(SyncBase):
    """成套工艺主数据（工艺代号唯一，24 套 D01~C11）。"""

    __tablename__ = "process_sets"

    code: Mapped[str] = mapped_column(String(50), unique=True, comment="工艺代号（含版本，主键含义）")
    form: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="产品形态")
    arch: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="封装架构")
    name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="成套工艺名称")
    feature: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="特征说明")
    version: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="版本号")
    route_text: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="路线原文")
    owner: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="负责人")
    yield_ref: Mapped[float | None] = mapped_column(Float, nullable=True, comment="成品率（汇总）")
    ratio_ref: Mapped[float | None] = mapped_column(Float, nullable=True, comment="装配放量比")
    cycle_ref: Mapped[float | None] = mapped_column(Float, nullable=True, comment="单件装配周期（天）")
    urgent_ref: Mapped[float | None] = mapped_column(Float, nullable=True, comment="加急单件周期（天）")
    required_flags: Mapped[list | None] = mapped_column(JSON, nullable=True, comment="特征参数适用标记")
    subpart_mode: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="分部件模式（前置/平行/空）")
    subpart_cycle: Mapped[float | None] = mapped_column(Float, nullable=True, comment="分部件装配周期（天）")
    ramp_days: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="爬坡时间（天）")
    bottleneck_op: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="瓶颈工序（取小结果）")
    bottleneck_flux: Mapped[float | None] = mapped_column(Float, nullable=True, comment="瓶颈通量")
    water_note: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="水汽要求说明")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="启用", comment="状态")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class ProcessRoute(SyncBase):
    """工艺路线（工艺代号×工序序号 唯一，共 ~133 行）。"""

    __tablename__ = "process_routes"
    __table_args__ = (UniqueConstraint("code", "seq", name="uq_route_code_seq"),)

    code: Mapped[str] = mapped_column(String(50), comment="工艺代号")
    seq: Mapped[int] = mapped_column(Integer, comment="工序序号")
    step_raw: Mapped[str] = mapped_column(String(50), comment="工序原文名")
    step_std: Mapped[str] = mapped_column(String(50), comment="规范工序名")
    level: Mapped[str] = mapped_column(String(20), comment="适用级别")
    cycle: Mapped[float | None] = mapped_column(Float, nullable=True, comment="工序装配周期（天）")
    yield_inspect: Mapped[float | None] = mapped_column(Float, nullable=True, comment="一次检验合格率")
    yield_overall: Mapped[float | None] = mapped_column(Float, nullable=True, comment="综合成品率")
    feature: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="核算特征（如 植球-球数N_b）")
    cf_field: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="折算系数来源（DB胶水/WB引线//）")
    cf_trigger: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="触发条件")
    note: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")


class Order(SyncBase):
    """工单（产品需求）：基础字段 + 优先级引擎字段 + 核算结果回写字段。"""

    __tablename__ = "orders"

    order_no: Mapped[str] = mapped_column(String(50), unique=True, comment="订单号")
    product: Mapped[str] = mapped_column(String(100), comment="产品型号")
    code: Mapped[str] = mapped_column(String(50), comment="工艺代号")
    order_type: Mapped[str] = mapped_column(String(10), default="常规", comment="订单类型（常规/加急）")
    first_flag: Mapped[str] = mapped_column(String(20), default="否", comment="首单/复线/变更首件/否")
    water_vapor: Mapped[str] = mapped_column(String(10), default="无", comment="水汽含量要求（有/无）")
    qty: Mapped[int] = mapped_column(Integer, comment="计划批量（只）")
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="订单需求日期")
    kit_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="物料齐套时间")
    priority: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="排产优先级（越小越优先，0=置顶）")
    features: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="BOM 特征（13+2 项）")
    remark: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="正常", comment="状态（正常/暂停/取消/完成）")

    prio_level: Mapped[str | None] = mapped_column(String(5), nullable=True, comment="优先级级别（P0~P3）")
    prio_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="6 因子评分")
    prio_source: Mapped[str | None] = mapped_column(String(10), nullable=True, comment="来源（auto/manual/pin）")
    prio_manual: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="手工指定优先级")
    pinned: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否置顶")
    pinned_until: Mapped[date | None] = mapped_column(Date, nullable=True, comment="置顶失效日期")
    pinned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="置顶时间")
    pinned_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="置顶操作人")
    sort_no: Mapped[float | None] = mapped_column(Float, nullable=True, comment="拖拽排序序号")
    prio_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, comment="优先级更新时间")
    prio_updated_by: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="优先级更新人")

    input_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="投料量（核算结果）")
    yield_ratio: Mapped[float | None] = mapped_column(Float, nullable=True, comment="装配放量比（核算结果）")
    y_full: Mapped[float | None] = mapped_column(Float, nullable=True, comment="成品率链乘积（核算结果）")
    cycle_single: Mapped[float | None] = mapped_column(Float, nullable=True, comment="单件周期-采用值（核算结果）")
    cycle_batch: Mapped[float | None] = mapped_column(Float, nullable=True, comment="批量总装配周期（核算结果）")
    adopted_flux: Mapped[float | None] = mapped_column(Float, nullable=True, comment="采用通量（核算结果）")
    bottleneck_op: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="瓶颈工序（核算结果）")
    ramp_applied: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="实际计入爬坡（天）")
    delivery_cycle: Mapped[float | None] = mapped_column(Float, nullable=True, comment="交付周期（核算结果）")
    latest_start_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="最晚投料日（核算结果）")
    plan_start_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="排产开始日")
    plan_finish_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="排产完成日")
    gap_days: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="交期余量（天）")
    judge: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="交付判定（满足/零裕量/延期/无交期）")
    strategy_id: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="采用策略")


class OrderOperation(SyncBase):
    """工序级需求：产品工单按路线自动分解；支持手工追加（返工/试制插入工序）。"""

    __tablename__ = "order_operations"

    order_id: Mapped[str] = mapped_column(String(36), comment="工单 ID")
    seq: Mapped[int] = mapped_column(Integer, comment="工序序号")
    level: Mapped[str] = mapped_column(String(20), comment="级别")
    op: Mapped[str] = mapped_column(String(50), comment="规范工序名")
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="生产模式（排产时按批量分流判定）")
    qty: Mapped[float | None] = mapped_column(Float, nullable=True, comment="工序级数量")
    unit: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="数量单位")
    feature_key: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="特征参数键（如 N_die）")
    feature_usage: Mapped[float | None] = mapped_column(Float, nullable=True, comment="单只特征用量（负荷计算用）")
    source: Mapped[str] = mapped_column(String(10), default="auto", comment="来源（auto=路线分解/manual=手工追加）")
    depends_on_id: Mapped[str | None] = mapped_column(String(36), nullable=True, comment="前道工序需求 ID（工序间约束）")
    note: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="备注（返工/试制原因等）")


class SystemParam(SyncBase):
    """系统参数（可配置；种子只补缺失、不覆盖用户已改值）。"""

    __tablename__ = "system_params"

    key: Mapped[str] = mapped_column(String(100), unique=True, comment="参数键")
    value: Mapped[str | None] = mapped_column(Text, nullable=True, comment="参数值（字符串/JSON）")
    label: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="显示名")
    group_name: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="分组")
    hint: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="说明")


class ScheduleBatch(SyncBase):
    """排产批次（一次求解的头部记录）。"""

    __tablename__ = "schedule_batches"

    batch_no: Mapped[str] = mapped_column(String(50), unique=True, comment="批次号")
    base_date: Mapped[date | None] = mapped_column(Date, nullable=True, comment="排产基准日期")
    solver_mode: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="GA/cp_sat/deterministic")
    strategy_id: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="策略 ID")
    params_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="参数快照")
    kpi: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="KPI 汇总")
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, default="完成", comment="状态")


class ScheduleAllocation(SyncBase):
    """排产分配明细（工序级需求 × 资源 × 日期 × 数量）。"""

    __tablename__ = "schedule_allocations"

    batch_id: Mapped[str] = mapped_column(String(36), comment="排产批次 ID")
    order_id: Mapped[str] = mapped_column(String(36), comment="工单 ID")
    operation_id: Mapped[str | None] = mapped_column(String(36), nullable=True, comment="工序级需求 ID")
    resource_key: Mapped[str] = mapped_column(String(100), comment="资源（级别|工序|模式）")
    work_date: Mapped[date] = mapped_column(Date, comment="分配日期")
    qty: Mapped[float] = mapped_column(Float, comment="分配数量")


class PriorityLog(SyncBase):
    """优先级变更审计日志（移植 mps-web priority_log 口径）。"""

    __tablename__ = "priority_logs"

    order_id: Mapped[str] = mapped_column(String(36), comment="工单 ID")
    order_no: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="订单号（冗余）")
    action: Mapped[str] = mapped_column(String(20), comment="动作（recompute/pin/unpin/reorder）")
    old_priority: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="原优先级")
    new_priority: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="新优先级")
    old_level: Mapped[str | None] = mapped_column(String(5), nullable=True, comment="原级别")
    new_level: Mapped[str | None] = mapped_column(String(5), nullable=True, comment="新级别")
    old_sort_no: Mapped[float | None] = mapped_column(Float, nullable=True, comment="原拖拽序")
    new_sort_no: Mapped[float | None] = mapped_column(Float, nullable=True, comment="新拖拽序")
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="原因")
    operator: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="操作人")
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True, comment="批量操作批次 ID")
    undo_of: Mapped[str | None] = mapped_column(String(36), nullable=True, comment="撤销对应的日志 ID")


class PriorityBatch(SyncBase):
    """优先级批量操作快照（撤销用）。"""

    __tablename__ = "priority_batches"

    batch_id: Mapped[str] = mapped_column(String(36), unique=True, comment="批次 ID")
    action: Mapped[str] = mapped_column(String(20), comment="动作")
    item_count: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="条目数")
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="变更快照")
    operator: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="操作人")
    undone: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否已撤销")


class HapConnection(SyncBase):
    """明道云连接配置（密钥加密存储，API 永不回显）。"""

    __tablename__ = "hap_connections"

    base_url: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="明道云地址")
    app_id: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="App ID")
    app_key_enc: Mapped[str | None] = mapped_column(Text, nullable=True, comment="AppKey（加密）")
    sign_enc: Mapped[str | None] = mapped_column(Text, nullable=True, comment="Sign（加密）")


class HapMapping(SyncBase):
    """实体→表单映射。"""

    __tablename__ = "hap_mappings"

    entity: Mapped[str] = mapped_column(String(50), unique=True, comment="业务实体 key（order/process_master/...）")
    ws_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="明道云表单 ID")
    sync_direction: Mapped[str] = mapped_column(String(20), default="pull", comment="同步方向（pull/push/both）")
    enabled: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否启用")


class HapFieldMapping(SyncBase):
    """字段级映射（本地字段 ↔ 明道云控件）。"""

    __tablename__ = "hap_field_mappings"
    __table_args__ = (UniqueConstraint("entity", "local_field", name="uq_hap_field_mapping"),)

    entity: Mapped[str] = mapped_column(String(50), comment="业务实体 key")
    local_field: Mapped[str] = mapped_column(String(50), comment="本地字段名")
    hap_field_id: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="明道云控件 ID")
    hap_field_name: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="明道云字段名")
    field_type: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="类型（str/int/float/date/option/bool/relation）")
    option_map: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="选项值映射")
    relation: Mapped[dict | None] = mapped_column(JSON, nullable=True, comment="关联配置")
    auto_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="自动匹配置信度")
    manual_override: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否手工调整过")
