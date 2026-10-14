# 排产仿真流程设计

## 概述

在现有排产系统基础上，增加排产执行跟踪和仿真闭环功能，实现：
1. 排产单增加完成数量/未完成数量/状态字段
2. 报工单自动生成并回写排产单
3. 日终自动处理：待生产→已失效，未完成数量进入次日排产
4. 同优先级内未完成数量优先排产

## 方案选择

**方案A（已选定）**：在现有 `schedule_results` 表上扩展字段，复用现有报工单和HAP同步机制。

理由：改动最小，数据关系清晰，无需新建表。

## 1. 数据模型变更

### 1.1 schedule_results 表新增字段

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `sr_completed_qty` | Integer | 0 | 已完成数量 |
| `sr_unfinished_qty` | Integer | sr_quantity | 未完成数量 = sr_quantity - sr_completed_qty |

### 1.2 sr_status 枚举值

| 状态 | 说明 | 触发条件 |
|------|------|----------|
| 待生产 | 排产确认后 | 用户确认排产结果 |
| 已完成 | 全部完成 | sr_completed_qty >= sr_quantity |
| 已失效 | 昨天未完成 | 日终处理：昨天+待生产→已失效 |

> 注意：去掉原有的"待确认"状态，排产确认后直接为"待生产"。

### 1.3 数据库迁移

```python
# alembic migration
def upgrade():
    op.add_column('schedule_results', sa.Column('sr_completed_qty', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('schedule_results', sa.Column('sr_unfinished_qty', sa.Integer(), nullable=True))
    # 将现有 sr_status='待确认' 改为 '待生产'
    op.execute("UPDATE schedule_results SET sr_status='待生产' WHERE sr_status='待确认' OR sr_status IS NULL")
```

### 1.4 HAP 字段同步

在 HAP schedule_result 工作表中添加对应的字段：
- `sr_completed_qty`：数值字段
- `sr_unfinished_qty`：数值字段
- `sr_status`：改为单选字段，选项为 待生产/已完成/已失效

## 2. 业务流程

```
排产触发 → 排产结果写入(sr_status=待生产, completed_qty=0, unfinished_qty=sr_quantity)
           ↓
       用户确认排产 → 自动生成报工单(rw_status=待报工, rw_plan_qty=sr_quantity)
           ↓
       报工(rw_actual_qty=X) → 回写排产单(sr_completed_qty += X)
           ↓                          └→ 如 completed >= qty → sr_status=已完成
       日终处理(每天首次启动):
         1. 昨天sr_status=待生产 → 已失效
         2. 已失效记录的unfinished_qty > 0 → 生成临时需求（携带原优先级）
         3. 重新排产时，新需求+未完成需求一起参与排产
```

## 3. 详细设计

### 3.1 排产确认（确认排产 → 待生产 + 生成报工单）

**API**: `POST /api/v1/schedule/confirm/{task_id}`

逻辑：
1. 将 task_id 对应的排产结果 sr_status 从 "待确认" 改为 "待生产"
2. 为每条排产结果自动生成一条 `report_work_orders` 记录：
   - `dispatch_id` = schedule_result.id
   - `product_id`, `process_id`, `line_id` 从排产结果复制
   - `rw_date` = sr_date
   - `rw_time_slot` = sr_time_slot
   - `rw_plan_qty` = sr_quantity
   - `rw_actual_qty` = 0
   - `rw_status` = "待报工"

### 3.2 报工回写排产单

**API**: `POST /api/v1/report-work/{dispatch_id}`

请求体：
```json
{
  "rw_actual_qty": 25,
  "rw_defect_qty": 0,
  "rw_remark": ""
}
```

逻辑：
1. 更新 report_work_order 的 rw_actual_qty, rw_status="已报工"
2. 查找关联的 schedule_result (via dispatch_id)
3. 更新 schedule_result:
   - `sr_completed_qty += rw_actual_qty`
   - `sr_unfinished_qty = sr_quantity - sr_completed_qty`
   - 如果 `sr_completed_qty >= sr_quantity`，则 `sr_status = "已完成"`
4. 同步到 HAP

### 3.3 日终处理

**API**: `POST /api/v1/schedule/daily-reset`

**自动触发**: 后端 lifespan 启动时检查 `last_daily_reset_date`，如非今天则执行。

逻辑：
1. 查找 `sr_status='待生产'` 且 `sr_date < 今天` 的排产结果
2. 将这些记录的 `sr_status` 改为 "已失效"
3. 记录 `last_daily_reset_date = 今天`
4. 关联的报工单 rw_status 改为 "已关闭"（如果仍为"待报工"）

### 3.4 未完成数量→次日排产

在 `schedule_service.py` 的 `_fetch_demand_plans` 方法中：

1. 查找 `sr_status='已失效'` 且 `sr_unfinished_qty > 0` 的排产结果
2. 按原始 demand_id 分组，合并同一需求的未完成数量
3. 为每组生成一个临时 `DemandPlan`：
   - `id` = 生成临时 UUID
   - `product_id` = 原 schedule_result.product_id
   - `quantity` = 分组内 sr_unfinished_qty 之和
   - `due_date` = 今天 + 1（默认明天交期）
   - `priority` = 从原 demand_plan 继承
   - `dp_code` = `UNFINISHED-{原dp_code}`（标记为未完成转来）
   - `is_carryover = True`（新字段，标记为结转需求）
4. 优先级排序：同优先级内，`is_carryover=True` 的排在前面
   - 实现方式：在 priority_weight 计算时，结转需求加 0.1 的微小权重提升

### 3.5 排产时状态初始化

`_batch_write_tasks` 方法修改：
- `sr_status` 初始值从 "待确认" 改为 "待生产"
- `sr_completed_qty` = 0
- `sr_unfinished_qty` = sr_quantity

## 4. API 端点汇总

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/schedule/confirm/{task_id}` | POST | 确认排产，生成报工单 |
| `/api/v1/report-work/{dispatch_id}` | POST | 单条报工，回写排产单 |
| `/api/v1/report-work/` | GET | 报工单列表（支持过滤） |
| `/api/v1/schedule/daily-reset` | POST | 手动触发日终处理 |
| `/api/v1/schedule/result` | GET | 排产结果列表（含新增字段） |

## 5. 前端变更

### 5.1 排产结果页面
- 表格新增列：已完成数量、未完成数量、状态
- 状态列用 Tag 组件显示：待生产(蓝)、已完成(绿)、已失效(灰)
- 确认按钮：点击后调用 confirm API

### 5.2 报工页面
- 新增报工管理页面（菜单：生产数据 → 报工管理）
- 表格列：派工单号、产品、工序、产线、计划数量、实际数量、状态、操作
- 操作列：报工按钮，弹出对话框填写实际完成数量
- 支持按状态过滤（待报工/已报工/已关闭）

### 5.3 日终处理
- 在排产页面添加"日终处理"按钮（手动触发）
- 后端启动时自动执行一次

## 6. 关键约束

1. **报工数量不能超过未完成数量**：`rw_actual_qty <= sr_unfinished_qty`
2. **已失效的排产单不可再报工**：只有"待生产"状态可报工
3. **未完成数量按需求计划维度合并**：同一需求的多道工序分别结转
4. **结转需求标注来源**：dp_code 前缀 `UNFINISHED-`，便于追踪
5. **日终处理幂等**：同一天多次执行不会重复处理

## 7. 验证场景

1. 基本流程：排产→确认→报工→完成
2. 部分完成：排产30→报工25→未完成5→日终处理→5台结转次日
3. 优先级排序：高优先级新需求 + 低优先级未完成5台 → 高优先级先排，5台同优先级内先排
4. 日终幂等：多次调用日终处理不影响已处理的数据
5. 全部完成：排产30→报工30→状态自动变为"已完成"
