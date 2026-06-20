"""排产任务 Pydantic V2 模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ScheduleCreateRequest(BaseModel):
    """创建排产任务请求。"""

    time_horizon: int = Field(default=7, description="排产时间范围（天）")
    start_time: str = Field(..., description="排产开始时间，格式 YYYY-MM-DD")
    end_time: str = Field(..., description="排产结束时间，格式 YYYY-MM-DD")
    solver_type: str = Field(default="ortools", description="求解器类型: ortools/ga")
    constraints: dict[str, Any] = Field(default_factory=dict, description="约束配置")
    objective_weights: dict[str, Any] = Field(default_factory=dict, description="目标权重")
    solver_config: str | None = Field(default=None, description="求解器配置 ID")
    freeze_horizon: int = Field(default=0, description="冻结窗口（天），前 N 天的时间槽被锁定")
    solver_params: dict[str, Any] = Field(default_factory=dict, description="求解器参数")


class ScheduleStatusResponse(BaseModel):
    """排产任务状态响应。"""

    task_id: str = Field(..., description="任务 ID")
    status: str = Field(..., description="任务状态: PENDING/RUNNING/SUCCESS/FAILURE")
    progress: int = Field(default=0, description="任务进度百分比")
    created_at: datetime | None = Field(default=None, description="创建时间")
    started_at: datetime | None = Field(default=None, description="开始时间")
    completed_at: datetime | None = Field(default=None, description="完成时间")
    result_summary: dict[str, Any] | None = Field(default=None, description="结果汇总")


class ScheduleListResponse(BaseModel):
    """排产任务列表响应。"""

    items: list[ScheduleStatusResponse] = Field(default_factory=list, description="任务列表")
    total: int = Field(default=0, description="任务总数")


class InsertOrderRequest(BaseModel):
    """紧急插单请求。"""

    product_id: str = Field(..., description="产品 ID（HAP 产品主数据 rowId）")
    quantity: int = Field(..., gt=0, description="需求数量")
    due_date: str = Field(..., description="交期日期 YYYY-MM-DD")
    remark: str = Field(default="", description="备注")
