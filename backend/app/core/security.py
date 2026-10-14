"""简单 API Key 认证模块，适用于局域网环境。"""

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from app.core.config import settings

# API Key 请求头定义
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Depends(api_key_header)) -> str:
    """验证请求中的 API Key。

    Args:
        api_key: 请求头中的 API Key

    Returns:
        str: 验证通过的 API Key

    Raises:
        HTTPException: API Key 缺失或无效时抛出 401 错误
    """
    if api_key is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="缺少 API Key，请在请求头 X-API-Key 中提供",
        )
    if api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key 无效",
        )
    return api_key
