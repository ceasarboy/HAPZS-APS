# 排产仿真流程实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有排产系统上增加执行跟踪闭环——排产单增加完成/未完成数量、报工回写、日终处理、未完成结转次日排产

**Architecture:** 在 schedule_results 表扩展字段，复用现有 report_work_orders 表和 HAP 同步机制。新增 4 个 API 端点（确认排产、报工、报工列表、日终处理），修改排产服务以支持未完成结转需求。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + React 18 + Ant Design 5

---

## 文件结构

### 新建文件
- `backend/alembic/versions/xxxx_add_simulation_fields.py` — 数据库迁移
- `backend/app/api/v1/report_work.py` — 报工 API
- `frontend/src/pages/ReportWork/index.tsx` — 报工管理页面

### 修改文件
- `backend/app/models/entities.py` — ScheduleResult 新增字段
- `backend/app/services/schedule_service.py` — 排产确认、日终处理、未完成结转
- `backend/app/api/v1/result.py` — 排产结果 API 新增字段返回
- `backend/app/schemas/schedule.py` — Pydantic schema 新增字段
- `backend/app/main.py` — 注册报工路由、lifespan 添加日终处理
- `backend/app/hap/client.py` — HAP 字段映射更新
- `frontend/src/components/CrudPage/index.tsx` — 支持排产结果状态显示
- `frontend/src/router/index.tsx` — 添加报工路由
- `frontend/src/types/hap.ts` — 类型定义更新

---

### Task 1: 数据库模型 + 迁移

**Files:**
- Modify: `backend/app/models/entities.py:154-172`
- Create: `backend/alembic/versions/xxxx_add_simulation_fields.py`

- [ ] **Step 1: 修改 ScheduleResult 模型，添加新字段**

在 `backend/app/models/entities.py` 的 ScheduleResult 类中，在 `prep_time` 字段后添加：

```python
    sr_completed_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0, comment="已完成数量")
    sr_unfinished_qty: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="未完成数量")
```

- [ ] **Step 2: 生成 Alembic 迁移脚本**

Run: `cd e:\openaps\aps-hap\backend && alembic revision --autogenerate -m "add_simulation_fields"`

检查生成的迁移文件，确保包含：
- `sr_completed_qty` 列（Integer, server_default='0'）
- `sr_unfinished_qty` 列（Integer）
- 更新 sr_status 旧值：`UPDATE schedule_results SET sr_status='待生产' WHERE sr_status='待确认' OR sr_status IS NULL`

如果 autogenerate 不包含 UPDATE 语句，手动添加：
```python
def upgrade():
    op.add_column('schedule_results', sa.Column('sr_completed_qty', sa.Integer(), nullable=True, server_default='0'))
    op.add_column('schedule_results', sa.Column('sr_unfinished_qty', sa.Integer(), nullable=True))
    op.execute("UPDATE schedule_results SET sr_status='待生产' WHERE sr_status='待确认' OR sr_status IS NULL")

def downgrade():
    op.drop_column('schedule_results', 'sr_unfinished_qty')
    op.drop_column('schedule_results', 'sr_completed_qty')
```

- [ ] **Step 3: 执行迁移**

Run: `cd e:\openaps\aps-hap\backend && alembic upgrade head`

- [ ] **Step 4: 验证数据库字段**

Run: `cd e:\openaps\aps-hap\backend && python -c "from sqlalchemy import inspect; from app.core.database import engine; ins = inspect(engine); cols = [c['name'] for c in ins.get_columns('schedule_results')]; print(cols); assert 'sr_completed_qty' in cols; assert 'sr_unfinished_qty' in cols; print('OK')"`

---

### Task 2: Pydantic Schema 更新

**Files:**
- Modify: `backend/app/schemas/schedule.py`

- [ ] **Step 1: 在 ScheduleResultBase schema 中添加新字段**

在 `backend/app/schemas/schedule.py` 中找到 ScheduleResult 相关的 schema 类，添加：

```python
    sr_completed_qty: int | None = 0
    sr_unfinished_qty: int | None = None
```

同时确保 `sr_status` 的描述反映新枚举值（待生产/已完成/已失效）。

- [ ] **Step 2: 验证导入无误**

Run: `cd e:\openaps\aps-hap\backend && python -c "from app.schemas.schedule import *; print('Schema OK')"`

---

### Task 3: 排产结果写入修改（_batch_write_tasks）

**Files:**
- Modify: `backend/app/services/schedule_service.py:934-952`

- [ ] **Step 1: 修改 _batch_write_tasks 中的 ScheduleResult 创建**

将 `sr_status="待确认"` 改为 `sr_status="待生产"`，并添加新字段：

```python
                sr = ORMScheduleResult(
                    plan_id=plan_id,
                    product_id=t.product_id or "",
                    process_id=t.process_id or "",
                    line_id=t.workcenter_id or "",
                    demand_id=t.order_item_id or t.item_id or None,
                    sr_date=sr_date_val,
                    sr_time_slot=time_slot_text or None,
                    sr_quantity=qty,
                    sr_status="待生产",
                    sr_completed_qty=0,
                    sr_unfinished_qty=qty,
                    process_code=t.process_code or None,
                    constraint_type=t.constraint_type or None,
                    seq=t.step_order or t.step_no or t.seq or None,
                    dependency_type=t.dependency_type or None,
                    wait_time=t.wait_time or None,
                    prep_time=t.prep_time or None,
                    sync_status=SyncStatus.PENDING_CREATE,
                )
```

- [ ] **Step 2: 验证后端启动无误**

Run: `cd e:\openaps\aps-hap\backend && python -c "from app.services.schedule_service import schedule_service; print('Service OK')"`

---

### Task 4: 排产确认 API（确认 + 生成报工单）

**Files:**
- Modify: `backend/app/services/schedule_service.py`
- Modify: `backend/app/api/v1/result.py`

- [ ] **Step 1: 在 schedule_service.py 中添加 confirm_schedule 方法**

在 ScheduleService 类中添加：

```python
    async def confirm_schedule(self, task_id: str) -> dict:
        """确认排产结果：状态改为待生产，并自动生成报工单。"""
        from app.models.entities import ORMScheduleResult, ORMReportWorkOrder
        async with async_session() as session:
            # 查找该 task_id 的排产结果
            result = await session.execute(
                select(ORMScheduleResult).where(ORMScheduleResult.plan_id == f"PLAN-{task_id}")
            )
            results = result.scalars().all()
            if not results:
                return {"confirmed": 0, "report_orders": 0}

            report_count = 0
            for sr in results:
                if sr.sr_status == "待确认":
                    sr.sr_status = "待生产"
                    sr.sync_status = SyncStatus.PENDING_UPDATE

                # 生成报工单（仅当状态为待生产且无已有报工单时）
                existing_rwo = await session.execute(
                    select(ORMReportWorkOrder).where(ORMReportWorkOrder.dispatch_id == sr.id)
                )
                if not existing_rwo.scalars().first():
                    rwo = ORMReportWorkOrder(
                        dispatch_id=sr.id,
                        product_id=sr.product_id,
                        process_id=sr.process_id,
                        line_id=sr.line_id,
                        rw_date=sr.sr_date,
                        rw_time_slot=sr.sr_time_slot,
                        rw_plan_qty=sr.sr_quantity,
                        rw_actual_qty=0,
                        rw_defect_qty=0,
                        rw_status="待报工",
                        sync_status=SyncStatus.PENDING_CREATE,
                    )
                    session.add(rwo)
                    report_count += 1

            await session.commit()

        logger.info("确认排产: task_id={}, 确认{}条, 生成报工单{}条", task_id, len(results), report_count)
        return {"confirmed": len(results), "report_orders": report_count}
```

- [ ] **Step 2: 在 result.py 中添加确认 API 端点**

在 `backend/app/api/v1/result.py` 中添加：

```python
@router.post("/{task_id}/confirm", summary="确认排产结果")
async def confirm_schedule(
    task_id: str,
    api_key: str = Depends(verify_api_key),
) -> dict:
    """确认排产结果，状态改为待生产，并自动生成报工单。"""
    return await schedule_service.confirm_schedule(task_id)
```

- [ ] **Step 3: 验证 API 端点可访问**

重启后端后，Run: `curl -s http://localhost:8001/api/v1/result/test-task/confirm -X POST -H "X-API-Key: test" | python -m json.tool`

---

### Task 5: 报工 API（回写排产单）

**Files:**
- Create: `backend/app/api/v1/report_work.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: 创建报工 API 路由文件**

创建 `backend/app/api/v1/report_work.py`：

```python
"""报工管理接口。"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from loguru import logger
from pydantic import BaseModel, Field

from app.core.security import verify_api_key
from app.core.database import async_session
from app.models.entities import ORMReportWorkOrder, ORMScheduleResult, SyncStatus
from sqlalchemy import select

router = APIRouter()


class ReportWorkRequest(BaseModel):
    """报工请求。"""
    rw_actual_qty: int = Field(..., ge=0, description="实际完成数量")
    rw_defect_qty: int = Field(0, ge=0, description="不良数量")
    rw_remark: str = Field("", max_length=200, description="备注")


@router.get("", summary="查询报工单列表")
async def list_report_works(
    status: str | None = None,
    api_key: str = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """查询报工单列表，支持按状态过滤。"""
    async with async_session() as session:
        stmt = select(ORMReportWorkOrder).order_by(ORMReportWorkOrder.created_at.desc())
        if status:
            stmt = stmt.where(ORMReportWorkOrder.rw_status == status)
        result = await session.execute(stmt)
        rows = result.scalars().all()
        return [
            {
                "id": rwo.id,
                "dispatch_id": rwo.dispatch_id,
                "product_id": rwo.product_id,
                "process_id": rwo.process_id,
                "line_id": rwo.line_id,
                "rw_date": str(rwo.rw_date) if rwo.rw_date else None,
                "rw_time_slot": rwo.rw_time_slot,
                "rw_plan_qty": rwo.rw_plan_qty,
                "rw_actual_qty": rwo.rw_actual_qty,
                "rw_defect_qty": rwo.rw_defect_qty,
                "rw_status": rwo.rw_status,
                "rw_remark": rwo.rw_remark,
            }
            for rwo in rows
        ]


@router.post("/{dispatch_id}", summary="报工")
async def report_work(
    dispatch_id: str,
    req: ReportWorkRequest,
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """单条报工，回写排产单的已完成数量和状态。"""
    async with async_session() as session:
        # 1. 查找报工单
        rwo_result = await session.execute(
            select(ORMReportWorkOrder).where(ORMReportWorkOrder.dispatch_id == dispatch_id)
        )
        rwo = rwo_result.scalars().first()
        if not rwo:
            raise HTTPException(status_code=404, detail="报工单不存在")

        if rwo.rw_status not in ("待报工",):
            raise HTTPException(status_code=400, detail=f"报工单状态为{rwo.rw_status}，不可报工")

        # 2. 查找关联的排产单
        sr_result = await session.execute(
            select(ORMScheduleResult).where(ORMScheduleResult.id == dispatch_id)
        )
        sr = sr_result.scalars().first()
        if not sr:
            raise HTTPException(status_code=404, detail="关联排产单不存在")

        if sr.sr_status not in ("待生产",):
            raise HTTPException(status_code=400, detail=f"排产单状态为{sr.sr_status}，不可报工")

        # 3. 校验报工数量
        unfinished = (sr.sr_quantity or 0) - (sr.sr_completed_qty or 0)
        if req.rw_actual_qty > unfinished:
            raise HTTPException(
                status_code=400,
                detail=f"报工数量({req.rw_actual_qty})超过未完成数量({unfinished})"
            )

        # 4. 更新报工单
        rwo.rw_actual_qty = req.rw_actual_qty
        rwo.rw_defect_qty = req.rw_defect_qty
        rwo.rw_remark = req.rw_remark
        rwo.rw_status = "已报工"
        rwo.sync_status = SyncStatus.PENDING_UPDATE

        # 5. 更新排产单
        sr.sr_completed_qty = (sr.sr_completed_qty or 0) + req.rw_actual_qty
        sr.sr_unfinished_qty = (sr.sr_quantity or 0) - sr.sr_completed_qty
        if sr.sr_completed_qty >= (sr.sr_quantity or 0):
            sr.sr_status = "已完成"
        sr.sync_status = SyncStatus.PENDING_UPDATE

        await session.commit()

    logger.info("报工完成: dispatch_id={}, actual_qty={}, 排产单状态={}", dispatch_id, req.rw_actual_qty, sr.sr_status)
    return {
        "dispatch_id": dispatch_id,
        "sr_completed_qty": sr.sr_completed_qty,
        "sr_unfinished_qty": sr.sr_unfinished_qty,
        "sr_status": sr.sr_status,
    }


@router.post("/daily-reset", summary="日终处理")
async def daily_reset(
    api_key: str = Depends(verify_api_key),
) -> dict[str, Any]:
    """日终处理：将昨天待生产的排产单改为已失效。"""
    from datetime import date
    from sqlalchemy import update

    today = date.today()
    expired_count = 0
    closed_rwo_count = 0

    async with async_session() as session:
        # 1. 查找 sr_status='待生产' 且 sr_date < 今天 的排产结果
        stmt = select(ORMScheduleResult).where(
            ORMScheduleResult.sr_status == "待生产",
            ORMScheduleResult.sr_date < today,
        )
        result = await session.execute(stmt)
        expired_results = result.scalars().all()

        for sr in expired_results:
            sr.sr_status = "已失效"
            sr.sr_unfinished_qty = (sr.sr_quantity or 0) - (sr.sr_completed_qty or 0)
            sr.sync_status = SyncStatus.PENDING_UPDATE
            expired_count += 1

            # 2. 关闭关联的待报工报工单
            rwo_stmt = select(ORMReportWorkOrder).where(
                ORMReportWorkOrder.dispatch_id == sr.id,
                ORMReportWorkOrder.rw_status == "待报工",
            )
            rwo_result = await session.execute(rwo_stmt)
            for rwo in rwo_result.scalars().all():
                rwo.rw_status = "已关闭"
                rwo.sync_status = SyncStatus.PENDING_UPDATE
                closed_rwo_count += 1

        await session.commit()

    logger.info("日终处理: 过期{}条排产单, 关闭{}条报工单", expired_count, closed_rwo_count)
    return {"expired_count": expired_count, "closed_rwo_count": closed_rwo_count}
```

- [ ] **Step 2: 在 main.py 中注册报工路由**

在 `backend/app/main.py` 中找到路由注册部分，添加：

```python
from app.api.v1.report_work import router as report_work_router
app.include_router(report_work_router, prefix="/api/v1/report-work", tags=["报工管理"])
```

- [ ] **Step 3: 验证 API 端点**

重启后端后，Run: `curl -s http://localhost:8001/api/v1/report-work/ -H "X-API-Key: test" | python -m json.tool`

---

### Task 6: 日终处理自动触发（lifespan）

**Files:**
- Modify: `backend/app/main.py`

- [ ] **Step 1: 在 lifespan 中添加日终处理自动触发**

在 `backend/app/main.py` 的 lifespan 函数中，在 startup 逻辑末尾添加：

```python
    # 日终处理：检查是否需要执行
    try:
        from datetime import date
        from app.core.database import async_session as _session_factory
        from sqlalchemy import text

        async with _session_factory() as session:
            result = await session.execute(text("SELECT value FROM system_config WHERE key='last_daily_reset_date'"))
            row = result.first()
            last_reset = row[0] if row else None

        today_str = date.today().isoformat()
        if last_reset != today_str:
            from app.services.schedule_service import schedule_service
            # 不直接调用 API，直接执行日终逻辑
            from app.models.entities import ORMScheduleResult, ORMReportWorkOrder, SyncStatus
            from sqlalchemy import select

            expired_count = 0
            async with _session_factory() as session:
                stmt = select(ORMScheduleResult).where(
                    ORMScheduleResult.sr_status == "待生产",
                    ORMScheduleResult.sr_date < date.today(),
                )
                result = await session.execute(stmt)
                for sr in result.scalars().all():
                    sr.sr_status = "已失效"
                    sr.sr_unfinished_qty = (sr.sr_quantity or 0) - (sr.sr_completed_qty or 0)
                    sr.sync_status = SyncStatus.PENDING_UPDATE
                    expired_count += 1

                    # 关闭关联报工单
                    rwo_stmt = select(ORMReportWorkOrder).where(
                        ORMReportWorkOrder.dispatch_id == sr.id,
                        ORMReportWorkOrder.rw_status == "待报工",
                    )
                    rwo_result = await session.execute(rwo_stmt)
                    for rwo in rwo_result.scalars().all():
                        rwo.rw_status = "已关闭"
                        rwo.sync_status = SyncStatus.PENDING_UPDATE

                await session.commit()

                # 记录执行日期
                await session.execute(text(
                    f"INSERT OR REPLACE INTO system_config (key, value) VALUES ('last_daily_reset_date', '{today_str}')"
                ))
                await session.commit()

            logger.info("启动时日终处理: 过期{}条", expired_count)
    except Exception as e:
        logger.warning("启动时日终处理失败: {}", str(e))
```

注意：需要先检查 `system_config` 表是否存在，如不存在需在迁移中创建。

- [ ] **Step 2: 在迁移中添加 system_config 表**

在迁移脚本中添加：

```python
    op.create_table(
        'system_config',
        sa.Column('key', sa.String(100), primary_key=True),
        sa.Column('value', sa.String(500), nullable=True),
    )
```

---

### Task 7: 未完成数量结转排产

**Files:**
- Modify: `backend/app/services/schedule_service.py` — `_fetch_demand_plans` 方法

- [ ] **Step 1: 在 _fetch_demand_plans 中添加未完成需求查询**

在 `schedule_service.py` 的 `_fetch_demand_plans` 方法末尾，return 之前添加结转逻辑：

```python
        # ── 结转未完成需求 ──
        from app.models.entities import ORMScheduleResult
        carryover_stmt = select(ORMScheduleResult).where(
            ORMScheduleResult.sr_status == "已失效",
            ORMScheduleResult.sr_unfinished_qty > 0,
        )
        carryover_result = await session.execute(carryover_stmt)
        carryover_rows = carryover_result.scalars().all()

        if carryover_rows:
            # 按 demand_id 分组
            carryover_by_demand: dict[str, list] = {}
            for sr in carryover_rows:
                did = sr.demand_id or "unknown"
                carryover_by_demand.setdefault(did, []).append(sr)

            for did, sr_list in carryover_by_demand.items():
                # 查找原始需求计划的优先级
                orig_priority = "中"
                if did in demand_map:
                    orig_priority = demand_map[did].priority or "中"

                # 按产品分组（同一需求可能有多个产品）
                product_groups: dict[str, int] = {}
                for sr in sr_list:
                    product_groups[sr.product_id] = product_groups.get(sr.product_id, 0) + (sr.sr_unfinished_qty or 0)

                for pid, qty in product_groups.items():
                    import uuid
                    carryover_dp = DemandPlan(
                        id=str(uuid.uuid4()),
                        product_id=pid,
                        quantity=qty,
                        due_date=(date.today() + timedelta(days=1)).isoformat(),
                        priority=orig_priority,
                        dp_code=f"UNFINISHED-{did[:8]}",
                        is_carryover=True,
                    )
                    demand_plans.append(carryover_dp)

            logger.info("结转未完成需求: {}条需求, 合并{}条临时需求计划", len(carryover_by_demand), len(demand_plans) - original_count)
```

- [ ] **Step 2: 在 DemandPlan 模型中添加 is_carryover 字段**

在 `backend/app/engine/models.py` 的 DemandPlan 类中添加：

```python
    is_carryover: bool = False  # 是否为结转需求
```

- [ ] **Step 3: 在优先级权重计算中考虑结转**

在 `constraint_builder.py` 的优先级权重计算处，找到 `priority_weights` 赋值的位置，添加结转优先级提升：

```python
            # 结转需求在同优先级内略微提升权重
            base_weight = priority_weight_map.get(item.priority, 1.0)
            if getattr(item, 'is_carryover', False):
                base_weight += 0.1  # 同优先级内未完成优先
            priority_weights[idx] = base_weight
```

---

### Task 8: result.py API 返回新字段

**Files:**
- Modify: `backend/app/api/v1/result.py`

- [ ] **Step 1: 在 cells 构建中添加 completedQty/unfinishedQty/status**

在 result.py 中构建 cells 的代码块中，每个 cell 添加：

```python
                "completedQty": 0,  # 排产时不填，从 schedule_results 表查询时填充
                "unfinishedQty": 0,
                "status": "待生产",
```

- [ ] **Step 2: 在 _fetch_result_from_hap 中添加新字段**

在 HAP 读取结果时，从行数据中提取 `sr_completed_qty`、`sr_unfinished_qty`：

```python
            cells.append({
                ...existing fields...,
                "completedQty": int(_float_val(r.get("sr_completed_qty", 0))),
                "unfinishedQty": int(_float_val(r.get("sr_unfinished_qty", 0))),
                "status": _str_val(r.get("sr_status", "待生产")),
            })
```

---

### Task 9: 前端 - 排产结果页面更新

**Files:**
- Modify: `frontend/src/components/CrudPage/index.tsx`

- [ ] **Step 1: 在排产结果表格配置中添加新列**

找到排产结果的 CrudPage 配置（通常在 ScheduleResult 相关页面），添加列：

```typescript
{ title: '已完成数量', dataIndex: 'sr_completed_qty', key: 'sr_completed_qty', width: 100 },
{ title: '未完成数量', dataIndex: 'sr_unfinished_qty', key: 'sr_unfinished_qty', width: 100 },
{
  title: '状态', dataIndex: 'sr_status', key: 'sr_status', width: 100,
  render: (status: string) => {
    const colorMap: Record<string, string> = {
      '待生产': 'blue',
      '已完成': 'green',
      '已失效': 'default',
    };
    return <Tag color={colorMap[status] || 'default'}>{status}</Tag>;
  }
},
```

- [ ] **Step 2: 添加排产确认按钮**

在排产结果页面顶部添加"确认排产"按钮，调用 `POST /api/v1/result/{task_id}/confirm`。

---

### Task 10: 前端 - 报工管理页面

**Files:**
- Create: `frontend/src/pages/ReportWork/index.tsx`
- Modify: `frontend/src/router/index.tsx`

- [ ] **Step 1: 创建报工管理页面**

创建 `frontend/src/pages/ReportWork/index.tsx`，基于 CrudPage 组件，配置：

```typescript
const config = {
  tableName: 'report_work_orders',
  title: '报工管理',
  columns: [
    { title: '派工单号', dataIndex: 'dispatch_id', key: 'dispatch_id' },
    { title: '产品', dataIndex: 'product_id', key: 'product_id' },
    { title: '工序', dataIndex: 'process_id', key: 'process_id' },
    { title: '产线', dataIndex: 'line_id', key: 'line_id' },
    { title: '计划数量', dataIndex: 'rw_plan_qty', key: 'rw_plan_qty' },
    { title: '实际数量', dataIndex: 'rw_actual_qty', key: 'rw_actual_qty' },
    { title: '不良数量', dataIndex: 'rw_defect_qty', key: 'rw_defect_qty' },
    { title: '状态', dataIndex: 'rw_status', key: 'rw_status',
      render: (s: string) => <Tag color={s === '待报工' ? 'blue' : s === '已报工' ? 'green' : 'default'}>{s}</Tag>
    },
  ],
  // 自定义操作列：报工按钮
  customActions: true,
};
```

添加报工对话框：点击"报工"→ Modal 输入实际完成数量 → 调用 `POST /api/v1/report-work/{dispatch_id}`

- [ ] **Step 2: 在路由中添加报工页面**

在 `frontend/src/router/index.tsx` 中添加：

```typescript
import ReportWork from '../pages/ReportWork';
// 在路由配置中添加
{ path: '/report-work', element: <ReportWork /> },
```

在菜单配置中添加"报工管理"菜单项（生产数据子菜单下）。

---

### Task 11: 集成测试

**Files:**
- Create: `backend/test_simulation.py` (临时，测试后删除)

- [ ] **Step 1: 编写集成测试脚本**

创建 `backend/test_simulation.py`：

```python
"""排产仿真流程集成测试"""
import asyncio
import httpx

BASE = "http://localhost:8001/api/v1"
HEADERS = {"X-API-Key": "test"}

async def test_full_flow():
    async with httpx.AsyncClient() as client:
        # 1. 触发排产
        print("1. 触发排产...")
        resp = await client.post(f"{BASE}/schedule/", json={"start_date": "2026-07-12", "end_date": "2026-08-12"}, headers=HEADERS)
        data = resp.json()
        task_id = data.get("task_id")
        print(f"   task_id={task_id}")

        # 2. 等待排产完成
        import time
        for _ in range(30):
            time.sleep(2)
            resp = await client.get(f"{BASE}/schedule/{task_id}/status", headers=HEADERS)
            status_data = resp.json()
            status = status_data.get("status", "")
            if status == "SUCCESS":
                break
        print(f"   status={status}")

        # 3. 确认排产
        print("2. 确认排产...")
        resp = await client.post(f"{BASE}/result/{task_id}/confirm", headers=HEADERS)
        print(f"   {resp.json()}")

        # 4. 查询报工单
        print("3. 查询报工单...")
        resp = await client.get(f"{BASE}/report-work/?status=待报工", headers=HEADERS)
        report_orders = resp.json()
        print(f"   报工单数: {len(report_orders)}")

        # 5. 报工（取第一条报工单，填写实际完成数量）
        if report_orders:
            rwo = report_orders[0]
            dispatch_id = rwo["dispatch_id"]
            plan_qty = rwo["rw_plan_qty"]
            actual_qty = max(0, plan_qty - 5)  # 留5个未完成

            print(f"4. 报工: dispatch_id={dispatch_id}, plan={plan_qty}, actual={actual_qty}")
            resp = await client.post(f"{BASE}/report-work/{dispatch_id}", json={
                "rw_actual_qty": actual_qty,
                "rw_defect_qty": 0,
                "rw_remark": "测试报工",
            }, headers=HEADERS)
            print(f"   {resp.json()}")

        # 6. 日终处理
        print("5. 日终处理...")
        resp = await client.post(f"{BASE}/report-work/daily-reset", headers=HEADERS)
        print(f"   {resp.json()}")

        print("\n=== 测试完成 ===")

asyncio.run(test_full_flow())
```

- [ ] **Step 2: 运行测试**

确保后端运行在 8001 端口，然后：

Run: `cd e:\openaps\aps-hap\backend && python test_simulation.py`

- [ ] **Step 3: 验证数据状态**

检查：
- 排产结果 sr_status 正确变为"待生产"
- 报工单自动生成且 rw_status="待报工"
- 报工后 sr_completed_qty 正确更新
- 日终处理后昨天待生产→已失效，sr_unfinished_qty 正确计算

- [ ] **Step 4: 清理测试脚本**

Delete: `backend/test_simulation.py`

---

### Task 12: HAP 字段同步

**Files:**
- Modify: `backend/app/hap/client.py` — sync_service 中字段映射
- Modify: `backend/deploy/worksheet_ids_v2.json` — 如需更新 HAP 字段

- [ ] **Step 1: 更新 sync_service 中 schedule_results 的字段映射**

在 `sync_service.py` 的 `_get_field_mappings` 或类似方法中，为 schedule_results 添加新字段映射：

```python
    "schedule_results": {
        ...existing mappings...,
        "sr_completed_qty": {"alias": "sr_completed_qty", "type": "Number"},
        "sr_unfinished_qty": {"alias": "sr_unfinished_qty", "type": "Number"},
        "sr_status": {"alias": "sr_status", "type": "SingleSelect", "options": ["待生产", "已完成", "已失效"]},
    }
```

- [ ] **Step 2: 通过 HAP API 添加新字段到 schedule_result 工作表**

如果 HAP 工作表中没有这些字段，使用 `update_worksheet_structure` 添加：

```python
# 通过 API 添加字段（如尚未在 HAP 中创建）
addFields = [
    {"id": "", "type": "Number", "name": "已完成数量", "alias": "sr_completed_qty"},
    {"id": "", "type": "Number", "name": "未完成数量", "alias": "sr_unfinished_qty"},
]
```

- [ ] **Step 3: 验证 HAP 同步**

触发一次同步，检查 HAP 中排产结果表是否包含新字段值。
