# MPS 改造计划 2 执行记录与经验教训（核算内核）

- 日期：2026-10-14（晚间收工记录）
- 分支：`mps-rework`
- 计划：`docs/superpowers/plans/2026-10-14-mps-rework-plan2-calc-kernel.md`

## 一、执行摘要

| 项 | 结果 |
|---|---|
| 完成范围 | Task 1~4 / 共 6（Task 5 官方周负荷算例+疑点双档、Task 6 收尾 未开始） |
| 测试基线 | **96 passed, 1 skipped**（内嵌 Python 3.13.5；PG 用例按需跳过） |
| 提交序列 | `61bd34a` `89c2d8e`(T1) → `1dbcff2` `676459b`(T2) → `7db6130` `0b1d5e4`(T3) → `f07fc70` `28e1508`(T4) |
| 交付物 | `app/mps/kernel.py`（单点函数 + calc_order 主体 + 甘特 + 告警，官方算例对齐）、`app/mps/load.py`（周负荷 + 产线瓶颈）、`app/mps/context.py`（DB→内核输入）、4 个测试文件（37 用例） |

**官方算例实测（M02-2D）**：T单件=6 / 加急=4；瓶颈 DB 自动 100 只/天；成品率 0.9507210075；放量比 1.052；投料 1052；批量周期 16；瓶颈占用 11；交付 17（含缓冲 1）；最晚投料 2026-12-14 —— 全部与 V1.6 表6 一致，并经实现者 Node 实跑 engine.js 逐项对照。

## 二、关键决策记录

1. **移植源精读先行**：编制计划时全文读取 `engine.js`（242 行）与 `schedule.js` 关键函数，把移植规格以逐字代码块内嵌计划——执行阶段"读计划即得规格"，效率与保真度双高。
2. **round_mode 默认修正为 `ceil`**（编制期发现参数默认与移植源行为矛盾——M02-2D=16 依赖此）。
3. **ramp_trigger 增加第三档 `first_only`**（Task 2 质量审查发现 check-list CHK-CYCLE-009B"仅首单"无法表达）。
4. **pick_mode 改为按名称分流**（Task 3 质量审查：依赖 modes 行序在明道云同步后是静默错误路径——反转行序时 qty=10 会错选自动档，通量 3 倍偏差）。
5. **load.py 独立成模块**（与 kernel 的"纯核算"边界清晰；评审确认保留）。
6. **对 mps-web 的有意差异全部参数化且文档化**：`round_mode`（ceil/exact）、`order_buffer_days`（1/0）、`ramp_trigger`（三档）、`wb_auto_flux_override`（0/12000/20000）；engine.js 微观差异（nz 空白串、缺参非数值串、total_extra 未移植等）在模块 docstring 留痕。

## 三、经验教训（来自真实事件）

1. **跨语言对照验证是移植类任务的最强证据**：Task 2 实现者主动用 Node 实跑 `engine.js` 与 Python 内核逐项对照（并复现出"差值恰为文档化的缓冲参数"）——建议后续移植任务标配该做法。
2. **两段审查持续抓获实质问题**（全部为审查发现）：
   - T1：`CHK-FLUX-018` 编号不存在（引用必须对照清单实际编号）；`ramp_flux_factor` 无调用方需留痕；
   - T2：`ramp_trigger` 缺档（009B 不可实现）；`yield_005` 测试名不符实（迭代循环数学上不可达，应钉住字段语义并注明）；甘特/告警零断言；扩展与裁剪点需在 docstring 全面留痕；
   - T3：`pick_mode` 行序依赖（静默错误结果路径）；非法参数静默归 0（比缺失更危险——改为回退 PARAM_DEFS 默认）；
   - T4：`line_bottleneck` 零覆盖，且按现 fixture 直接调用会 `KeyError`（fixture 与生产契约存在 gap——补测时同步修正 fixture）。
3. **计划计数笔误**：Task 2 写"预期 10 passed"，实际代码块是 9 个测试——计数必须以代码块统计为准，不能目测。
4. **"质量跟进"小提交模式有效**：每个任务评审后的修正独立成提交（`89c2d8e`/`676459b`/`0b1d5e4`/`28e1508`），可追溯、可回滚、评审闭环。
5. **参数默认值必须对照移植源实测行为验证**（round_mode 教训），不能凭文档推断；参数语义（如 wb 覆盖同时作用于 mean/peak）需在代码注释/参数 hint 说明。
6. **文档镜像纪律**：计划代码块与实现保持逐字镜像（含后续修正回写），本计划 6 次镜像回写全部完成。

## 四、未决事项与续跑指南

**下一步（Task 5，注意点）：**
1. 官方周负荷算例（M01-2DS 2.64/3.08/0.88）：先做**数据复原调查**——逻辑书 §九第二段数字与单订单推算不吻合（94860÷36000 等三数分母不同），需从 V1.7 周计划示例区找齐参与订单；无法复原时按计划 BLOCKED 路径报告。
2. 疑点双档补齐：`wb_auto_flux_override` 12000/20000（FLUX-015A/B）；其余双档（003/005/009）已在 T2/T3 覆盖。
3. Task 6 收尾：
   - 与 engine.js 逐段对照抽查（周期/通量/交付三段）；
   - **check-list 测试路径回写**：CALC/CYCLE/YIELD/FLUX/DELIVERY/LOAD 条目的"测试用例"列当前指向不存在的 `test_kernel_cycle.py` 等文件——必须核对回写到真实用例（含状态改"通过"，双档疑点标"已实现双档"）。

**低优先遗留：**
- `ramp_flux_factor` 暂无调用方（计划 3/5 接入）；
- order 优先级透传字段裁剪（计划 3 排产前确认是否需要补回）；
- Task 7（计划1）遗留的 3 个种子小测试

**运行命令（backend 目录）：**
```powershell
& "D:\aps-hap\offline\runtime\python\python.exe" -m pytest tests -v
```

## 五、Task 6 收尾记录（2026-10-14）

- engine.js 逐段对照（周期/通量/交付）：周期段（js 86-99）与交付段默认档（js 148-156）逐行等价；通量段（js 120-140）等价，差异均为记录化扩展（wb_auto_flux_override、pick_mode 按名称分流、buffer/latest_start_date/ramp 三档），未发现未文档化偏差。
- 全量回归：105 passed, 1 skipped
- 清单穷尽性：CALC/CYCLE/YIELD/FLUX/DELIVERY/LOAD 共 59 条（73 处测试引用经 `pytest --collect-only` 核对全部存在；DELIVERY-007/FLUX-016B 为预期未实现项）
- 遗留：ramp_flux_factor 集成调用点（计划3/5）；order 优先级透传字段（计划3确认）
