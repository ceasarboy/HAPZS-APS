"""Redis 异步连接管理模块，提供依赖注入。"""

import redis.asyncio as aioredis

from app.core.config import settings

# 全局 Redis 连接池
_redis_pool: aioredis.Redis | None = None


async def init_redis() -> aioredis.Redis:
    """初始化 Redis 连接池，在应用启动时调用。"""
    global _redis_pool
    _redis_pool = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,
    )
    return _redis_pool


async def close_redis() -> None:
    """关闭 Redis 连接池，在应用关闭时调用。"""
    global _redis_pool
    if _redis_pool:
        await _redis_pool.close()
        _redis_pool = None


async def get_redis() -> aioredis.Redis:
    """获取 Redis 连接实例，用于 FastAPI 依赖注入。

    Returns:
        aioredis.Redis: Redis 异步连接实例

    Raises:
        RuntimeError: 如果 Redis 连接池未初始化
    """
    if _redis_pool is None:
        raise RuntimeError("Redis 连接池未初始化，请先调用 init_redis()")
    return _redis_pool
