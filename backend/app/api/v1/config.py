"""系统配置接口，提供求解器配置和 HAP 鉴权配置的查询与更新。"""

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.app_config import get_hap_config, set_hap_config, get_solver_config, set_solver_config
from app.core.security import verify_api_key

router = APIRouter()


class HapConfigUpdate(BaseModel):
    """HAP 鉴权配置更新请求体。"""
    hap_app_id: str = ""
    hap_app_key: str = ""
    hap_sign: str = ""
    hap_base_url: str = "https://api.mingdao.com"


def _mask_sign(sign: str) -> str:
    """脱敏处理 Sign，只显示前6位。"""
    if len(sign) <= 6:
        return sign + "***" if sign else ""
    return sign[:6] + "***"


@router.get("/", summary="获取当前配置")
async def get_config(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """获取当前生效的求解器配置。"""
    return get_solver_config()


@router.put("/", summary="更新配置")
async def update_config(
    config: dict[str, Any],
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """更新求解器配置。"""
    # 合并更新
    if "solver_type" in config:
        set_solver_config({"solver_type": config["solver_type"]})
    if "start_time" in config:
        set_solver_config({"start_time": config["start_time"]})
    if "end_time" in config:
        set_solver_config({"end_time": config["end_time"]})
    if "config" in config:
        inner = config["config"]
        set_solver_config(inner)
    return get_solver_config()


@router.get("/presets", summary="获取预设配置列表")
async def get_presets(
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """获取所有预设配置列表。"""
    return []


@router.get("/hap", summary="获取 HAP 鉴权配置")
async def get_hap_config_endpoint(
    api_key: str = Depends(verify_api_key),
) -> dict[str, str]:
    """获取 HAP 鉴权配置，Sign 字段脱敏显示。"""
    cfg = get_hap_config()
    return {
        "hap_app_id": cfg["hap_app_id"],
        "hap_app_key": cfg["hap_app_key"],
        "hap_sign": _mask_sign(cfg["hap_sign"]),
        "hap_base_url": cfg["hap_base_url"],
    }


@router.put("/hap", summary="更新 HAP 鉴权配置")
async def update_hap_config_endpoint(
    data: HapConfigUpdate,
    api_key: str = Depends(verify_api_key),
) -> dict[str, str]:
    """更新 HAP 鉴权配置。"""
    set_hap_config(
        app_id=data.hap_app_id,
        app_key=data.hap_app_key,
        sign=data.hap_sign,
        base_url=data.hap_base_url,
    )
    # 返回脱敏结果
    cfg = get_hap_config()
    return {
        "hap_app_id": cfg["hap_app_id"],
        "hap_app_key": cfg["hap_app_key"],
        "hap_sign": _mask_sign(cfg["hap_sign"]),
        "hap_base_url": cfg["hap_base_url"],
    }
