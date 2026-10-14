"""系统配置 Pydantic V2 模型。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ConstraintConfig(BaseModel):
    """约束配置。"""

    enable_capacity_cons: bool = Field(default=True, description="启用产能约束")
    enable_demand_cons: bool = Field(default=True, description="启用需求约束")
    demand_cons_mode: str = Field(default="soft", description="需求约束模式: soft/hard")
    enable_kitting_cons: bool = Field(default=False, description="启用齐套约束")
    enable_inventory_cons: bool = Field(default=False, description="启用库存约束")
    enable_changeover_cons: bool = Field(default=True, description="启用换线约束")
    enable_frozen_horizon: bool = Field(default=False, description="启用冻结期")
    frozen_until: str | None = Field(default=None, description="冻结截止时间")


class ObjectiveWeights(BaseModel):
    """目标权重配置。"""

    workload: float = Field(default=1.0, description="负荷权重")
    idletime: float = Field(default=0.5, description="空闲权重")
    job_bias: float = Field(default=0.3, description="作业偏好权重")
    waittime: float = Field(default=0.2, description="等待时间权重")
    changeover: float = Field(default=0.8, description="换线权重")
    load_variance: float = Field(default=0.4, description="负荷均衡权重")


class SolverParams(BaseModel):
    """求解器参数。"""

    threads: int = Field(default=4, description="求解线程数")
    time_limit: int = Field(default=300, description="求解时间限制（秒）")


class ConfigResponse(BaseModel):
    """配置响应。"""

    id: str = Field(..., description="配置 ID")
    name: str = Field(..., description="配置名称")
    constraints: ConstraintConfig = Field(default_factory=ConstraintConfig, description="约束配置")
    objective_weights: ObjectiveWeights = Field(default_factory=ObjectiveWeights, description="目标权重")
    solver_params: SolverParams = Field(default_factory=SolverParams, description="求解器参数")
    is_default: bool = Field(default=False, description="是否为默认配置")
