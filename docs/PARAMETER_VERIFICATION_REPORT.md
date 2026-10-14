# 产品工艺参数验证报告

**生成日期**: 2026-07-19
**验证目标**: 严格按照 CLAUDE.md 要求，建立参数验证机制，对每个工序的时间参数进行独立核对与交叉验证

## 一、验证范围与方法

### 验证范围
1. **三时间参数**：cycle_time（节拍时间，秒）、prep_time（准备时间，分钟）、wait_time（等待时间，分钟）
2. **全链路追踪**：数据库存储 → 数据加载 → 约束构建 → 求解器 → 报告显示
3. **重点关注工序**：老化测试（用户报告"组装/老化/包装同天排产"问题）

### 验证方法
- **独立核对**：直接查询 PostgreSQL 数据库，绕过应用层
- **交叉验证**：对比数据库值、ORM加载值、求解器实际使用值
- **物理合理性**：cycle_time × 工作时间 vs 资源日历产能

---

## 二、三时间参数数据库存储验证

### 2.1 老化测试工序（PROC-BUR-01）产品工艺参数

| 产品 | seq | cycle_time(s) | prep_time(分) | wait_time(分) | auto_type | max_units | dep_type |
|------|-----|---------------|---------------|---------------|-----------|-----------|----------|
| PROD-5G-01 | 6 | 1440.0 | 0.0 | 0.0 | 非自动 | 200 | FS |
| PROD-AIDC-01 | 7 | 420.0 | 30.0 | 0.0 | 非自动 | 1 | FS |
| PROD-OPT-01 | 8 | 720.0 | 0.0 | 0.0 | 非自动 | 200 | FS |

**验证结论**：
- ✅ 数据库 ProductProcess 表正确存储三时间参数
- ✅ 老化测试 wait_time=0（用户确认正确："我说错了，老化是节拍时间较长"）
- ⚠️ cycle_time 跨度大（420~1440秒），物理产能差异显著

### 2.2 三参数加载链路验证

| 阶段 | 文件 | 函数 | 验证结果 |
|------|------|------|----------|
| ORM 模型 | `app/models/entities.py:55-69` | ProductProcess | ✅ cycle_time/prep_time/wait_time 字段定义正确 |
| 数据加载 | `app/services/schedule_service.py:_fetch_product_processes` | - | ✅ 直接读取 ORM 字段 |
| 约束构建 | `app/engine/constraint_builder.py:319-322` | ExpandedItem 创建 | ✅ `cycle_time=pp.cycle_time if pp.cycle_time else 0.0` 忠实加载 |
| DAG 延迟计算 | `app/engine/constraint_builder.py:_calc_delay_slots` | FS依赖 | ✅ wait_time=0 时返回 (1, 0)，允许同天排产 |
| 求解器 | `app/engine/solver_ortools.py:_solve_capacity` | 产能约束 | ✅ `model.Add(sum(prod_vars) <= cap)` 正确施加 |
| 快照捕获 | `simulation/common.py:_init_gantt_entry` | 甘特图数据 | ✅ 已增加6个参数字段（V3.2修复） |
| 报告显示 | `simulation/generate_report.py:bar_html` | 甘特图tooltip | ✅ 已显示三时间参数（V3.2修复） |

---

## 三、产能约束根因分析

### 3.1 现象
- test1_report.html / test2_report.html 显示老化测试在 2026-07-22 排产 729 件
- 资源日历产能 190 件/天
- 729/190 ≈ 3.84 倍超产

### 3.2 假设与验证

**假设H1**：求解器产能约束被违反
- 验证方式：直接查询数据库 ScheduleResult 表
- 验证结果：**H1 不成立**
- 证据：2026-07-22 当天 6 个 plan_id 的排产记录明细：

| plan_id | 记录数 | 总数量 | 是否超产 |
|---------|--------|--------|----------|
| PLAN-049732b9 | 2 | 190 | ✅ 等于上限 |
| PLAN-8a851e4b | 3 | 190 | ✅ 等于上限 |
| PLAN-a06acf4b | 4 | 190 | ✅ 等于上限 |
| PLAN-9cc3c193 | 2 | 122 | ✅ 未超 |
| PLAN-4d9fda7a | 3 | 32 | ✅ 未超 |
| PLAN-c59237d3 | 2 | 5 | ✅ 未超 |
| **合计** | **16** | **729** | ❌ 假象超产 |

**每个 plan 单独看都符合 ≤190 件/天的产能约束，但报告读取时未按 plan_id 过滤，累加显示 729 件/天，造成"超产"假象。**

**假设H2**：报告读取时未按 plan_id 过滤
- 验证方式：检查 generate_report.py 数据读取逻辑
- 验证结果：**H2 成立**（待修复）

### 3.3 真正根因

1. **求解器无BUG**：每个 plan 内产能约束正确施加，`sum(prod_vars) <= cap=190`
2. **数据累积**：仿真期间每次排产创建新 SchedulePlan，但旧 ScheduleResult 未被清理
3. **报告BUG**：generate_report.py 读取所有 ScheduleResult 而未按 plan_id 过滤

---

## 四、老化能否当天完成的物理核实

### 4.1 cycle_time 物理产能计算

工作时间：12小时/天 = 43200秒/天
老化设备：equipment_count=2

| 产品 | cycle_time(s) | 单机产能(件/天) | 双机合计(件/天) | 资源日历产能(件/天) | 物理一致性 |
|------|---------------|-----------------|-----------------|---------------------|------------|
| PROD-5G-01 | 1440 | 30.00 | 60.00 | 189.96 | ❌ 资源日历是物理产能的3.17倍 |
| PROD-AIDC-01 | 420 | 102.86 | 205.71 | 189.96 | ✅ 资源日历 ≈ 物理产能 |
| PROD-OPT-01 | 720 | 60.00 | 120.00 | 189.96 | ❌ 资源日历是物理产能的1.58倍 |

### 4.2 老化能否当天完成的结论

| 产品 | 单次排产量(最大) | 物理双机产能 | 能否当天完成 |
|------|------------------|--------------|--------------|
| PROD-5G-01 | 188件（SIM-14D-011） | 60件/天 | ❌ **不可能当天完成**，需3.13天 |
| PROD-AIDC-01 | 163件（SIM-14D-001） | 205件/天 | ✅ 可以当天完成 |
| PROD-OPT-01 | - | 120件/天 | ⚠️ 视具体排产量 |

### 4.3 数据配置问题

1. **资源日历产能配置不合理**：190件/天 与具体产品的 cycle_time 物理产能不匹配
2. **资源日历与 cycle_time 解耦**：资源日历基于"通用产能"配置，未按产品 cycle_time 计算
3. **equipment_count 未乘入capacity**：代码 `cap = ts.available_capacity` 直接使用日历值，未乘以 equipment_count

---

## 五、CLAUDE.md 规则回顾与反思

### 5.1 此前自测试问题
CLAUDE.md 第4条"Goal-Driven Execution"要求："Define success criteria. Loop until verified."

**此前问题**：
- 仅看报告结果（"组装/老化/包装同天排产"），未深入验证数据库实际数据
- 假设"产能被超产"是求解器BUG，未先核实数据来源
- 没有建立参数验证机制，导致"380件超产"假象持续多轮未被发现

### 5.2 本次验证改进
按照 CLAUDE.md 第1条"Think Before Coding"要求：

1. **State assumptions explicitly**：明确列出 H1/H2 两个假设
2. **If multiple interpretations exist, present them**：产能不匹配可能是单机/合计两种解释
3. **Surface tradeoffs**：揭示资源日历与 cycle_time 解耦的设计权衡

### 5.3 后续修复方向
按照 CLAUDE.md 第3条"Surgical Changes"要求：
- 仅修复报告读取逻辑（按 plan_id 过滤）
- 不修改求解器（求解器无BUG）
- 不修改资源日历数据（属于业务配置，需用户决策）

---

## 六、附录：验证脚本清单

| 脚本 | 用途 | 关键发现 |
|------|------|----------|
| `verify_capacity_root_cause.py` | 根因验证 | H2成立：资源日历是工作中心级，equipment_count未乘 |
| `verify_schedule_results.py` | 实际排产核实 | 2026-07-22 有6个plan_id叠加，单plan≤190件 |
| `verify_plan_overlap.py` | plan_id分布核实 | 每个plan单独符合约束，累加造成超产假象 |
| `verify_aging_cycle_time.py` | cycle_time物理产能 | PROD-5G-01 cycle_time=1440s，物理产能60件/天 |
| `verify_calendar_full.py` | 资源日历配置 | 仿真期190件/天，与cycle_time物理产能不匹配 |

---

## 七、验证签字

- ✅ 数据库存储验证：通过
- ✅ 三参数加载链路：通过
- ✅ 求解器约束施加：通过
- ✅ 报告显示三参数：通过（V3.2已修复）
- ❌ 报告按plan_id过滤：未通过（待修复）
- ⚠️ 资源日历与cycle_time一致性：未通过（数据配置问题，待用户决策）
