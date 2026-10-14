"""Celery 任务定义模块，定义排产求解的异步任务。"""

import asyncio
from typing import Any

from loguru import logger

from app.scheduler.celery_app import celery_app
from app.scheduler.solver_wrapper import WorkshopSolverWrapper


@celery_app.task(bind=True, name="solve_schedule_task")
def solve_schedule_task(self, task_id: str) -> dict[str, Any]:
    """主排产任务，执行排产求解并将结果回写 HAP。

    任务流程：
    1. 更新任务状态为 RUNNING
    2. 创建 WorkshopSolverWrapper 并加载数据
    3. 执行求解
    4. 将结果回写 HAP
    5. 更新任务状态为 SUCCESS 或 FAILURE

    Args:
        self: Celery 任务实例（bind=True）
        task_id: 排产任务 ID

    Returns:
        dict: 任务执行结果
    """
    logger.info("排产任务开始执行，task_id: {}", task_id)

    try:
        # 更新任务状态为 RUNNING
        self.update_state(state="RUNNING", meta={"task_id": task_id, "progress": 0})

        # TODO: 从数据库获取任务配置
        config: dict[str, Any] = {
            "time_horizon": 7,
            "start_time": "2024-01-01",
            "end_time": "2024-01-07",
            "constraints": {},
            "objective_weights": {},
            "solver_params": {},
        }

        # 创建求解器封装
        wrapper = WorkshopSolverWrapper(config)

        # 异步加载数据（在同步 Celery 任务中运行异步代码）
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(wrapper.load_data_from_hap())
        finally:
            loop.close()

        self.update_state(state="RUNNING", meta={"task_id": task_id, "progress": 30})

        # 执行求解
        result = wrapper.run()
        self.update_state(state="RUNNING", meta={"task_id": task_id, "progress": 70})

        # 将结果回写 HAP
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(_push_results_to_hap(task_id, result))
        finally:
            loop.close()

        self.update_state(state="RUNNING", meta={"task_id": task_id, "progress": 100})

        # TODO: 更新数据库任务状态为 SUCCESS
        logger.info("排产任务执行成功，task_id: {}", task_id)

        return {
            "task_id": task_id,
            "status": "SUCCESS",
            "summary": result.get("summary", {}),
        }

    except Exception as e:
        logger.error("排产任务执行失败，task_id: {}, 错误: {}", task_id, str(e))
        # TODO: 更新数据库任务状态为 FAILURE
        self.update_state(
            state="FAILURE",
            meta={"task_id": task_id, "error": str(e)},
        )
        raise


async def _push_results_to_hap(task_id: str, result: dict[str, Any]) -> None:
    """将排产结果回写 HAP。

    Args:
        task_id: 排产任务 ID
        result: 求解结果
    """
    from app.services.hap_service import HAPService
    hap_service = HAPService()
    await hap_service.push_results(task_id)
    logger.info("排产结果已回写 HAP，task_id: {}", task_id)
