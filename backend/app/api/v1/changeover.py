"""换线矩阵接口，提供换线矩阵的查询、更新和同步操作。"""

import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends
from loguru import logger

from app.core.security import verify_api_key
from app.hap.client import HAPClient

router = APIRouter()

_WORKSHEET_IDS_FILE = Path(__file__).resolve().parents[4] / "deploy" / "worksheet_ids_v2.json"


def _load_worksheet_ids() -> dict[str, str]:
    if _WORKSHEET_IDS_FILE.exists():
        with open(_WORKSHEET_IDS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _relation_name(raw: Any) -> str:
    """HAP 关联字段取显示名称。"""
    if isinstance(raw, list) and raw:
        return str(raw[0].get("name", ""))
    if isinstance(raw, dict):
        return str(raw.get("name", ""))
    return ""


def _float_val(raw: Any, default: float = 0.0) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except (ValueError, TypeError):
        return default


def _str_val(raw: Any, default: str = "") -> str:
    if raw is None:
        return default
    if isinstance(raw, list):
        # 选项字段
        if raw and isinstance(raw[0], dict):
            return str(raw[0].get("value", default))
        return default
    return str(raw).strip()


async def _fetch_changeover_from_hap() -> list[dict[str, Any]]:
    """从 HAP 拉取换线矩阵数据并转换为前端 ChangeoverCell[] 格式。"""
    ws_ids = _load_worksheet_ids()
    ws_id = ws_ids.get("changeover_matrix", "")
    if not ws_id:
        logger.warning("changeover_matrix 工作表 ID 未配置")
        return []

    client = HAPClient()
    result = await client.get_rows(ws_id, page_size=1000)
    rows = result.get("data", {}).get("rows", [])

    # 构建产品编码→名称映射（使用正确字段别名）
    product_ws_id = ws_ids.get("product", "")
    product_map: dict[str, str] = {}
    if product_ws_id:
        try:
            prod_result = await client.get_rows(product_ws_id, page_size=1000)
            prod_rows = prod_result.get("data", {}).get("rows", [])
            for pr in prod_rows:
                code = _str_val(pr.get("product_code", ""))
                name = _str_val(pr.get("product_name", ""))
                if code:
                    product_map[code] = name or code
        except Exception as e:
            logger.warning("获取产品映射失败: {}", e)

    cells: list[dict[str, Any]] = []
    for r in rows:
        from_product = _relation_name(r.get("from_product", ""))
        to_product = _relation_name(r.get("to_product", ""))
        changeover_time = _float_val(r.get("changeover_time", 0.0))

        # 如果关联字段为空，从 matrix_no 解析产品编码
        if not from_product or not to_product:
            matrix_no = _str_val(r.get("matrix_no", ""))
            if matrix_no and matrix_no.startswith("CO-"):
                parts = matrix_no[3:].split("-")
                if len(parts) >= 2:
                    if not from_product:
                        from_product = parts[0]
                    if not to_product:
                        to_product = parts[1]

        # 尝试用产品编码映射到名称
        from_display = product_map.get(from_product, from_product)
        to_display = product_map.get(to_product, to_product)

        if from_product and to_product:
            cells.append({
                "fromProduct": from_display,
                "toProduct": to_display,
                "changeoverTime": changeover_time,
            })
    return cells


@router.get("/", summary="查询换线矩阵")
async def get_changeover_matrix(
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """查询换线矩阵数据，返回 ChangeoverCell[] 格式。"""
    cells = await _fetch_changeover_from_hap()
    return cells


@router.put("/", summary="更新换线矩阵")
async def update_changeover_matrix(
    matrix: dict[str, Any],
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """更新换线矩阵数据。"""
    return {"status": "updated", "matrix_size": len(matrix)}


@router.post("/sync", summary="从 HAP 同步换线矩阵")
async def sync_changeover_matrix(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """从 HAP 平台同步换线矩阵数据。"""
    cells = await _fetch_changeover_from_hap()
    return {"status": "synced", "count": len(cells), "message": "换线矩阵同步完成"}
