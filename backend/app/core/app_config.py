"""全局配置中心，提供运行时可读写的配置存储。

config API 和 HAPClient 共享此模块读写配置，
避免直接引用 API 层的私有变量。
"""

from typing import Any

from app.core.config import settings

# 运行时配置存储（内存）
_runtime_config: dict[str, Any] = {
    # HAP 鉴权配置
    "hap_app_id": "",
    "hap_app_key": "",
    "hap_sign": "",
    "hap_base_url": "",
}

# 求解器系统配置存储（内存）
_solver_config: dict[str, Any] = {
    "solver_type": "ortools",
    "start_time": "",
    "end_time": "",
    "hard_rules": ["FINITE_CAPACITY", "PROCESS_ORDER", "RESOURCE_COMPATIBILITY"],
    "soft_rules": ["OTD_PRIORITY", "SETUP_MINIMIZATION", "LOAD_BALANCING"],
    "soft_rule_weights": {
        "OTD_PRIORITY": 0.35,
        "SETUP_MINIMIZATION": 0.25,
        "LOAD_BALANCING": 0.15,
    },
}


def get_solver_config() -> dict[str, Any]:
    """获取求解器系统配置。"""
    return _solver_config.copy()


def set_solver_config(config: dict[str, Any]) -> None:
    """更新求解器系统配置（合并更新）。"""
    for key in ("solver_type", "start_time", "end_time", "hard_rules", "soft_rules", "soft_rule_weights"):
        if key in config:
            _solver_config[key] = config[key]


def get_hap_config() -> dict[str, str]:
    """获取 HAP 鉴权配置，优先运行时配置，fallback 到 settings。"""
    app_id = _runtime_config["hap_app_id"] or settings.HAP_APP_ID
    app_key = _runtime_config["hap_app_key"] or settings.HAP_APPKEY
    sign = _runtime_config["hap_sign"] or settings.HAP_SIGN
    base_url = _runtime_config["hap_base_url"] or settings.HAP_BASE_URL
    return {
        "hap_app_id": app_id,
        "hap_app_key": app_key,
        "hap_sign": sign,
        "hap_base_url": base_url,
    }


def set_hap_config(app_id: str, app_key: str, sign: str, base_url: str) -> None:
    """更新 HAP 鉴权配置到运行时存储。"""
    _runtime_config["hap_app_id"] = app_id
    _runtime_config["hap_app_key"] = app_key
    _runtime_config["hap_sign"] = sign
    _runtime_config["hap_base_url"] = base_url
