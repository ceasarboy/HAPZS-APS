"""写入工序依赖关系测试数据到HAP"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import asyncio
from app.hap.client import HAPClient

PROCESS_INFO_WS_ID = "6a2ded6888359ed358a4facd"
PRODUCT_PROCESS_WS_ID = "6a2ded6d3005b538f6a54ef1"
PRODUCT_WS_ID = "6a2bf816c839766934ee62e8"

async def get_field_map(client: HAPClient, worksheet_id: str) -> dict:
    """获取字段映射: name -> id"""
    structure = await client.get_worksheet_structure(worksheet_id)
    data = structure.get("data", {})
    fields = data.get("fields", [])
    return {f["name"]: f["id"] for f in fields if f.get("name") and f.get("id")}

async def get_option_key(field_info: dict, option_value: str) -> str:
    """从字段信息中获取选项key"""
    for opt in field_info.get("options", []):
        if opt.get("value") == option_value:
            return opt.get("key", "")
    return ""

async def get_row_id_by_title(client: HAPClient, worksheet_id: str, title_value: str) -> str:
    """通过标题字段查找行ID"""
    rows = await client.get_rows(worksheet_id, page_size=1000)
    for row in rows.get("data", {}).get("rows", []):
        fields = row.get("fields", {})
        # 标题字段通常是第一个Text字段
        for v in fields.values():
            if isinstance(v, str) and v == title_value:
                return row.get("rowId", "")
    return ""

async def write_process_info(client: HAPClient):
    """写入工序信息数据"""
    print("\n=== 写入工序信息数据 ===")
    
    field_map = await get_field_map(client, PROCESS_INFO_WS_ID)
    print(f"工序信息表字段: {list(field_map.keys())}")
    
    # 获取完整结构以获取选项key
    structure = await client.get_worksheet_structure(PROCESS_INFO_WS_ID)
    fields_info = {f["name"]: f for f in structure.get("data", {}).get("fields", [])}
    
    # 清空现有数据
    print("清空现有工序信息数据...")
    rows = await client.get_rows(PROCESS_INFO_WS_ID, page_size=1000)
    if rows.get("data", {}).get("rows"):
        row_ids = [r["rowId"] for r in rows["data"]["rows"]]
        await client.batch_delete_rows(PROCESS_INFO_WS_ID, row_ids)
        print(f"已删除 {len(row_ids)} 条记录")
    
    # 工序数据（使用实际HAP字段名）
    process_data = [
        {"工艺编码": "SMT", "工艺名称": "SMT贴片", "工艺类型": "成型", "约束类型": "机时约束",
         "标准节拍": 60, "换型时间": 5, "等待时间": 0, "等待计入下班时间": True, "准备时间": 3, "是否质检点": False, "状态": "启用"},
        {"工艺编码": "REFLOW", "工艺名称": "回流焊", "工艺类型": "焊接", "约束类型": "机时约束",
         "标准节拍": 120, "换型时间": 3, "等待时间": 5, "等待计入下班时间": True, "准备时间": 2, "是否质检点": False, "状态": "启用"},
        {"工艺编码": "AOI", "工艺名称": "AOI检测", "工艺类型": "检测", "约束类型": "机时约束",
         "标准节拍": 90, "换型时间": 2, "等待时间": 5, "等待计入下班时间": True, "准备时间": 2, "是否质检点": True, "状态": "启用"},
        {"工艺编码": "ICT", "工艺名称": "ICT测试", "工艺类型": "检测", "约束类型": "人员工时约束",
         "标准节拍": 180, "换型时间": 2, "等待时间": 5, "等待计入下班时间": True, "准备时间": 2, "是否质检点": True, "状态": "启用"},
        {"工艺编码": "FCT", "工艺名称": "FCT功能测试", "工艺类型": "检测", "约束类型": "人员工时约束",
         "标准节拍": 240, "换型时间": 2, "等待时间": 5, "等待计入下班时间": True, "准备时间": 2, "是否质检点": True, "状态": "启用"},
        {"工艺编码": "COATING", "工艺名称": "涂覆", "工艺类型": "处理", "约束类型": "机时约束",
         "标准节拍": 150, "换型时间": 5, "等待时间": 720, "等待计入下班时间": True, "准备时间": 5, "是否质检点": False, "状态": "启用"},
        {"工艺编码": "XRAY", "工艺名称": "X-Ray检测", "工艺类型": "检测", "约束类型": "机时约束",
         "标准节拍": 180, "换型时间": 3, "等待时间": 10, "等待计入下班时间": True, "准备时间": 3, "是否质检点": True, "状态": "启用"},
        {"工艺编码": "ASSEMBLY", "工艺名称": "组装", "工艺类型": "组装", "约束类型": "人员工时约束",
         "标准节拍": 300, "换型时间": 10, "等待时间": 20, "等待计入下班时间": True, "准备时间": 10, "是否质检点": False, "状态": "启用"},
        {"工艺编码": "AGING", "工艺名称": "老化测试", "工艺类型": "检测", "约束类型": "机时约束",
         "标准节拍": 3600, "换型时间": 5, "等待时间": 30, "等待计入下班时间": True, "准备时间": 5, "是否质检点": True, "状态": "启用"},
        {"工艺编码": "PACKING", "工艺名称": "包装", "工艺类型": "组装", "约束类型": "人员工时约束",
         "标准节拍": 60, "换型时间": 3, "等待时间": 10, "等待计入下班时间": True, "准备时间": 3, "是否质检点": False, "状态": "启用"},
    ]
    
    success_count = 0
    for data in process_data:
        fields = []
        for field_name, value in data.items():
            fid = field_map.get(field_name)
            if not fid:
                continue
            # 选项字段需要传key
            if field_name in ("工艺类型", "约束类型", "状态"):
                key = await get_option_key(fields_info.get(field_name, {}), value)
                fields.append({"id": fid, "value": [key] if key else value})
            # 布尔字段
            elif field_name in ("是否质检点", "等待计入下班时间"):
                fields.append({"id": fid, "value": value})
            else:
                fields.append({"id": fid, "value": value})
        
        result = await client.create_row(PROCESS_INFO_WS_ID, fields)
        rowid = result.get("data", {})
        if isinstance(rowid, dict):
            rowid = rowid.get("id", "")
        if rowid:
            success_count += 1
            print(f"  OK {data.get('工艺名称')} (等待={data.get('等待时间')}min, 准备={data.get('准备时间')}min)")
        else:
            print(f"  FAIL {data.get('工艺名称')}")
    
    print(f"工序信息写入: {success_count}/{len(process_data)}")
    return success_count

async def write_product_process(client: HAPClient):
    """写入产品工艺数据"""
    print("\n=== 写入产品工艺数据 ===")
    
    field_map = await get_field_map(client, PRODUCT_PROCESS_WS_ID)
    print(f"产品工艺表字段: {list(field_map.keys())}")
    
    # 获取完整结构
    structure = await client.get_worksheet_structure(PRODUCT_PROCESS_WS_ID)
    fields_info = {f["name"]: f for f in structure.get("data", {}).get("fields", [])}
    
    # 清空现有数据
    print("清空现有产品工艺数据...")
    rows = await client.get_rows(PRODUCT_PROCESS_WS_ID, page_size=1000)
    if rows.get("data", {}).get("rows"):
        row_ids = [r["rowId"] for r in rows["data"]["rows"]]
        await client.batch_delete_rows(PRODUCT_PROCESS_WS_ID, row_ids)
        print(f"已删除 {len(row_ids)} 条记录")
    
    # 先获取产品和工序的rowId
    print("获取产品rowId...")
    product_rows = await client.get_rows(PRODUCT_WS_ID, page_size=1000)
    product_id_map = {}  # 编码 -> rowId
    for row in product_rows.get("data", {}).get("rows", []):
        fields = row.get("fields", {})
        # 标题字段是产品编码
        for k, v in fields.items():
            if isinstance(v, str) and v.startswith("PROD-"):
                product_id_map[v] = row.get("rowId", "")
                break
    print(f"  产品映射: {product_id_map}")
    
    print("获取工序rowId...")
    process_rows = await client.get_rows(PROCESS_INFO_WS_ID, page_size=1000)
    process_id_map = {}  # 编码 -> rowId
    for row in process_rows.get("data", {}).get("rows", []):
        fields = row.get("fields", {})
        for k, v in fields.items():
            if isinstance(v, str) and v in ("SMT", "REFLOW", "AOI", "ICT", "FCT", "COATING", "XRAY", "ASSEMBLY", "AGING", "PACKING"):
                process_id_map[v] = row.get("rowId", "")
                break
    print(f"  工序映射: {process_id_map}")
    
    # 产品工艺数据
    pp_data = [
        {"产品编码": "PROD-5G-01", "工序编码": "SMT", "工序顺序": 1, "标准工时": 60, "依赖类型": "FS", "是否关键工序": True, "备注": "SMT贴片"},
        {"产品编码": "PROD-5G-01", "工序编码": "REFLOW", "工序顺序": 2, "标准工时": 120, "依赖类型": "FS", "是否关键工序": True, "备注": "回流焊"},
        {"产品编码": "PROD-5G-01", "工序编码": "AOI", "工序顺序": 3, "标准工时": 90, "依赖类型": "SS", "是否关键工序": False, "备注": "AOI检测（与ICT/FCT并行）"},
        {"产品编码": "PROD-5G-01", "工序编码": "ICT", "工序顺序": 3, "标准工时": 180, "依赖类型": "SS", "是否关键工序": False, "备注": "ICT测试（与AOI/FCT并行）"},
        {"产品编码": "PROD-5G-01", "工序编码": "FCT", "工序顺序": 3, "标准工时": 240, "依赖类型": "SS", "是否关键工序": False, "备注": "FCT功能测试（与AOI/ICT并行）"},
        {"产品编码": "PROD-5G-01", "工序编码": "COATING", "工序顺序": 4, "标准工时": 150, "依赖类型": "FS", "是否关键工序": False, "备注": "涂覆（需等待12小时表干）"},
        {"产品编码": "PROD-5G-01", "工序编码": "XRAY", "工序顺序": 5, "标准工时": 180, "依赖类型": "FS", "是否关键工序": True, "备注": "X-Ray检测"},
        {"产品编码": "PROD-5G-01", "工序编码": "ASSEMBLY", "工序顺序": 6, "标准工时": 300, "依赖类型": "FS", "是否关键工序": False, "备注": "组装"},
        {"产品编码": "PROD-5G-01", "工序编码": "AGING", "工序顺序": 7, "标准工时": 3600, "依赖类型": "FS", "是否关键工序": True, "备注": "老化测试"},
        {"产品编码": "PROD-5G-01", "工序编码": "PACKING", "工序顺序": 8, "标准工时": 60, "依赖类型": "FS", "是否关键工序": False, "备注": "包装"},
    ]
    
    success_count = 0
    for data in pp_data:
        fields = []
        for field_name, value in data.items():
            fid = field_map.get(field_name)
            if not fid:
                continue
            # 关联字段
            if field_name == "产品编码":
                row_id = product_id_map.get(value, "")
                if row_id:
                    fields.append({"id": fid, "value": [row_id]})
            elif field_name == "工序编码":
                row_id = process_id_map.get(value, "")
                if row_id:
                    fields.append({"id": fid, "value": [row_id]})
            # 选项字段
            elif field_name == "依赖类型":
                key = await get_option_key(fields_info.get(field_name, {}), value)
                fields.append({"id": fid, "value": [key] if key else value})
            else:
                fields.append({"id": fid, "value": value})
        
        result = await client.create_row(PRODUCT_PROCESS_WS_ID, fields)
        rowid = result.get("data", {})
        if isinstance(rowid, dict):
            rowid = rowid.get("id", "")
        if rowid:
            success_count += 1
            print(f"  OK {data.get('工序编码')} (seq={data.get('工序顺序')}, dep={data.get('依赖类型')})")
        else:
            print(f"  FAIL {data.get('工序编码')}")
    
    print(f"产品工艺写入: {success_count}/{len(pp_data)}")
    return success_count

async def main():
    client = HAPClient()
    
    process_count = await write_process_info(client)
    product_count = await write_product_process(client)
    
    print(f"\n=== 完成 ===")
    print(f"工序信息: {process_count}/10")
    print(f"产品工艺: {product_count}/10")

if __name__ == "__main__":
    asyncio.run(main())
