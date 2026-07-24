"""HAP V3 API 客户端，封装与明道云 HAP 平台的 HTTP 交互。

HAP 特殊规则：
- 选项字段写入时使用 key 而非显示值
- 数值字段读取时为字符串类型，需手动转换
- 关联字段使用 belongsto 类型
"""

from typing import Any

import httpx
from loguru import logger

from app.core.app_config import get_hap_config
from app.core.config import settings


class HAPClient:
    """HAP V3 API 异步客户端。"""

    def __init__(self) -> None:
        """初始化 HAP 客户端，优先从运行时配置读取鉴权信息，fallback 到 settings。"""
        hap_cfg = get_hap_config()
        self.base_url = hap_cfg["hap_base_url"] or settings.HAP_BASE_URL
        self.headers = {
            "Content-Type": "application/json",
            "HAP-Appkey": hap_cfg["hap_app_key"] or settings.HAP_APPKEY,
            "HAP-Sign": hap_cfg["hap_sign"] or settings.HAP_SIGN,
        }
        self.app_id = hap_cfg["hap_app_id"] or settings.HAP_APP_ID

    def _get_client(self) -> httpx.AsyncClient:
        """创建 httpx 异步客户端实例。"""
        return httpx.AsyncClient(base_url=self.base_url, headers=self.headers, timeout=30.0)

    def _app_params(self) -> dict[str, str]:
        """获取包含 App ID 的通用查询参数。"""
        return {"appId": self.app_id}

    async def get_app_info(self) -> dict[str, Any]:
        """获取应用基本信息。

        Returns:
            dict: 应用信息
        """
        async with self._get_client() as client:
            response = await client.get("/v3/app/info", params=self._app_params())
            response.raise_for_status()
            data = response.json()
            logger.info("获取应用信息成功: {}", data.get("data", {}).get("appName", ""))
            return data

    async def get_worksheets(self) -> list[dict[str, Any]]:
        """获取应用下所有工作表列表。

        Returns:
            list[dict]: 工作表列表
        """
        async with self._get_client() as client:
            response = await client.get("/v3/app/worksheets", params=self._app_params())
            response.raise_for_status()
            data = response.json()
            worksheets = data.get("data", {}).get("worksheets", [])
            logger.info("获取工作表列表成功，共 {} 个", len(worksheets))
            return worksheets

    async def get_worksheet_structure(self, worksheet_id: str) -> dict[str, Any]:
        """获取指定工作表的结构信息（字段定义等）。

        Args:
            worksheet_id: 工作表 ID

        Returns:
            dict: 工作表结构信息
        """
        params = {**self._app_params(), "worksheetId": worksheet_id}
        async with self._get_client() as client:
            response = await client.get(f"/v3/app/worksheets/{worksheet_id}", params=params)
            response.raise_for_status()
            data = response.json()
            logger.info("获取工作表 {} 结构成功", worksheet_id)
            return data

    async def update_worksheet_structure(
        self,
        worksheet_id: str,
        worksheet_name: str,
        add_fields: list[dict[str, Any]] | None = None,
        edit_fields: list[dict[str, Any]] | None = None,
        remove_fields: list[str] | None = None,
    ) -> dict[str, Any]:
        """更新工作表结构（增删改字段）。

        HAP V3 API：PUT /v3/app/worksheets/{worksheetId}
        - name（工作表名称）为必填字段
        - addFields: 新增字段数组，options 需要 index 字段
        - editFields: 修改字段数组
        - removeFields: 删除字段 ID 数组

        HAP 字段类型代码：
        - Text: 2
        - Number: 6
        - Checkbox: 4
        - SingleSelect: 10
        - Date: 5
        - DateTime: 6
        - Relation: 8

        Args:
            worksheet_id: 工作表 ID
            worksheet_name: 工作表名称（必填）
            add_fields: 新增字段列表
            edit_fields: 修改字段列表
            remove_fields: 要删除的字段 ID 列表

        Returns:
            dict: 更新结果
        """
        payload: dict[str, Any] = {
            "appId": self.app_id,
            "worksheetId": worksheet_id,
            "name": worksheet_name,
        }
        if add_fields:
            payload["addFields"] = add_fields
        if edit_fields:
            payload["editFields"] = edit_fields
        if remove_fields:
            payload["removeFields"] = remove_fields

        async with self._get_client() as client:
            # HAP V3 SaaS：POST + addFields；私有部署可能支持 PUT
            response = await client.put(
                f"/v3/app/worksheets/{worksheet_id}", json=payload,
            )
            if response.status_code == 405:
                # SaaS 不支持 PUT，改用 POST
                logger.warning("PUT 方法不被支持（405），改用 POST + addFields")
                response = await client.post(
                    f"/v3/app/worksheets/{worksheet_id}", json=payload,
                )
            response.raise_for_status()
            data = response.json()
            logger.info(
                "更新工作表结构成功: {} (add={}, edit={}, remove={})",
                worksheet_id,
                len(add_fields or []),
                len(edit_fields or []),
                len(remove_fields or []),
            )
            return data

    async def add_field(
        self,
        worksheet_id: str,
        field_name: str,
        field_alias: str,
        field_type: int,
        options: list[dict[str, str]] | None = None,
        worksheet_name: str = "工作表",
    ) -> dict[str, Any]:
        """向工作表添加单个字段（便捷方法，底层调用 update_worksheet_structure）。

        Args:
            worksheet_id: 工作表 ID
            field_name: 字段名称
            field_alias: 字段别名
            field_type: 字段类型代码
            options: 选项字段选项列表 [{"value": "选项1"}, ...]
            worksheet_name: 工作表名称（HAP V3 API 必填）

        Returns:
            dict: 添加结果
        """
        field_def: dict[str, Any] = {
            "name": field_name,
            "alias": field_alias,
            "type": field_type,
        }
        if options:
            # HAP V3 要求 options 中包含 index 字段
            field_def["options"] = [
                {"value": opt["value"], "index": str(idx)}
                for idx, opt in enumerate(options)
            ]

        return await self.update_worksheet_structure(
            worksheet_id=worksheet_id,
            worksheet_name=worksheet_name,
            add_fields=[field_def],
        )

    async def get_rows(
        self,
        worksheet_id: str,
        filter: dict[str, Any] | None = None,
        sorts: list[dict[str, str]] | None = None,
        page_index: int = 1,
        page_size: int = 100,
    ) -> dict[str, Any]:
        """获取工作表行数据（分页）。

        Args:
            worksheet_id: 工作表 ID
            filter: 筛选条件，HAP 筛选器格式
            sorts: 排序条件列表
            page_index: 页码，从 1 开始
            page_size: 每页条数，最大 1000

        Returns:
            dict: 包含 total 和 rows 的响应数据
        """
        payload: dict[str, Any] = {
            "appId": self.app_id,
            "worksheetId": worksheet_id,
            "pageIndex": page_index,
            "pageSize": page_size,
        }
        if filter:
            payload["filters"] = filter if isinstance(filter, list) else [filter]
        if sorts:
            payload["sorts"] = sorts

        async with self._get_client() as client:
            response = await client.post(f"/v3/app/worksheets/{worksheet_id}/rows/list", json=payload)
            response.raise_for_status()
            data = response.json()
            rows = data.get("data", {}).get("rows", [])
            total = data.get("data", {}).get("total", 0)
            logger.info("获取工作表 {} 行数据，本页 {} 条，共 {} 条", worksheet_id, len(rows), total)
            return data

    @staticmethod
    def _normalize_fields(fields: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
        """将 fields 统一转换为 HAP V3 要求的数组格式。

        HAP V3 API 要求 fields 为 JSON 数组：[{"id": controlId, "value": value}, ...]
        旧代码传入字典格式 {controlId: value} 会导致反序列化失败。

        Args:
            fields: 字段数据，支持字典或数组格式

        Returns:
            list: 标准化的字段数组
        """
        if isinstance(fields, dict):
            return [{"id": k, "value": v} for k, v in fields.items() if v is not None]
        return fields or []

    async def create_row(
        self,
        worksheet_id: str,
        fields: dict[str, Any] | list[dict[str, Any]],
        trigger_workflow: bool = False,
    ) -> dict[str, Any]:
        """在工作表中创建一行数据。

        注意：选项字段需传入 key 值而非显示值。
        fields 支持两种格式：
        - 数组格式 [{"id": fieldId, "value": ...}]（推荐，HAP V3 标准）
        - 字典格式 {fieldId: value}（兼容旧调用，会自动转换为数组格式）

        Args:
            worksheet_id: 工作表 ID
            fields: 字段数据
            trigger_workflow: 是否触发工作流

        Returns:
            dict: 创建结果，包含新行 rowid
        """
        normalized_fields = self._normalize_fields(fields)
        payload = {
            "fields": normalized_fields,
            "triggerWorkflow": trigger_workflow,
        }
        async with self._get_client() as client:
            response = await client.post(f"/v3/app/worksheets/{worksheet_id}/rows", json=payload)
            response.raise_for_status()
            data = response.json()
            if not data.get("success", True):
                logger.error("创建行失败: {}", data.get("error_msg", ""))
            # HAP V3 返回格式: {"data": {"id": "row_id"}, "success": true}
            rowid = data.get("data", {})
            if isinstance(rowid, dict):
                rowid = rowid.get("id", "")
            logger.info("创建行成功，rowid: {}", rowid)
            return data

    async def batch_create_rows(
        self,
        worksheet_id: str,
        rows: list[dict[str, Any]],
        trigger_workflow: bool = False,
    ) -> dict[str, Any]:
        """批量创建行数据。

        注意：选项字段需传入 key 值而非显示值。
        rows 中每项的 fields 支持字典或数组格式，会自动转换为数组格式。

        Args:
            worksheet_id: 工作表 ID
            rows: 行数据列表，每项为字段字典
            trigger_workflow: 是否触发工作流

        Returns:
            dict: 批量创建结果
        """
        normalized_rows = [
            {**r, "fields": self._normalize_fields(r.get("fields", {}))}
            for r in rows
        ]
        payload = {
            "rows": normalized_rows,
            "triggerWorkflow": trigger_workflow,
        }
        async with self._get_client() as client:
            response = await client.post(f"/v3/app/worksheets/{worksheet_id}/rows/batch", json=payload)
            response.raise_for_status()
            data = response.json()
            logger.info("批量创建行成功，共 {} 行", len(rows))
            return data

    async def update_row(
        self,
        worksheet_id: str,
        row_id: str,
        fields: dict[str, Any] | list[dict[str, Any]],
        trigger_workflow: bool = False,
    ) -> dict[str, Any]:
        """更新指定行的数据。

        注意：HAP V3 SaaS 环境更新行必须用 PATCH，不是 POST（官方文档有误）。
        选项字段需传入 key 值而非显示值。
        fields 支持数组格式 [{"id": fieldId, "value": ...}] 和字典格式。

        Args:
            worksheet_id: 工作表 ID
            row_id: 行 ID（rowid）
            fields: 需要更新的字段数据
            trigger_workflow: 是否触发工作流

        Returns:
            dict: 更新结果
        """
        payload = {
            "fields": self._normalize_fields(fields),
            "triggerWorkflow": trigger_workflow,
        }
        async with self._get_client() as client:
            response = await client.patch(f"/v3/app/worksheets/{worksheet_id}/rows/{row_id}", json=payload)
            response.raise_for_status()
            data = response.json()
            logger.info("更新行 {} 成功", row_id)
            return data

    async def batch_update_rows(
        self,
        worksheet_id: str,
        row_ids: list[str],
        fields: dict[str, Any] | list[dict[str, Any]],
        trigger_workflow: bool = False,
    ) -> dict[str, Any]:
        """批量更新多行数据（统一字段值）。

        注意：选项字段需传入 key 值而非显示值。
        fields 支持数组格式 [{"id": fieldId, "value": ...}] 和字典格式。

        Args:
            worksheet_id: 工作表 ID
            row_ids: 行 ID 列表
            fields: 需要更新的字段数据（所有行更新为相同值）
            trigger_workflow: 是否触发工作流

        Returns:
            dict: 批量更新结果
        """
        payload = {
            "rowIds": row_ids,
            "fields": self._normalize_fields(fields),
            "triggerWorkflow": trigger_workflow,
        }
        async with self._get_client() as client:
            response = await client.patch(f"/v3/app/worksheets/{worksheet_id}/rows/batch", json=payload)
            response.raise_for_status()
            data = response.json()
            logger.info("批量更新行成功，共 {} 行", len(row_ids))
            return data

    async def delete_row(self, worksheet_id: str, row_id: str) -> dict[str, Any]:
        """删除指定行。

        Args:
            worksheet_id: 工作表 ID
            row_id: 行 ID（rowid）

        Returns:
            dict: 删除结果
        """
        params = {
            "appId": self.app_id,
            "worksheetId": worksheet_id,
            "rowId": row_id,
        }
        async with self._get_client() as client:
            response = await client.delete(f"/v3/app/worksheets/{worksheet_id}/rows/{row_id}", params=params)
            response.raise_for_status()
            data = response.json()
            logger.info("删除行 {} 成功", row_id)
            return data

    async def batch_delete_rows(self, worksheet_id: str, row_ids: list[str]) -> dict[str, Any]:
        """批量删除行。

        Args:
            worksheet_id: 工作表 ID
            row_ids: 行 ID 列表

        Returns:
            dict: 删除结果
        """
        import json as _json
        body = {
            "appId": self.app_id,
            "worksheetId": worksheet_id,
            "rowIds": row_ids,
        }
        async with self._get_client() as client:
            response = await client.request(
                "DELETE",
                f"/v3/app/worksheets/{worksheet_id}/rows",
                content=_json.dumps(body).encode(),
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            logger.info("批量删除行成功，共 {} 行", len(row_ids))
            return data
