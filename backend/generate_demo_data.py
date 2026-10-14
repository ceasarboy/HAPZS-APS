"""
生成本地数据库演示数据
用于APS-HAP系统演示和测试
"""
import asyncio
import asyncpg
import uuid
from datetime import datetime, timedelta
import random

async def generate_demo_data():
    # 连接数据库
    conn = await asyncpg.connect(
        host='localhost',
        port=5432,
        user='postgres',
        password='123456',
        database='aps_hap'
    )

    try:
        print("=" * 60)
        print("开始生成演示数据...")
        print("=" * 60)

        # ============================================================
        # 1. 产品主数据 (15个产品)
        # ============================================================
        print("\n1. 创建产品主数据...")
        products = []
        product_data = [
            ("P001", "外壳-A1", "颜色A", 2, 50),
            ("P002", "外壳-A2", "颜色A", 2, 50),
            ("P003", "外壳-B1", "颜色B", 2, 40),
            ("P004", "外壳-B2", "颜色B", 2, 40),
            ("P005", "面板-C1", "颜色C", 3, 60),
            ("P006", "面板-C2", "颜色C", 3, 60),
            ("P007", "支架-D1", "模具类型1", 4, 80),
            ("P008", "支架-D2", "模具类型1", 4, 80),
            ("P009", "底座-E1", "模具类型2", 1, 30),
            ("P010", "底座-E2", "模具类型2", 1, 30),
            ("P011", "盖板-F1", "颜色A", 3, 50),
            ("P012", "盖板-F2", "颜色B", 3, 50),
            ("P013", "连接器-G1", "模具类型1", 5, 100),
            ("P014", "连接器-G2", "模具类型2", 5, 100),
            ("P015", "转接片-H1", "颜色C", 6, 120),
        ]

        for code, name, attr, rate, batch in product_data:
            product_id = str(uuid.uuid4())
            await conn.execute('''
                INSERT INTO products (id, prod_code, prod_name, changeover_attr, output_rate, batch_size, sync_status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, 'SYNCED', NOW(), NOW())
            ''', product_id, code, name, attr, rate, batch)
            products.append((product_id, code, name, attr))

        print(f"  ✓ 已创建 {len(products)} 个产品")

        # ============================================================
        # 2. 工艺信息 (10道工序)
        # ============================================================
        print("\n2. 创建工艺信息...")
        processes = []
        process_data = [
            ("PROC-01", "注塑成型", "机时约束", False),
            ("PROC-02", "冲压成型", "机时约束", False),
            ("PROC-03", "表面处理", "人员工时约束", True),
            ("PROC-04", "组装", "人员工时约束", False),
            ("PROC-05", "质量检验", "人员工时约束", True),
            ("PROC-06", "包装", "人员工时约束", False),
            ("PROC-07", "固化", "机时约束", False),
            ("PROC-08", "清洗", "机时约束", False),
            ("PROC-09", "涂覆", "人员工时约束", False),
            ("PROC-10", "老化测试", "机时约束", False),
        ]

        for code, name, const_type, is_qc in process_data:
            process_id = str(uuid.uuid4())
            await conn.execute('''
                INSERT INTO process_info (id, proc_code, proc_name, constraint_type, is_qc_point, status, sync_status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, '启用', 'SYNCED', NOW(), NOW())
            ''', process_id, code, name, const_type, is_qc)
            processes.append((process_id, code, name))

        print(f"  ✓ 已创建 {len(processes)} 道工序")

        # ============================================================
        # 3. 产线 (4条产线)
        # ============================================================
        print("\n3. 创建产线...")
        lines = []
        line_data = [
            ("LINE-A", "注塑产线A", "注塑", 600),
            ("LINE-B", "注塑产线B", "注塑", 550),
            ("LINE-C", "冲压产线C", "冲压", 500),
            ("LINE-D", "装配产线D", "装配", 450),
        ]

        for code, name, ltype, capacity in line_data:
            line_id = str(uuid.uuid4())
            await conn.execute('''
                INSERT INTO production_lines (id, line_code, line_name, line_type, status, sync_status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, '启用', 'SYNCED', NOW(), NOW())
            ''', line_id, code, name, ltype)
            lines.append((line_id, code, name))

        print(f"  ✓ 已创建 {len(lines)} 条产线")

        # ============================================================
        # 4. 产品工艺关系 (每个产品3-5道工序)
        # ============================================================
        print("\n4. 创建产品工艺关系...")
        pp_count = 0
        for prod_idx, (prod_id, prod_code, prod_name, prod_attr) in enumerate(products):
            # 为每个产品分配3-5道工序
            num_procs = random.randint(3, 5)
            selected_procs = random.sample(processes, num_procs)

            for seq, (proc_id, proc_code, proc_name) in enumerate(selected_procs):
                pp_id = str(uuid.uuid4())
                cycle_time = random.uniform(30, 120)  # 30-120秒节拍时间
                wait_time = random.choice([0, 60, 120, 180])  # 等待时间（分钟）
                dependency_type = random.choice(['FS', 'SS', 'FF', 'SF'])

                await conn.execute('''
                    INSERT INTO product_processes 
                    (id, product_id, process_id, seq, auto_type, cycle_time, max_units_per_beat, 
                     prep_time, wait_time, dependency_type, wait_includes_offhours, is_key, 
                     sync_status, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, 'SYNCED', NOW(), NOW())
                ''', pp_id, prod_id, proc_id, seq, '非自动', cycle_time, 1, 
                    random.uniform(5, 15), wait_time, dependency_type, 
                    random.choice([True, False]), random.choice([True, False]))
                pp_count += 1

        print(f"  ✓ 已创建 {pp_count} 条产品工艺关系")

        # ============================================================
        # 5. 产线工艺配置
        # ============================================================
        print("\n5. 创建产线工艺配置...")
        lpc_count = 0
        for line_idx, (line_id, line_code, line_name) in enumerate(lines):
            # 每条产线配置4-6道工序
            selected_procs = random.sample(processes, random.randint(4, 6))

            for proc_idx, (proc_id, proc_code, proc_name) in enumerate(selected_procs):
                lpc_id = str(uuid.uuid4())
                lpc_code = f"LPC-{line_code}-{proc_code}"

                await conn.execute('''
                    INSERT INTO line_process_configs 
                    (id, lpc_code, line_id, process_id, auto_type, is_bottleneck, equipment_count, 
                     worker_count, status, sync_status, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, '启用', 'SYNCED', NOW(), NOW())
                ''', lpc_id, lpc_code, line_id, proc_id, '非自动',
                    random.choice([True, False]), 
                    random.randint(1, 5), 
                    random.randint(1, 3))
                lpc_count += 1

        print(f"  ✓ 已创建 {lpc_count} 条产线工艺配置")

        # ============================================================
        # 6. 需求计划 (20个需求)
        # ============================================================
        print("\n6. 创建需求计划...")
        demands = []
        today = datetime.now()
        
        for i in range(1, 21):
            demand_id = str(uuid.uuid4())
            dp_code = f"DP-2026-{i:04d}"
            product_idx = (i - 1) % len(products)
            product_id = products[product_idx][0]
            
            quantity = random.randint(50, 200)
            due_date = (today + timedelta(days=random.randint(2, 7))).date()
            priority = random.choice(['普通', '紧急'])
            
            await conn.execute('''
                INSERT INTO demand_plans 
                (id, dp_code, product_id, dp_quantity, dp_due_date, dp_priority, dp_status, 
                 sync_status, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, '已确认', 'SYNCED', NOW(), NOW())
            ''', demand_id, dp_code, product_id, quantity, due_date, priority)
            
            demands.append((demand_id, dp_code, quantity, due_date, priority))

        print(f"  ✓ 已创建 {len(demands)} 个需求计划")

        # ============================================================
        # 7. 换线矩阵
        # ============================================================
        print("\n7. 创建换线矩阵...")
        co_count = 0

        # 按换线属性分组
        attr_groups = {}
        for prod_id, prod_code, prod_name, prod_attr in products:
            if prod_attr not in attr_groups:
                attr_groups[prod_attr] = []
            attr_groups[prod_attr].append((prod_id, prod_code))

        # 创建换线矩阵（只在不同产品间创建）
        for i, (prod_id1, prod_code1, prod_name1, prod_attr1) in enumerate(products):
            for j, (prod_id2, prod_code2, prod_name2, prod_attr2) in enumerate(products):
                if i >= j:
                    continue

                co_id = str(uuid.uuid4())
                
                # 根据换线属性计算换线时间
                if prod_attr1 == prod_attr2:
                    setup_time = 15  # 相同属性，换线时间短
                elif (prod_attr1 in ["颜色A", "颜色B", "颜色C"] and prod_attr2 in ["颜色A", "颜色B", "颜色C"]):
                    setup_time = 30  # 相同类型（颜色），换线时间中等
                elif (prod_attr1 in ["模具类型1", "模具类型2"] and prod_attr2 in ["模具类型1", "模具类型2"]):
                    setup_time = 25  # 相同类型（模具），换线时间中等
                else:
                    setup_time = 45  # 不同类型，换线时间长

                await conn.execute('''
                    INSERT INTO changeover_matrices 
                    (id, from_product, to_product, setup_time, sync_status, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, 'SYNCED', NOW(), NOW())
                ''', co_id, prod_id1, prod_id2, setup_time)
                co_count += 1

        print(f"  ✓ 已创建 {co_count} 条换线矩阵")

        # ============================================================
        # 8. 缓冲配置
        # ============================================================
        print("\n8. 创建缓冲配置...")
        for proc_idx, (proc_id, proc_code, proc_name) in enumerate(processes):
            buffer_id = str(uuid.uuid4())
            buffer_time = random.randint(5, 30)  # 5-30分钟缓冲时间

            await conn.execute('''
                INSERT INTO buffer_configs 
                (id, bc_process, buffer_time, sync_status, created_at, updated_at)
                VALUES ($1, $2, $3, 'SYNCED', NOW(), NOW())
            ''', buffer_id, proc_id, buffer_time)

        print(f"  ✓ 已创建 {len(processes)} 条缓冲配置")

        # ============================================================
        # 汇总
        # ============================================================
        print("\n" + "=" * 60)
        print("演示数据生成完成！")
        print("=" * 60)
        print(f"  产品主数据: {len(products)} 条")
        print(f"  工艺信息:   {len(processes)} 条")
        print(f"  产线:       {len(lines)} 条")
        print(f"  产品工艺:   {pp_count} 条")
        print(f"  产线配置:   {lpc_count} 条")
        print(f"  需求计划:   {len(demands)} 条")
        print(f"  换线矩阵:   {co_count} 条")
        print(f"  缓冲配置:   {len(processes)} 条")
        
        total_demand = sum(d[2] for d in demands)
        print(f"\n  总需求量:   {total_demand} 台")
        print(f"  交货期范围: {today.date()} 至 {(today + timedelta(days=7)).date()}")
        print("=" * 60)

    except Exception as e:
        print(f"❌ 数据生成失败: {e}")
        raise
    finally:
        await conn.close()

if __name__ == '__main__':
    asyncio.run(generate_demo_data())