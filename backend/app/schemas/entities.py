"""14张业务表的 Pydantic V2 Schema，用于 CRUD API 请求/响应。"""

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, ConfigDict


# ── 通用基类 ──────────────────────────────────────────────────────────────

class SyncBaseSchema(BaseModel):
    """同步基类字段（所有表共有）。"""
    id: str
    hap_row_id: str | None = None
    sync_status: str | None = None
    synced_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class PaginationParams(BaseModel):
    """分页参数。"""
    skip: int = Field(default=0, ge=0, description="跳过记录数")
    limit: int = Field(default=100, ge=1, le=1000, description="每页记录数")


class PaginatedResponse(BaseModel):
    """分页响应。"""
    items: list[Any] = Field(default_factory=list)
    total: int = Field(default=0)
    skip: int = Field(default=0)
    limit: int = Field(default=100)


# ── 1. 产品主数据 ────────────────────────────────────────────────────────

class ProductCreate(BaseModel):
    prod_code: str = Field(..., description="产品编码")
    prod_name: str = Field(..., description="产品名称")
    prod_category: str | None = None
    prod_spec: str | None = None
    changeover_attr: str | None = None
    output_rate: float | None = None
    batch_size: int | None = None


class ProductUpdate(BaseModel):
    prod_code: str | None = None
    prod_name: str | None = None
    prod_category: str | None = None
    prod_spec: str | None = None
    changeover_attr: str | None = None
    output_rate: float | None = None
    batch_size: int | None = None


class ProductOut(SyncBaseSchema):
    prod_code: str
    prod_name: str
    prod_category: str | None = None
    prod_spec: str | None = None
    changeover_attr: str | None = None
    output_rate: float | None = None
    batch_size: int | None = None


# ── 2. 工序信息 ──────────────────────────────────────────────────────────

class ProcessInfoCreate(BaseModel):
    proc_code: str = Field(..., description="工序编码")
    proc_name: str = Field(..., description="工序名称")
    proc_type: str | None = None
    constraint_type: str | None = None
    cycle_time: float | None = None
    setup_time: float | None = None
    wait_time: float | None = None
    wait_includes_offhours: bool | None = None
    prep_time: float | None = None
    is_qc_point: bool | None = None
    status: str | None = None


class ProcessInfoUpdate(BaseModel):
    proc_code: str | None = None
    proc_name: str | None = None
    proc_type: str | None = None
    constraint_type: str | None = None
    cycle_time: float | None = None
    setup_time: float | None = None
    wait_time: float | None = None
    wait_includes_offhours: bool | None = None
    prep_time: float | None = None
    is_qc_point: bool | None = None
    status: str | None = None


class ProcessInfoOut(SyncBaseSchema):
    proc_code: str
    proc_name: str
    proc_type: str | None = None
    constraint_type: str | None = None
    cycle_time: float | None = None
    setup_time: float | None = None
    wait_time: float | None = None
    wait_includes_offhours: bool | None = None
    prep_time: float | None = None
    is_qc_point: bool | None = None
    status: str | None = None


# ── 3. 产线 ──────────────────────────────────────────────────────────────

class ProductionLineCreate(BaseModel):
    line_code: str = Field(..., description="产线编码")
    line_name: str = Field(..., description="产线名称")
    line_type: str | None = None
    daily_capacity: int | None = None
    efficiency: float | None = None
    location: str | None = None
    status: str | None = None


class ProductionLineUpdate(BaseModel):
    line_code: str | None = None
    line_name: str | None = None
    line_type: str | None = None
    daily_capacity: int | None = None
    efficiency: float | None = None
    location: str | None = None
    status: str | None = None


class ProductionLineOut(SyncBaseSchema):
    line_code: str
    line_name: str
    line_type: str | None = None
    daily_capacity: int | None = None
    efficiency: float | None = None
    location: str | None = None
    status: str | None = None


# ── 4. 产品工艺 ──────────────────────────────────────────────────────────

class ProductProcessCreate(BaseModel):
    product_id: str = Field(..., description="关联产品ID")
    process_id: str = Field(..., description="关联工序ID")
    seq: int | None = None
    auto_type: str | None = None
    cycle_time: float | None = None
    max_units_per_beat: int | None = None
    prep_time: float | None = None
    wait_time: float | None = None
    dependency_type: str | None = None
    is_key: bool | None = None
    remark: str | None = None


class ProductProcessUpdate(BaseModel):
    product_id: str | None = None
    process_id: str | None = None
    seq: int | None = None
    auto_type: str | None = None
    cycle_time: float | None = None
    max_units_per_beat: int | None = None
    prep_time: float | None = None
    wait_time: float | None = None
    dependency_type: str | None = None
    is_key: bool | None = None
    remark: str | None = None


class ProductProcessOut(SyncBaseSchema):
    product_id: str
    process_id: str
    seq: int | None = None
    auto_type: str | None = None
    cycle_time: float | None = None
    max_units_per_beat: int | None = None
    prep_time: float | None = None
    wait_time: float | None = None
    dependency_type: str | None = None
    is_key: bool | None = None
    remark: str | None = None


# ── 5. 产线工艺配置 ──────────────────────────────────────────────────────

class LineProcessConfigCreate(BaseModel):
    lpc_code: str | None = None
    line_id: str = Field(..., description="关联产线ID")
    process_id: str = Field(..., description="关联工序ID")
    auto_type: str | None = None
    is_bottleneck: bool | None = None
    equipment_count: int | None = None
    worker_count: int | None = None
    status: str | None = None


class LineProcessConfigUpdate(BaseModel):
    lpc_code: str | None = None
    line_id: str | None = None
    process_id: str | None = None
    auto_type: str | None = None
    is_bottleneck: bool | None = None
    equipment_count: int | None = None
    worker_count: int | None = None
    status: str | None = None


class LineProcessConfigOut(SyncBaseSchema):
    lpc_code: str | None = None
    line_id: str
    process_id: str
    auto_type: str | None = None
    is_bottleneck: bool | None = None
    equipment_count: int | None = None
    worker_count: int | None = None
    status: str | None = None


# ── 6. 物料主数据 ────────────────────────────────────────────────────────

class MaterialMasterCreate(BaseModel):
    mat_code: str = Field(..., description="物料编码")
    mat_name: str = Field(..., description="物料名称")
    mat_type: str | None = None
    unit: str | None = None
    safety_stock: int | None = None
    stock_qty: int | None = None
    in_transit: int | None = None
    status: str | None = None


class MaterialMasterUpdate(BaseModel):
    mat_code: str | None = None
    mat_name: str | None = None
    mat_type: str | None = None
    unit: str | None = None
    safety_stock: int | None = None
    stock_qty: int | None = None
    in_transit: int | None = None
    status: str | None = None


class MaterialMasterOut(SyncBaseSchema):
    mat_code: str
    mat_name: str
    mat_type: str | None = None
    unit: str | None = None
    safety_stock: int | None = None
    stock_qty: int | None = None
    in_transit: int | None = None
    status: str | None = None


# ── 7. 工序BOM ───────────────────────────────────────────────────────────

class ProcessBOMCreate(BaseModel):
    product_id: str = Field(..., description="关联产品ID")
    process_id: str = Field(..., description="关联工序ID")
    material_id: str = Field(..., description="关联物料ID")
    unit_qty: float | None = None
    reusable: bool | None = None
    remark: str | None = None


class ProcessBOMUpdate(BaseModel):
    product_id: str | None = None
    process_id: str | None = None
    material_id: str | None = None
    unit_qty: float | None = None
    reusable: bool | None = None
    remark: str | None = None


class ProcessBOMOut(SyncBaseSchema):
    product_id: str
    process_id: str
    material_id: str
    unit_qty: float | None = None
    reusable: bool | None = None
    remark: str | None = None


# ── 8. 物料齐套 ──────────────────────────────────────────────────────────

class MaterialKittingCreate(BaseModel):
    demand_id: str = Field(..., description="关联需求计划ID")
    product_id: str = Field(..., description="关联产品ID")
    process_id: str = Field(..., description="关联工序ID")
    material_id: str = Field(..., description="关联物料ID")
    required_qty: int | None = None
    available_qty: int | None = None
    shortage_qty: int | None = None
    kitting_date: date | None = None
    kitting_status: str | None = None


class MaterialKittingUpdate(BaseModel):
    demand_id: str | None = None
    product_id: str | None = None
    process_id: str | None = None
    material_id: str | None = None
    required_qty: int | None = None
    available_qty: int | None = None
    shortage_qty: int | None = None
    kitting_date: date | None = None
    kitting_status: str | None = None


class MaterialKittingOut(SyncBaseSchema):
    demand_id: str
    product_id: str
    process_id: str
    material_id: str
    required_qty: int | None = None
    available_qty: int | None = None
    shortage_qty: int | None = None
    kitting_date: date | None = None
    kitting_status: str | None = None


# ── 9. 需求计划 ──────────────────────────────────────────────────────────

class DemandPlanCreate(BaseModel):
    dp_code: str = Field(..., description="需求编码")
    product_id: str = Field(..., description="关联产品ID")
    quantity: int | None = None
    unit: str | None = None
    due_date: date | None = None
    priority: str | None = None
    status: str | None = None
    scheduled_qty: int | None = None
    completed_qty: int | None = None
    remark: str | None = None


class DemandPlanUpdate(BaseModel):
    dp_code: str | None = None
    product_id: str | None = None
    quantity: int | None = None
    unit: str | None = None
    due_date: date | None = None
    priority: str | None = None
    status: str | None = None
    scheduled_qty: int | None = None
    completed_qty: int | None = None
    remark: str | None = None


class DemandPlanOut(SyncBaseSchema):
    dp_code: str
    product_id: str
    quantity: int | None = None
    unit: str | None = None
    due_date: date | None = None
    priority: str | None = None
    status: str | None = None
    scheduled_qty: int | None = None
    completed_qty: int | None = None
    remark: str | None = None


# ── 10. 排产结果 ─────────────────────────────────────────────────────────

class ScheduleResultCreate(BaseModel):
    plan_id: str | None = None
    product_id: str | None = None
    process_id: str | None = None
    line_id: str | None = None
    demand_id: str | None = None
    sr_date: date | None = None
    sr_time_slot: str | None = None
    sr_quantity: int | None = None
    sr_status: str | None = None
    sr_completed_qty: int | None = 0
    sr_unfinished_qty: int | None = None
    process_code: str | None = None
    constraint_type: str | None = None
    seq: int | None = None
    dependency_type: str | None = None
    wait_time: float | None = None
    prep_time: float | None = None


class ScheduleResultUpdate(BaseModel):
    plan_id: str | None = None
    product_id: str | None = None
    process_id: str | None = None
    line_id: str | None = None
    demand_id: str | None = None
    sr_date: date | None = None
    sr_time_slot: str | None = None
    sr_quantity: int | None = None
    sr_status: str | None = None
    sr_completed_qty: int | None = 0
    sr_unfinished_qty: int | None = None
    process_code: str | None = None
    constraint_type: str | None = None
    seq: int | None = None
    dependency_type: str | None = None
    wait_time: float | None = None
    prep_time: float | None = None


class ScheduleResultOut(SyncBaseSchema):
    plan_id: str | None = None
    product_id: str | None = None
    process_id: str | None = None
    line_id: str | None = None
    demand_id: str | None = None
    sr_date: date | None = None
    sr_time_slot: str | None = None
    sr_quantity: int | None = None
    sr_status: str | None = None
    sr_completed_qty: int | None = 0
    sr_unfinished_qty: int | None = None
    process_code: str | None = None
    constraint_type: str | None = None
    seq: int | None = None
    dependency_type: str | None = None
    wait_time: float | None = None
    prep_time: float | None = None


# ── 11. 资源日历 ─────────────────────────────────────────────────────────

class ResourceCalendarCreate(BaseModel):
    rc_code: str = Field(..., description="资源编码")
    rc_date: date | None = None
    rc_hour: int | None = None
    line_id: str | None = None
    process_id: str | None = None
    available_capacity: float | None = None
    is_working: bool | None = None


class ResourceCalendarUpdate(BaseModel):
    rc_code: str | None = None
    rc_date: date | None = None
    rc_hour: int | None = None
    line_id: str | None = None
    process_id: str | None = None
    available_capacity: float | None = None
    is_working: bool | None = None


class ResourceCalendarOut(SyncBaseSchema):
    rc_code: str
    rc_date: date | None = None
    rc_hour: int | None = None
    line_id: str | None = None
    process_id: str | None = None
    available_capacity: float | None = None
    is_working: bool | None = None


# ── 12. 换线矩阵 ────────────────────────────────────────────────────────

class ChangeoverMatrixCreate(BaseModel):
    from_product_id: str | None = None
    to_product_id: str | None = None
    from_lpc_id: str | None = None
    to_lpc_id: str | None = None
    changeover_type: str | None = None
    setup_time: float | None = None


class ChangeoverMatrixUpdate(BaseModel):
    from_product_id: str | None = None
    to_product_id: str | None = None
    from_lpc_id: str | None = None
    to_lpc_id: str | None = None
    changeover_type: str | None = None
    setup_time: float | None = None


class ChangeoverMatrixOut(SyncBaseSchema):
    from_product_id: str | None = None
    to_product_id: str | None = None
    from_lpc_id: str | None = None
    to_lpc_id: str | None = None
    changeover_type: str | None = None
    setup_time: float | None = None


# ── 13. 缓冲配置 ────────────────────────────────────────────────────────

class BufferConfigCreate(BaseModel):
    process_id: str = Field(..., description="关联工序ID")
    buffer_time: int | None = None


class BufferConfigUpdate(BaseModel):
    process_id: str | None = None
    buffer_time: int | None = None


class BufferConfigOut(SyncBaseSchema):
    process_id: str
    buffer_time: int | None = None


# ── 14. 排产方案 ────────────────────────────────────────────────────────

class SchedulePlanCreate(BaseModel):
    sp_name: str = Field(..., description="方案名称")
    sp_status: str | None = None
    sp_start_date: date | None = None
    sp_end_date: date | None = None
    sp_solver: str | None = None
    sp_solve_status: str | None = None
    sp_solve_time: float | None = None
    sp_task_count: int | None = None
    sp_total_output: int | None = None


class SchedulePlanUpdate(BaseModel):
    sp_name: str | None = None
    sp_status: str | None = None
    sp_start_date: date | None = None
    sp_end_date: date | None = None
    sp_solver: str | None = None
    sp_solve_status: str | None = None
    sp_solve_time: float | None = None
    sp_task_count: int | None = None
    sp_total_output: int | None = None


class SchedulePlanOut(SyncBaseSchema):
    sp_name: str
    sp_status: str | None = None
    sp_start_date: date | None = None
    sp_end_date: date | None = None
    sp_solver: str | None = None
    sp_solve_status: str | None = None
    sp_solve_time: float | None = None
    sp_task_count: int | None = None
    sp_total_output: int | None = None


# ── 15. 报工工单 ────────────────────────────────────────────────────────

class ReportWorkOrderCreate(BaseModel):
    rw_code: str | None = None
    dispatch_id: str | None = None
    product_id: str | None = None
    process_id: str | None = None
    line_id: str | None = None
    rw_date: date | None = None
    rw_time_slot: str | None = None
    rw_plan_qty: int | None = None
    rw_actual_qty: int | None = None
    rw_defect_qty: int | None = None
    rw_status: str | None = None
    rw_remark: str | None = None


class ReportWorkOrderUpdate(BaseModel):
    rw_code: str | None = None
    dispatch_id: str | None = None
    product_id: str | None = None
    process_id: str | None = None
    line_id: str | None = None
    rw_date: date | None = None
    rw_time_slot: str | None = None
    rw_plan_qty: int | None = None
    rw_actual_qty: int | None = None
    rw_defect_qty: int | None = None
    rw_status: str | None = None
    rw_remark: str | None = None


class ReportWorkOrderOut(SyncBaseSchema):
    rw_code: str | None = None
    dispatch_id: str | None = None
    product_id: str | None = None
    process_id: str | None = None
    line_id: str | None = None
    rw_date: date | None = None
    rw_time_slot: str | None = None
    rw_plan_qty: int | None = None
    rw_actual_qty: int | None = None
    rw_defect_qty: int | None = None
    rw_status: str | None = None
    rw_remark: str | None = None


# ── 16. 工序排产单 ──────────────────────────────────────────────────────

class ProcessScheduleOrderCreate(BaseModel):
    pso_code: str | None = None
    demand_id: str | None = None
    product_id: str | None = None
    process_id: str | None = None
    seq: int | None = None
    line_id: str | None = None
    prev_pso_id: str | None = None
    plan_id: str | None = None
    pso_date: date | None = None
    pso_time_slot: str | None = None
    pso_quantity: int | None = None
    pso_completed_qty: int | None = 0
    pso_unfinished_qty: int | None = None
    pso_status: str | None = None
    dependency_type: str | None = None
    wait_time: float | None = None


class ProcessScheduleOrderUpdate(BaseModel):
    pso_code: str | None = None
    demand_id: str | None = None
    product_id: str | None = None
    process_id: str | None = None
    seq: int | None = None
    line_id: str | None = None
    prev_pso_id: str | None = None
    plan_id: str | None = None
    pso_date: date | None = None
    pso_time_slot: str | None = None
    pso_quantity: int | None = None
    pso_completed_qty: int | None = None
    pso_unfinished_qty: int | None = None
    pso_status: str | None = None
    dependency_type: str | None = None
    wait_time: float | None = None


class ProcessScheduleOrderOut(SyncBaseSchema):
    pso_code: str | None = None
    demand_id: str | None = None
    product_id: str | None = None
    process_id: str | None = None
    seq: int | None = None
    line_id: str | None = None
    prev_pso_id: str | None = None
    plan_id: str | None = None
    pso_date: date | None = None
    pso_time_slot: str | None = None
    pso_quantity: int | None = None
    pso_completed_qty: int | None = 0
    pso_unfinished_qty: int | None = None
    pso_status: str | None = None
    dependency_type: str | None = None
    wait_time: float | None = None
