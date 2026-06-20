"""HAP 元数据缓存模块，使用 Redis 缓存选项字段映射和工作表结构。

缓存策略：
- 选项字段 key→value 映射：TTL 1 小时
- 工作表结构：TTL 1 小时
"""

from typing import Any

from loguru import logger

from app.core.redis import get_redis


class OptionCache:
    """选项字段缓存，存储 HAP 选项字段的 key→value 映射。

    Redis Key 格式: hap:option:{worksheet_id}:{field_id}
    TTL: 3600 秒（1 小时）
    """

    TTL = 3600  # 缓存有效期：1小时

    @staticmethod
    def _key(worksheet_id: str, field_id: str) -> str:
        """生成选项缓存 Redis Key。

        Args:
            worksheet_id: 工作表 ID
            field_id: 字段 ID

        Returns:
            str: Redis Key
        """
        return f"hap:option:{worksheet_id}:{field_id}"

    @staticmethod
    async def get(worksheet_id: str, field_id: str) -> dict[str, str] | None:
        """获取选项字段的 key→value 映射。

        Args:
            worksheet_id: 工作表 ID
            field_id: 字段 ID

        Returns:
            dict | None: key→value 映射字典，缓存不存在时返回 None
        """
        redis = await get_redis()
        key = OptionCache._key(worksheet_id, field_id)
        data = await redis.hgetall(key)
        if data:
            logger.debug("选项缓存命中: {}/{}", worksheet_id, field_id)
            return data
        return None

    @staticmethod
    async def set(worksheet_id: str, field_id: str, mapping: dict[str, str]) -> None:
        """设置选项字段的 key→value 映射缓存。

        Args:
            worksheet_id: 工作表 ID
            field_id: 字段 ID
            mapping: key→value 映射字典
        """
        redis = await get_redis()
        key = OptionCache._key(worksheet_id, field_id)
        await redis.hset(key, mapping=mapping)  # type: ignore[arg-type]
        await redis.expire(key, OptionCache.TTL)
        logger.debug("选项缓存已设置: {}/{}, 共 {} 项", worksheet_id, field_id, len(mapping))

    @staticmethod
    async def invalidate(worksheet_id: str, field_id: str) -> None:
        """使指定选项缓存失效。

        Args:
            worksheet_id: 工作表 ID
            field_id: 字段 ID
        """
        redis = await get_redis()
        key = OptionCache._key(worksheet_id, field_id)
        await redis.delete(key)
        logger.debug("选项缓存已失效: {}/{}", worksheet_id, field_id)


class StructureCache:
    """工作表结构缓存，存储 HAP 工作表的字段定义。

    Redis Key 格式: hap:structure:{worksheet_id}
    TTL: 3600 秒（1 小时）
    """

    TTL = 3600  # 缓存有效期：1小时

    @staticmethod
    def _key(worksheet_id: str) -> str:
        """生成结构缓存 Redis Key。

        Args:
            worksheet_id: 工作表 ID

        Returns:
            str: Redis Key
        """
        return f"hap:structure:{worksheet_id}"

    @staticmethod
    async def get(worksheet_id: str) -> dict[str, Any] | None:
        """获取工作表结构缓存。

        Args:
            worksheet_id: 工作表 ID

        Returns:
            dict | None: 工作表结构数据，缓存不存在时返回 None
        """
        redis = await get_redis()
        key = StructureCache._key(worksheet_id)
        import json
        data = await redis.get(key)
        if data:
            logger.debug("结构缓存命中: {}", worksheet_id)
            return json.loads(data)
        return None

    @staticmethod
    async def set(worksheet_id: str, structure: dict[str, Any]) -> None:
        """设置工作表结构缓存。

        Args:
            worksheet_id: 工作表 ID
            structure: 工作表结构数据
        """
        redis = await get_redis()
        key = StructureCache._key(worksheet_id)
        import json
        await redis.set(key, json.dumps(structure, ensure_ascii=False), ex=StructureCache.TTL)
        logger.debug("结构缓存已设置: {}", worksheet_id)

    @staticmethod
    async def invalidate(worksheet_id: str) -> None:
        """使指定结构缓存失效。

        Args:
            worksheet_id: 工作表 ID
        """
        redis = await get_redis()
        key = StructureCache._key(worksheet_id)
        await redis.delete(key)
        logger.debug("结构缓存已失效: {}", worksheet_id)


async def get_option_key(worksheet_id: str, field_id: str, display_value: str) -> str | None:
    """根据显示值查找选项字段的 key。

    优先从缓存查找，缓存未命中则从 HAP API 拉取工作表结构并更新缓存。

    Args:
        worksheet_id: 工作表 ID
        field_id: 字段 ID
        display_value: 选项的显示值

    Returns:
        str | None: 选项的 key 值，未找到时返回 None
    """
    # 先从缓存查找
    mapping = await OptionCache.get(worksheet_id, field_id)
    if mapping is None:
        # 缓存未命中，从 HAP API 拉取工作表结构
        from app.hap.client import HAPClient
        client = HAPClient()
        structure = await client.get_worksheet_structure(worksheet_id)
        # 提取选项字段映射并写入缓存
        controls = structure.get("data", {}).get("controls", [])
        for control in controls:
            if control.get("controlId") == field_id:
                options = control.get("options", [])
                opt_mapping = {opt.get("key", ""): opt.get("value", "") for opt in options}
                # 反转映射：value→key
                reverse_mapping = {v: k for k, v in opt_mapping.items()}
                await OptionCache.set(worksheet_id, field_id, reverse_mapping)
                mapping = reverse_mapping
                break

    if mapping:
        # 在映射中查找显示值对应的 key
        for key, value in mapping.items():
            if value == display_value:
                return key
    return None
