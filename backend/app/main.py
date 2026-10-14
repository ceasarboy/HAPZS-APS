"""FastAPI 应用入口模块。"""

from contextlib import asynccontextmanager
from datetime import date

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from app.api.router import v1_router
from app.core.redis import close_redis, init_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时初始化资源，关闭时释放资源。"""
    # M9修复: 关键初始化（Redis）失败时记录错误并中断；非关键初始化失败时降级运行
    # 启动事件：初始化 Redis 连接（关键服务）
    logger.info("初始化 Redis 连接...")
    try:
        await init_redis()
        logger.info("Redis 连接初始化完成")
    except Exception as e:
        logger.error("Redis 连接初始化失败（关键服务，启动中止）: {}", e)
        raise

    # 启动事件：HAP 缓存预热（非关键，失败时降级）
    logger.info("开始 HAP 缓存预热...")
    try:
        from app.hap.client import HAPClient
        client = HAPClient()
        # 预热：获取工作表列表
        await client.get_worksheets()
        logger.info("HAP 缓存预热完成")
    except Exception as e:
        logger.warning("HAP 缓存预热失败（不影响启动）: {}", e)

    # 启动事件：每日重置检查（非关键，失败时降级）
    try:
        from app.database import async_session
        from app.models.entities import SystemConfig
        from sqlalchemy import select, text

        today_str = date.today().isoformat()
        async with async_session() as session:
            # 检查 system_config 表是否存在
            try:
                await session.execute(text("SELECT 1 FROM system_config LIMIT 1"))
            except Exception:
                logger.warning("system_config 表不存在，跳过每日重置检查")
            else:
                cfg = await session.execute(
                    select(SystemConfig).where(SystemConfig.key == "last_daily_reset_date")
                )
                cfg_row = cfg.scalars().first()
                if not cfg_row or cfg_row.value != today_str:
                    # 执行每日重置
                    from app.api.v1.report_work import daily_reset
                    reset_result = await daily_reset(api_key="internal")
                    # 更新重置日期
                    if not cfg_row:
                        from sqlalchemy import insert
                        await session.execute(
                            insert(SystemConfig).values(key="last_daily_reset_date", value=today_str)
                        )
                    else:
                        cfg_row.value = today_str
                    await session.commit()
                    logger.info("每日重置完成: {}", reset_result)
    except Exception as e:
        logger.warning("每日重置检查失败（不影响启动）: {}", e)

    yield

    # 关闭事件：释放 Redis 连接
    logger.info("关闭 Redis 连接...")
    await close_redis()
    logger.info("Redis 连接已关闭")


# 创建 FastAPI 应用
app = FastAPI(
    title="APS-HAP",
    version="1.0.0",
    description="APS 排产系统后端，与明道云 HAP V3 API 对接，封装 OpenAPS 求解引擎",
    lifespan=lifespan,
)

# 配置 CORS（允许局域网访问）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允许所有来源，局域网环境
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册 v1 路由
app.include_router(v1_router)


@app.get("/health", summary="健康检查")
async def health_check() -> dict:
    """健康检查端点，返回服务状态。

    Returns:
        dict: 服务状态信息
    """
    return {
        "status": "healthy",
        "service": "APS-HAP",
        "version": "1.0.0",
    }
