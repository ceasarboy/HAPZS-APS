# MPS 改造计划 3 执行记录与经验教训（3A：优先级与策略层）

- 日期：2026-10-14
- 分支：`mps-rework`
- 计划：`docs/superpowers/plans/2026-10-14-mps-rework-plan3a-priority-strategy.md`

## 一、执行摘要（3A）

| 项 | 结果 |
|---|---|
| 完成范围 | Task 1~6 全部完成（3B：排产解码与求解 未开始） |
| 测试基线 | **139 passed, 1 skipped**（内嵌 Python 3.13.5） |
| 提交序列 | `afaa82c` `0138165`（Task1/2）→ `8a49226` `b36eeae` `f646c17`（Task3+跟进）→ `baf1016` `4599499`（Task4+跟进）→ `db88703` `7c5e170`（Task5+跟进） |
| 交付物 | `dates.py`（共享日期工具，JS 半上取整复刻）、`priority.py`（6 因子评分/P0-P3/8 级全序/重算/拖拽，383 行移植）、`priority_service.py`（置顶/到期/拖拽/审计/批量撤销，异步 ORM）、`strategy.py`（5 策略/指标/得分/配置 schema，257 行移植）；check-list PRIO-001~008 回写为"通过" |
| 接口落地 | kernel `order` 优先级透传（计划 2 遗留清理）：id/prio_level/prio_score/prio_source/prio_manual/pinned/pinned_at（`_fmt_dt` 归一化）/sort_no/status；计划 2 文档镜像同步 |

## 二、关键决策记录

1. **并发乐观锁决策**：拖拽/置顶的 `expected_prio_updated_at` → 409 语义由后续 API 层实现（对齐 mps-web server.js）；本服务层已维护 `prio_updated_at` 供比对。
2. **makespan 锚点加固**：`strategy_metrics` 锚点改为"首个有 start_date 的非 error 行"（JS 用 `planned[0]`，error 首行时塌缩为 0）——授权加固先例。
3. **due_buffer_days 语义留痕**：实测对排序无观察效果（匀移保持相对序；remain 分支为 JS 同源死代码）——保留参数对齐配置面，语义决策留 3B。
4. **pinned_at 类型纪律**：kernel 透传统一 `_fmt_dt` → `'YYYY-MM-DD'` 字符串（比较器第 2 级依赖字符串比较，禁止 datetime 直通）；`pinned` 用 `bool(nz(...))` 防 `"0"` 型字符串。

## 三、经验教训（本批次真实事件）

1. **审查再次抓到真问题**：`to_date` 的 datetime 子类陷阱（date−datetime 崩溃链）、kernel `pinned_at` 混型排序崩溃、`reorder_and_log` 状态守卫与 pin 不对称（暂停工单可拖入置顶组）、`result_key` 对 `delivery:None` 的 AttributeError、makespan error 首行塌缩、空断言（`is not None` 恒真）——全部为审查/复核发现。
2. **"计划笔误三连"**：Task 2 计数（10→9）、Task 5 计数（6→5）、Task 3 全量预估（127→122）——均因目测计数。**教训：计划中的测试计数必须用脚本统计代码块 `def test_` 数量，不能手写估算。**
3. **镜像纪律的边界**：Task 5 的实现段是"提示式规格"（无逐字代码块），镜像改为"执行结果补记+评审跟进"小节；有代码块的任务维持逐字镜像。规则明确后维护成本可控。
4. **子代理网络闪断**：一次派发 EHOSTUNREACH 失败 → 重试即通（与 git push 闪断同一模式：本地先行、失败即重试）。

## 四、未决事项与续跑指南（计划 3B）

**3B 范围（下一步）**：schedule.js 解码层移植（`scheduleProcessConstrained/allocEarliest/opWork/resource_key/op_key/gantt_chart` + 非容量时间线分支）、order_operations 分解与返工追加（SCHED-005/006）、kanban.js 看板、aps.js（gate 启发式/局部搜索）+ **GA 求解核心（DEAP 可配置；确定性基准=策略 orderFn+解码器；CP-SAT 适配延后并在文档标注）**、SCHED-010 批次落库（schedule_batch/allocations）、SCHED 清单回写。

**3B 开工前注意（从 3A 传递）**：
1. `get_strategy(id, p)["orderFn"](results, opts)` 为排序契约；`order_by_priority` 走 `sort_results(results)` 默认 `week_days=6`——3B 需将 ctx 的 `week_days` 传入比较器（`partial` 或 opts 透传），否则自定义 week_days 下排序键口径不一致；
2. `strategy_metrics` 的 `planned` 必须携带 `plan`（解码层产物）——3A 指标契约已就绪；
3. kernel 结果 `gantt.bars` 的 `mode` 字段供 `opKey/resourceKey` 复用（`f"{level}|{op}|{mode}"` 与账本键一致）；
4. 确定性基准验收 = 策略 orderFn + 解码器输出与 mps-web 一致（SCHED-009）；GA 固定种子可复现（预案已在设计 §3）。

**低优先遗留**：`get_strategy_config_values` 全 schema 遍历测试、orderFn 各策略乱序稳定性（随 3B 顺带）。
