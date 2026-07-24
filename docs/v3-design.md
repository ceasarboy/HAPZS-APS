# V3 架构设计：本地数据库为主，HAP 为展示底座

## 1. 背景与目标

### V2 现状问题
- HAP 是唯一数据源，每次排产全量拉取，网络延迟大
- 本地 PostgreSQL 已配置但形同虚设，任务状态纯内存
- 无本地 CRUD 能力，数据编辑依赖 HAP 原生界面
- 排产结果仅存 HAP，查询需回读 HAP，组装复杂

### V3 目标
- **本地 PostgreSQL 为主数据源**，所有数据先写本地
- **HAP 为展示底座**，单向推送同步，不在 HAP 端编辑
- **每张表实现完整 CRUD**，前端可视化界面管理
- **前端 API 路径不变**，后端切换数据源即可

## 2. 架构变更

```
V2: 前端 → 后端 API → HAP API（唯一数据源）
                         ↓ 读取
                    ScheduleService → 求解 → 写回 HAP

V3: 前端 → 后端 API → 本地 PostgreSQL（主数据源）
                         ↓ 单向推送
                    HAP 工作表（展示底座）
                         ↓ 读取
                    ScheduleService → 求解 → 写回本地 DB → 异步推送 HAP
```

## 3. 数据库设计

### 3.1 公共字段

每张表都包含以下公共字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | UUID | 本地主键 |
| `hap_row_id` | String(64) | HAP 行 ID（用于同步关联，可空） |
| `sync_status` | Enum | synced / pending_create / pending_update / pending_delete |
| `synced_at` | DateTime | 最后成功同步时间 |
| `created_at` | DateTime | 本地创建时间 |
| `updated_at` | DateTime | 本地更新时间 |

### 3.2 各表字段设计

#### 产品主数据 (products)

| 字段 | 类型 | 说明 |
|------|------|------|
| prod_code | String(50) | 产品编码 |
| prod_name | String(100) | 产品名称 |
| prod_category | String(50) | 产品分类 |
| prod_spec | String(200) | 产品规格 |
| changeover_attr | String(50) | 换线属性 |
| output_rate | Float | 出件率 |
| batch_size | Integer | 整批量 |

#### 工艺信息 (process_info)

| 字段 | 类型 | 说明 |
|------|------|------|
| proc_code | String(50) | 工序编码 |
| proc_name | String(100) | 工序名称 |
| proc_type | String(50) | 工序类型（成型/焊接/处理/组装/检测） |
| constraint_type | String(50) | 约束类型（机时约束/人员工时约束） |
| cycle_time | Float | 标准节拍（秒） |
| setup_time | Float | 换型时间（分钟） |
| wait_time | Float | 等待时间（分钟） |
| wait_includes_offhours | Boolean | 等待是否计入下班时间 |
| prep_time | Float | 准备时间（分钟） |
| is_qc_point | Boolean | 是否质检点 |
| status | String(20) | 状态（启用/停用） |

#### 产线 (production_lines)

| 字段 | 类型 | 说明 |
|------|------|------|
| line_code | String(50) | 产线编码 |
| line_name | String(100) | 产线名称 |
| line_type | String(50) | 产线类型 |
| daily_capacity | Integer | 日产能 |
| efficiency | Float | 效率百分比 |
| location | String(100) | 位置 |
| status | String(20) | 状态 |

#### 产品工艺 (product_processes)

| 字段 | 类型 | 说明 |
|------|------|------|
| product_id | UUID(FK) | 关联产品 |
| process_id | UUID(FK) | 关联工序 |
| seq | Integer | 工序顺序 |
| std_time | Float | 标准工时（秒） |
| dependency_type | String(10) | 依赖类型（FS/SS/FF/SF） |
| is_key | Boolean | 是否关键工序 |
| remark | String(200) | 备注 |

#### 产线工艺配置 (line_process_configs)

| 字段 | 类型 | 说明 |
|------|------|------|
| line_id | UUID(FK) | 关联产线 |
| process_id | UUID(FK) | 关联工序 |
| daily_capacity | Integer | 日产能 |
| efficiency | Float | 效率百分比 |
| min_batch | Integer | 最小批量 |
| is_bottleneck | Boolean | 是否瓶颈 |
| equipment_count | Integer | 设备数量 |
| worker_count | Integer | 人员数量 |
| status | String(20) | 状态 |

#### 物料主数据 (material_masters)

| 字段 | 类型 | 说明 |
|------|------|------|
| mat_code | String(50) | 物料编码 |
| mat_name | String(100) | 物料名称 |
| mat_type | String(50) | 物料类型 |
| unit | String(20) | 计量单位 |
| safety_stock | Integer | 安全库存 |
| stock_qty | Integer | 库存数量 |
| in_transit | Integer | 在途数量 |
| status | String(20) | 状态 |

#### 工序BOM (process_boms)

| 字段 | 类型 | 说明 |
|------|------|------|
| product_id | UUID(FK) | 关联产品 |
| process_id | UUID(FK) | 关联工序 |
| material_id | UUID(FK) | 关联物料 |
| unit_qty | Float | 单位用量 |
| reusable | Boolean | 是否可复用 |
| remark | String(200) | 备注 |

#### 物料齐套 (material_kittings)

| 字段 | 类型 | 说明 |
|------|------|------|
| demand_id | UUID(FK) | 关联需求计划 |
| product_id | UUID(FK) | 关联产品 |
| process_id | UUID(FK) | 关联工序 |
| material_id | UUID(FK) | 关联物料 |
| required_qty | Integer | 需求数量 |
| available_qty | Integer | 可用数量 |
| shortage_qty | Integer | 缺料数量 |
| kitting_date | Date | 齐套日期 |
| kitting_status | String(20) | 齐套状态 |

#### 需求计划 (demand_plans)

| 字段 | 类型 | 说明 |
|------|------|------|
| dp_code | String(50) | 需求编码 |
| product_id | UUID(FK) | 关联产品 |
| quantity | Integer | 需求数量 |
| unit | String(20) | 单位 |
| due_date | Date | 交货日期 |
| priority | String(20) | 优先级（紧急/高/中/低） |
| status | String(20) | 状态 |
| scheduled_qty | Integer | 已排数量 |
| remark | String(200) | 备注 |

#### 排产结果 (schedule_results)

| 字段 | 类型 | 说明 |
|------|------|------|
| plan_id | UUID(FK) | 关联排产方案 |
| product_id | UUID(FK) | 关联产品 |
| process_id | UUID(FK) | 关联工序 |
| line_id | UUID(FK) | 关联产线 |
| demand_id | UUID(FK) | 关联需求计划 |
| sr_date | Date | 排产日期 |
| sr_time_slot | String(20) | 时间段 |
| sr_quantity | Integer | 排产数量 |
| sr_status | String(20) | 状态 |
| process_code | String(50) | 工序编码（冗余） |
| constraint_type | String(50) | 约束类型（冗余） |
| seq | Integer | 工序顺序 |
| dependency_type | String(10) | 依赖类型 |
| wait_time | Float | 等待时间 |
| prep_time | Float | 准备时间 |

#### 资源日历 (resource_calendars)

| 字段 | 类型 | 说明 |
|------|------|------|
| rc_code | String(100) | 资源编码 |
| rc_date | Date | 日期 |
| rc_hour | Integer | 小时时段 |
| line_id | UUID(FK) | 关联产线 |
| process_id | UUID(FK) | 关联工序 |
| available_capacity | Float | 可用产能 |
| is_working | Boolean | 是否工作时段 |

#### 换线矩阵 (changeover_matrices)

| 字段 | 类型 | 说明 |
|------|------|------|
| from_product_id | UUID(FK) | 源产品 |
| to_product_id | UUID(FK) | 目标产品 |
| setup_time | Float | 换线时间（分钟） |

#### 缓冲配置 (buffer_configs)

| 字段 | 类型 | 说明 |
|------|------|------|
| process_id | UUID(FK) | 关联工序 |
| buffer_time | Integer | 缓冲时间（分钟） |

#### 排产方案 (schedule_plans)

| 字段 | 类型 | 说明 |
|------|------|------|
| sp_name | String(100) | 方案名称 |
| sp_status | String(20) | 方案状态 |
| sp_start_date | Date | 排产开始日期 |
| sp_end_date | Date | 排产结束日期 |
| sp_solver | String(20) | 求解器类型 |
| sp_solve_status | String(20) | 求解状态 |
| sp_solve_time | Float | 求解耗时（秒） |
| sp_task_count | Integer | 任务数量 |
| sp_total_output | Integer | 总产量 |

## 4. 同步服务设计

### 4.1 SyncService

```python
class SyncService:
    """HAP 同步服务：本地 DB ↔ HAP"""

    async def pull_from_hap(self, table_name: str) -> SyncResult:
        """从 HAP 拉取数据写入本地 DB（全量覆盖）"""

    async def push_to_hap(self, table_name: str) -> SyncResult:
        """将本地变更推送到 HAP（增量同步）"""

    async def push_all_pending(self) -> SyncResult:
        """推送所有待同步记录"""

    async def get_sync_status(self) -> dict:
        """获取各表同步状态"""
```

### 4.2 同步策略

| 操作 | 本地 DB | HAP | sync_status |
|------|---------|-----|-------------|
| 首次拉取 | 写入 | 不变 | synced |
| 本地新增 | INSERT | 待推送 | pending_create |
| 本地修改 | UPDATE | 待推送 | pending_update |
| 本地删除 | DELETE | 待推送 | pending_delete |
| 推送成功 | 更新状态 | 写入/更新/删除 | synced |
| 推送失败 | 保持 pending | 不变 | pending_* |

### 4.3 同步 API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/sync/pull/{table}` | POST | 从 HAP 拉取指定表 |
| `/api/v1/sync/pull-all` | POST | 从 HAP 拉取全部表 |
| `/api/v1/sync/push/{table}` | POST | 推送指定表到 HAP |
| `/api/v1/sync/push-all` | POST | 推送全部待同步数据 |
| `/api/v1/sync/status` | GET | 查看同步状态 |

## 5. CRUD API 设计

每张表统一遵循 RESTful 风格：

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/{entity}` | GET | 列表查询（分页、筛选） |
| `/api/v1/{entity}/{id}` | GET | 详情查询 |
| `/api/v1/{entity}` | POST | 新增 |
| `/api/v1/{entity}/{id}` | PUT | 修改 |
| `/api/v1/{entity}/{id}` | DELETE | 删除 |

14 张表对应的 entity 路径：

| entity 路径 | 表名 | 说明 |
|-------------|------|------|
| `/products` | products | 产品主数据 |
| `/process-info` | process_info | 工艺信息 |
| `/production-lines` | production_lines | 产线 |
| `/product-processes` | product_processes | 产品工艺 |
| `/line-process-configs` | line_process_configs | 产线工艺配置 |
| `/material-masters` | material_masters | 物料主数据 |
| `/process-boms` | process_boms | 工序BOM |
| `/material-kittings` | material_kittings | 物料齐套 |
| `/demand-plans` | demand_plans | 需求计划 |
| `/schedule-results` | schedule_results | 排产结果 |
| `/resource-calendars` | resource_calendars | 资源日历 |
| `/changeover-matrices` | changeover_matrices | 换线矩阵 |
| `/buffer-configs` | buffer_configs | 缓冲配置 |
| `/schedule-plans` | schedule_plans | 排产方案 |

### 兼容性处理

现有 `/api/v1/hap/*` 端点改为从本地 DB 读取，保持前端零改动：

| 旧端点 | 新数据源 |
|--------|---------|
| `GET /hap/products` | 查询 products 表 |
| `GET /hap/demand-plans` | 查询 demand_plans 表 |
| `GET /hap/production-lines` | 查询 production_lines 表 |
| `GET /hap/process-info` | 查询 process_info 表 |
| `GET /hap/product-processes` | 查询 product_processes 表 |
| `GET /hap/line-process-configs` | 查询 line_process_configs 表 |
| `GET /hap/resource-calendar` | 查询 resource_calendars 表 |
| `GET /hap/material-kitting` | 查询 material_kittings 表 |
| `GET /hap/process-bom` | 查询 process_boms 表 |

## 6. 前端页面规划

### 6.1 页面结构

| 页面 | 管理的表 | 路由 |
|------|---------|------|
| 主数据管理 | 产品主数据、物料主数据 | /master-data |
| 工艺管理 | 工艺信息、产品工艺、产线工艺配置 | /process |
| 产线管理 | 产线、资源日历 | /production-lines |
| 需求管理 | 需求计划、物料齐套 | /demand |
| 排产管理 | 排产结果、排产方案 | /schedule（现有） |
| 系统配置 | 换线矩阵、缓冲配置、HAP 连接、同步状态 | /config（现有扩展） |

### 6.2 通用组件

- **DataTable**：封装 Ant Design Table + 分页 + 搜索 + 排序 + 同步状态标识
- **DataForm**：封装 Ant Design Modal Form，根据字段定义自动生成表单
- **SyncBadge**：同步状态标识组件（已同步/待同步/同步失败）

### 6.3 侧边栏更新

```
仪表盘
排产编制
排产历史
主数据管理    ← 新增
  ├ 产品主数据
  ├ 物料主数据
工艺管理      ← 新增
  ├ 工序信息
  ├ 产品工艺
  └ 产线工艺配置
产线管理      ← 新增
  ├ 产线信息
  └ 资源日历
需求管理      ← 新增
  ├ 需求计划
  └ 物料齐套
系统设置
  ├ HAP 连接配置
  ├ 同步管理     ← 新增
  ├ 换线矩阵
  └ 缓冲配置
```

## 7. ScheduleService 改造

### 7.1 数据读取

```python
# V2: 从 HAP 拉取
async def fetch_scheduling_data(self):
    products = await self._fetch_products()  # HAP API

# V3: 从本地 DB 读取
async def fetch_scheduling_data(self, db: AsyncSession):
    products = await self._fetch_products_from_db(db)  # PostgreSQL
```

### 7.2 结果写入

```python
# V2: 写入 HAP
async def push_results(self, task_id: str):
    await self._batch_write_tasks(...)  # HAP API

# V3: 写入本地 DB + 异步推送 HAP
async def push_results(self, task_id: str, db: AsyncSession):
    await self._write_results_to_db(db, ...)  # PostgreSQL
    asyncio.create_task(self._sync_results_to_hap())  # 异步推送
```

### 7.3 任务状态持久化

现有 `self._tasks` 内存字典改为数据库持久化，使用已有的 `schedule_plans` 表。

## 8. 实施计划

### Step 1: 数据库建模 + 迁移 + 同步服务

- [ ] 创建 14 张 SQLAlchemy ORM 模型
- [ ] 配置 Alembic 迁移
- [ ] 实现 SyncService（拉取/推送/状态查询）
- [ ] 实现同步 API 端点
- [ ] 测试：从 HAP 拉取数据到本地 DB，验证数据完整性

### Step 2: 后端 CRUD API + 排产流程改造

- [ ] 实现通用 CRUD 基类（减少重复代码）
- [ ] 为 14 张表各实现 CRUD API
- [ ] 改造 `/api/v1/hap/*` 端点从本地 DB 读取
- [ ] 改造 ScheduleService 从本地 DB 读取/写入
- [ ] 测试：CRUD 操作 + 排产流程端到端验证

### Step 3: 前端管理界面

- [ ] 实现 DataTable / DataForm / SyncBadge 通用组件
- [ ] 实现 6 个管理页面
- [ ] 更新侧边栏导航
- [ ] 测试：前端 CRUD 操作 + 同步状态展示

## 9. 可清理的死代码

V3 完成后，以下模块可以清理：

- `hap/mapper.py`：未被排产核心流程使用
- `services/hap_service.py`：未被排产流程使用
- `hap/cache.py`：本地 DB 化后不再需要 Redis 缓存
- 各文件中重复的 `_str_val`、`_float_val`、`_relation_id` 工具函数
