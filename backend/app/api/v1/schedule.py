"""排产任务接口，提供排产任务的创建、查询、取消等操作。"""

from typing import Any

from fastapi import APIRouter, Depends, Query

from app.core.security import verify_api_key
from app.schemas.schedule import (
    ScheduleCreateRequest,
    ScheduleListResponse,
    ScheduleStatusResponse,
    InsertOrderRequest,
)
from app.services.schedule_service import schedule_service

router = APIRouter()


@router.post("/create", response_model=dict, summary="创建排产任务")
async def create_schedule(
    request: ScheduleCreateRequest,
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """创建排产任务，返回任务 ID。

    创建后会异步执行排产求解，可通过 /{task_id}/status 查询进度。

    Args:
        request: 排产任务创建请求
        api_key: API Key 认证

    Returns:
        dict: 包含 task_id 的响应
    """
    task_id = await schedule_service.create_schedule(request)
    return {"task_id": task_id, "status": "RUNNING"}


@router.get("/{task_id}/status", response_model=ScheduleStatusResponse, summary="查询任务状态")
async def get_schedule_status(
    task_id: str,
    api_key: str = Depends(verify_api_key),
) -> ScheduleStatusResponse:
    """查询排产任务状态和进度。

    Args:
        task_id: 任务 ID
        api_key: API Key 认证

    Returns:
        ScheduleStatusResponse: 任务状态信息
    """
    status = await schedule_service.get_status(task_id)
    return ScheduleStatusResponse(
        task_id=status["task_id"],
        status=status["status"],
        progress=status.get("progress", 0),
        created_at=status.get("created_at"),
        started_at=status.get("started_at"),
        completed_at=status.get("completed_at"),
        result_summary=status.get("result_summary"),
    )


@router.get("/list", response_model=ScheduleListResponse, summary="查询任务列表")
async def list_schedules(
    page: int = Query(default=1, ge=1, description="页码"),
    size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    api_key: str = Depends(verify_api_key),
) -> ScheduleListResponse:
    """查询排产任务列表（分页）。

    Args:
        page: 页码，从 1 开始
        size: 每页条数，最大 100
        api_key: API Key 认证

    Returns:
        ScheduleListResponse: 任务列表
    """
    result = await schedule_service.list_schedules(page, size)
    items = [
        ScheduleStatusResponse(
            task_id=item["task_id"],
            status=item["status"],
            progress=item.get("progress", 0),
            created_at=item.get("created_at"),
            started_at=item.get("started_at"),
            completed_at=item.get("completed_at"),
            result_summary=item.get("result_summary"),
        )
        for item in result["items"]
    ]
    return ScheduleListResponse(items=items, total=result["total"])


@router.post("/{task_id}/cancel", summary="取消任务")
async def cancel_schedule(
    task_id: str,
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """取消正在执行的排产任务。

    Args:
        task_id: 任务 ID
        api_key: API Key 认证

    Returns:
        dict: 取消结果
    """
    await schedule_service.cancel_schedule(task_id)
    return {"task_id": task_id, "status": "CANCELLED"}


@router.post("/insert-order", response_model=dict, summary="紧急插单")
async def insert_urgent_order(
    request: InsertOrderRequest,
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """向 HAP 需求计划表写入一条紧急需求（priority=紧急）。

    插单成功后，需重新调用 /create 触发排产。

    Args:
        request: 紧急插单请求
        api_key: API Key 认证

    Returns:
        dict: 包含 row_id 和 dp_code 的响应
    """
    result = await schedule_service.insert_urgent_order(
        product_id=request.product_id,
        quantity=request.quantity,
        due_date=request.due_date,
        remark=request.remark,
    )
    return result
