"""
添加数据库中缺失的字段
"""
import asyncio
import asyncpg

async def add_missing_fields():
    # 连接数据库
    conn = await asyncpg.connect(
        host='localhost',
        port=5432,
        user='postgres',
        password='123456',
        database='aps_hap'
    )

    try:
        # 1. 修复 product_processes 表
        print("正在修复 product_processes 表...")
        fields_to_add = [
            ("auto_type", "VARCHAR(20)", "非自动", "工艺类型（自动/非自动）"),
            ("cycle_time", "DOUBLE PRECISION", None, "节拍时间（秒）"),
            ("max_units_per_beat", "INTEGER", "1", "单节拍最大数量"),
            ("prep_time", "DOUBLE PRECISION", None, "准备时间（分钟）"),
            ("wait_time", "DOUBLE PRECISION", None, "等待时间（分钟）"),
            ("wait_includes_offhours", "BOOLEAN", "FALSE", "下班时间是否可计入等待时间"),
        ]

        for field_name, field_type, default_value, comment in fields_to_add:
            try:
                # 检查字段是否已存在
                exists = await conn.fetchval(f"""
                    SELECT COUNT(*) FROM information_schema.columns
                    WHERE table_name='product_processes' AND column_name='{field_name}'
                """)

                if exists == 0:
                    # 添加字段
                    if default_value:
                        await conn.execute(f'''
                            ALTER TABLE product_processes
                            ADD COLUMN {field_name} {field_type} DEFAULT {default_value}
                        ''')
                    else:
                        await conn.execute(f'''
                            ALTER TABLE product_processes
                            ADD COLUMN {field_name} {field_type}
                        ''')
                    print(f"  ✓ 已添加字段 {field_name} ({comment})")
                else:
                    print(f"  - 字段 {field_name} 已存在，跳过")
            except Exception as e:
                print(f"  ✗ 添加字段 {field_name} 失败: {e}")

        # 2. 修复 process_schedule_orders 表
        print("\n正在修复 process_schedule_orders 表...")
        try:
            # 检查字段是否已存在
            exists = await conn.fetchval("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_name='process_schedule_orders' AND column_name='planned_qty'
            """)

            if exists == 0:
                # 添加 planned_qty 字段
                await conn.execute('''
                    ALTER TABLE process_schedule_orders
                    ADD COLUMN planned_qty INTEGER
                ''')
                print("  ✓ 已添加字段 planned_qty (计划数量)")
            else:
                print("  - 字段 planned_qty 已存在，跳过")
        except Exception as e:
            print(f"  ✗ 添加字段 planned_qty 失败: {e}")

        print("\n✅ 所有缺失字段已添加完成！")

    except Exception as e:
        print(f"❌ 修复过程出错: {e}")
        raise
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(add_missing_fields())