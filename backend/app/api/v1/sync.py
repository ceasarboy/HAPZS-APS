"""HAP 同步 API 端点。"""

from fastapi import APIRouter

from app.services.sync_service import SyncService, TABLE_HAP_MAP, SYNC_ORDER

router = APIRouter()


@router.post("/pull/{table_name}")
async def pull_from_hap(table_name: str):
    """从 HAP 拉取指定表数据写入本地 DB（全量覆盖）。"""
    if table_name not in TABLE_HAP_MAP:
        return {"success": False, "error": f"未知表名: {table_name}，可选: {list(TABLE_HAP_MAP.keys())}"}
    svc = SyncService()
    result = await svc.pull_from_hap(table_name)
    return result


@router.post("/pull-all")
async def pull_all():
    """从 HAP 拉取全部表数据写入本地 DB。"""
    svc = SyncService()
    result = await svc.pull_all()
    return result


@router.post("/push/{table_name}")
async def push_to_hap(table_name: str):
    """将本地变更推送到 HAP（增量同步）。"""
    if table_name not in TABLE_HAP_MAP:
        return {"success": False, "error": f"未知表名: {table_name}，可选: {list(TABLE_HAP_MAP.keys())}"}
    svc = SyncService()
    result = await svc.push_to_hap(table_name)
    return result


@router.post("/push-all")
async def push_all():
    """推送全部待同步数据到 HAP。"""
    svc = SyncService()
    result = await svc.push_all_pending()
    return result


@router.get("/status")
async def get_sync_status():
    """获取各表同步状态统计。"""
    svc = SyncService()
    result = await svc.get_sync_status()
    return result


@router.get("/tables")
async def get_sync_tables():
    """获取可同步的表列表。"""
    return {
        "tables": list(TABLE_HAP_MAP.keys()),
        "sync_order": SYNC_ORDER,
    }
