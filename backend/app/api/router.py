"""API 路由注册模块，汇总所有 v1 版本路由。"""

from fastapi import APIRouter

from app.api.v1 import changeover, config, hap, result, schedule

# 创建 v1 版本路由器
v1_router = APIRouter(prefix="/api/v1")

# 注册各子模块路由
v1_router.include_router(hap.router, prefix="/hap", tags=["HAP 数据代理"])
v1_router.include_router(schedule.router, prefix="/schedule", tags=["排产任务"])
v1_router.include_router(result.router, prefix="/result", tags=["排产结果"])
v1_router.include_router(changeover.router, prefix="/changeover", tags=["换线矩阵"])
v1_router.include_router(config.router, prefix="/config", tags=["系统配置"])
