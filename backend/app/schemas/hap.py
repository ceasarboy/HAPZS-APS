"""HAP 数据 Pydantic V2 模型。"""

from typing import Any

from pydantic import BaseModel, Field


class HAPRowResponse(BaseModel):
    """HAP 行数据响应。"""

    rowid: str = Field(..., description="行 ID")
    fields: dict[str, Any] = Field(default_factory=dict, description="字段数据")


class HAPRowListResponse(BaseModel):
    """HAP 行数据列表响应。"""

    total: int = Field(default=0, description="总行数")
    rows: list[HAPRowResponse] = Field(default_factory=list, description="行数据列表")


# ── V2 模型 ──────────────────────────────────────────────────────────────


class DemandPlanItem(BaseModel):
    """需求计划数据项（V2，替代 OrderItem）。"""

    dp_code: str = Field(..., description="需求计划编号")
    dp_quantity: float = Field(default=0, description="需求数量")
    dp_unit: str = Field(default="台", description="单位")
    dp_due_date: str = Field(default="", description="交付日期")
    dp_priority: str = Field(default="中", description="优先级")
    dp_status: str = Field(default="待确认", description="状态")
    dp_product: str = Field(default="", description="关联产品")
    dp_remark: str = Field(default="", description="备注")


class ProductionLineItem(BaseModel):
    """产线数据项（V2，替代 WorkCenterItem）。"""

    line_code: str = Field(..., description="产线编码")
    line_name: str = Field(..., description="产线名称")
    line_type: str = Field(default="主产线", description="产线类型")
    line_capacity: int = Field(default=0, description="日产能")
    line_load: float = Field(default=0.0, description="负荷率")
    line_efficiency: float = Field(default=100.0, description="效率")
    line_location: str = Field(default="", description="位置")
    line_status: str = Field(default="运行中", description="状态")


class ResourceCalendarItem(BaseModel):
    """资源日历数据项（V2，替代 CalendarItem）。"""

    rc_code: str = Field(..., description="日历编码")
    rc_date: str = Field(..., description="日期")
    rc_is_workday: bool = Field(default=True, description="是否工作日")
    rc_daily_capacity: int = Field(default=0, description="日产能")
    rc_efficiency: float = Field(default=100.0, description="效率")
    rc_effective_capacity: float = Field(default=0.0, description="有效产能")
    rc_equipment_count: int = Field(default=0, description="设备数")
    rc_worker_count: int = Field(default=0, description="人员数")
    rc_line: str = Field(default="", description="关联产线")


class ProcessInfoItem(BaseModel):
    """工序信息数据项（V2 新增）。"""

    proc_code: str = Field(..., description="工序编码")
    proc_name: str = Field(default="", description="工序名称")
    proc_type: str = Field(default="", description="工序类型")
    constraint_type: str = Field(default="", description="约束类型")
    cycle_time: float = Field(default=0.0, description="标准节拍(秒)")
    setup_time: float = Field(default=0.0, description="换型时间(分钟)")
    wait_time: float = Field(default=0.0, description="等待时间(分钟)")
    wait_includes_offhours: bool = Field(default=True, description="等待时间是否计入下班时间")
    prep_time: float = Field(default=0.0, description="准备时间(分钟)")
    is_qc_point: bool = Field(default=False, description="是否质检点")
    status: str = Field(default="启用", description="状态")


class ProductProcessItem(BaseModel):
    """产品工艺数据项（V2 新增）。"""

    product_id: str = Field(default="", description="关联产品")
    process_id: str = Field(default="", description="关联工序")
    seq: int = Field(default=0, description="工序顺序")
    std_time: float = Field(default=0.0, description="标准工时(秒)")
    dependency_type: str = Field(default="FS", description="依赖类型：FS/SS/FF/SF")
    is_key: bool = Field(default=False, description="是否关键工序")
    remark: str = Field(default="", description="备注")


class LineProcessConfigItem(BaseModel):
    """产线工艺配置数据项（V2 新增）。"""

    line_id: str = Field(default="", description="关联产线")
    process_id: str = Field(default="", description="关联工序")
    daily_capacity: int = Field(default=0, description="日产能")
    efficiency: float = Field(default=100.0, description="效率")
    min_batch: int = Field(default=0, description="最小批量")
    is_bottleneck: bool = Field(default=False, description="是否瓶颈")
    equipment_count: int = Field(default=0, description="设备数")
    worker_count: int = Field(default=0, description="人员数")
    status: str = Field(default="启用", description="状态")


class ProcessBOMItem(BaseModel):
    """工序 BOM 数据项（V2 新增）。"""

    product_id: str = Field(default="", description="关联产品")
    process_id: str = Field(default="", description="关联工序")
    material_id: str = Field(default="", description="关联物料")
    unit_qty: float = Field(default=0.0, description="单位用量")
    reusable: bool = Field(default=False, description="是否可复用")
    remark: str = Field(default="", description="备注")


class MaterialKittingItem(BaseModel):
    """物料齐套数据项（V2，替代旧 Kitting）。"""

    demand_id: str = Field(default="", description="关联需求计划")
    product_id: str = Field(default="", description="关联产品")
    process_id: str = Field(default="", description="关联工序")
    material_id: str = Field(default="", description="关联物料")
    required_qty: int = Field(default=0, description="需求数量")
    available_qty: int = Field(default=0, description="可用数量")
    shortage_qty: int = Field(default=0, description="缺料数量")
    kitting_date: str = Field(default="", description="齐套日期")
    kitting_status: str = Field(default="待确认", description="齐套状态")


# ── V1 兼容别名 ──────────────────────────────────────────────────────────


class OrderItem(BaseModel):
    """订单数据项（V1 兼容，推荐使用 DemandPlanItem）。"""

    order_no: str = Field(..., description="订单编号")
    priority: str = Field(default="普通", description="优先级")
    delivery_date: str = Field(..., description="交期")
    product: str = Field(..., description="产品编码")
    quantity: float = Field(default=0, description="订单数量")
    scheduled_quantity: float = Field(default=0, description="已排产数量")
    status: str = Field(default="待排产", description="订单状态")


class WorkCenterItem(BaseModel):
    """工作中心数据项（V1 兼容，推荐使用 ProductionLineItem）。"""

    code: str = Field(..., description="工作中心编码")
    name: str = Field(..., description="工作中心名称")
    type: str = Field(default="生产线", description="类型")
    oee: float = Field(default=0.85, description="设备综合效率")


class CalendarItem(BaseModel):
    """日历数据项（V1 兼容，推荐使用 ResourceCalendarItem）。"""

    date: str = Field(..., description="日期")
    shift: str = Field(default="白班", description="班次")
    start_time: str = Field(default="08:00", description="开始时间")
    end_time: str = Field(default="20:00", description="结束时间")
    status: str = Field(default="工作日", description="状态")
