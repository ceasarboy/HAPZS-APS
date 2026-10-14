"""Celery 实例配置模块。"""

from celery import Celery

from app.core.config import settings

# 创建 Celery 实例
celery_app = Celery(
    "aps_hap",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# Celery 配置
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,  # 结果过期时间：1小时
    timezone="Asia/Shanghai",
    enable_utc=True,
)

# 自动发现任务模块
celery_app.autodiscover_tasks(["app.scheduler"])
