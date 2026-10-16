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

---

# MPS 改造计划 3 执行记录与经验教训（3B1：排产解码与工序需求）

- 日期：2026-10-16
- 分支：`mps-rework`
- 计划：`docs/superpowers/plans/2026-10-14-mps-rework-plan3b1-schedule-ops-kanban.md`

## 一、执行摘要（3B1）

| 项 | 结果 |
|---|---|
| 完成范围 | Task 1~5 全部完成（3B2：APS/GA/求解与批次落库 未开始） |
| 测试基线 | **166 passed, 1 skipped**（内嵌 Python 3.13.5） |
| 计数轨迹 | 139（3A）→ 146（T1）→ 153（T2）→ 157（T3 初）→ 160（T3 跟进）→ 163（T4 初）→ 166（T4 跟进） |
| 交付物 | `schedule.py`（399 行：alloc_earliest/op_work/定序正排/非容量分支/甘特）、`operations.py`（109 行：D12 工序级需求分解与返工追加）、`kanban.py`（143 行：日任务看板）；新增测试 27（schedule 14 / operations 7 / kanban 6） |
| 对照抽查 | schedule 三段逐行 + kanban 全量逐行通过；`alloc_earliest` Node↔Python 差分探针 6 例输出全等（见二-7） |

| 任务 | 提交（实现 / 跟进 / 文档镜像） |
|---|---|
| T1 账本分配 | `57aa7a1` / `804d7d0` / `ec324b7`（夹具修正镜像） |
| T2 定序排产+甘特 | `407748d` / `1194117` / `2c45bcf`（护栏补缺+计数修正） |
| T3 operations | `7569e59` / `d8da1dc`（跟进含镜像） |
| T4 kanban | `2fbb942` / `1b8a399`（跟进含镜像） |
| T5 收尾 | 本提交（对照抽查 + 执行记录；哈希见 git log 末条） |

## 二、关键决策与偏离留痕

1. **WB 良率夹具修正（0.98，Node 实证）**：计划 Task1 夹具 WB=0.99（0.97×0.99=0.9603 → Q=1042）与全计划"Q=1052"类断言矛盾；开工前用 Node engine.js 实跑实证后修正为 0.98（0.97×0.98=0.9506 → Q=⌈1000×1.05197⌉=1052），`ec324b7` 镜像计划 + 测试留痕注释。
2. **schedule 4 项偏离（JS 死分支/边界修正，均已入 docstring）**：
   ① kit_adjusted 取 kit_offset>0（JS 的 `diffDays(start, kit) < 0` 为恒假死分支，齐套门槛实际生效时应标注调整）；
   ② gantt_chart 有界产能模式下无 from/to 的条按 base 回退（JS 按 plan.start_date，前置分部件会与首道工序重叠；本实现要求前置条先于首道工序完工）；
   ③ 护栏位置：缺 WC 护栏置于 op_work 之后、fluxOf 登记与产能分配之前（跳过条不登记 fluxOf，仅记 warnings）；
   ④ first_start 全无时回退 `add_days(base, kit_offset)`（T2 跟进修正 `1194117`，原实现回退 base）。
3. **护栏 [扩展]（偏离 JS：缺 WC 不挂死）**：op_work 得 flux=1e-9 时跳过产能分配并记 warnings（否则 `ceil_int(amt/1e-9)` → grow 6.3e13 行挂死，JS 同病）；配套 cap 核验对无 steps 资源键（手工条）回退 fluxOf（JS 取 1e-9 会误报超载）。
4. **Task3 三项修复（质量跟进 `d8da1dc`）**：① `sync_order_operations` 拒绝 error/缺 steps 的 calc_result（防误删重建）；② `merge_manual_bars` 先剥离既有手工条（重复调用幂等）；③ 显式 mode 按 mode_name 精确匹配取产能、无匹配 flux=None（走解码护栏）。
5. **kanban 4 项适配（micro 差异，已入 docstring）**：① `Math.round` → `js_round`（半上舍入 floor(x+0.5)；Python 银行家舍入边界不一致）；② ledger 索引显式守卫 `0 <= q_idx < len`（JS undefined→0；Python 负索引会绕到尾部）；③ base 缺省 `date.today()`（本地时区）vs JS UTC，跨日边界微差；④ groups 平局按 op 码点序（JS localeCompare 依赖语言环境）。
6. **Task4 测试补强（`1b8a399`）**：无效日期错误分支（无 groups）、负索引守卫（对照 JS undefined→0 不变式）、状态梯（超负荷>延期>缺料>正常）+ setup 条排除、flux 缺失 load_rate=None 不判超载。
7. **对照抽查结论（T5）**：
   - `schedule.py:72-111` ↔ `schedule.js:207-243`（allocEarliest）：逐行 1:1（含 1e-9 ceil 容差、slots/nooverlap、3650 扫描上限、dayNeeded≤0 早退）；
   - `schedule.py:132-267` ↔ `schedule.js:250-370`（scheduleProcessConstrained）：逐行 1:1，差异仅二-2/3 所列 4+1 项偏离（均已留痕）；
   - `schedule.py:355-399` ↔ `schedule.js:436-481`（ganttChart）：逐行 1:1，差异仅 anchor 回退（二-2②）；
   - `operations.py` ↔ 设计 D12/§4：自动分解（depends_on_seq 链）/手工追加（source=manual + depends_on_id + note）/重同步保 manual/手工条参与排产占产能，语义符合；
   - `kanban.py` ↔ `kanban.js`（121 行全量）：等价，差异仅 4 项适配（二-5）；
   - 差分探针：`alloc_earliest` 6 例（账本铺开/二单顺延/ceil 容差/单资源不可行扫描至 limit+1/nooverlap slots/零量早退）Node v24 与内嵌 Python 输出全等。

## 三、经验教训（本批次真实事件）

1. **"计划笔误"系列（计划文本必须实证复核）**：夹具体量矛盾 1042 vs 1052（WB 0.99/0.98 口径，Node 实证才定位）；due 链断言方向写反（正确语义：实际开工 < 最晚投料日 = 满足）；`_ctx_min` 缺"模块级|调试"WC（手工条用例主数据漏配，运行才暴露）；计划 Task3 测试代码块漏 `Order` import；看板夹具列表表达式尾部 noop 拼接 `*11 + []`——**计划代码块誊写后须先跑通再落地**。
2. **预检发现计划缺陷（正向经验）**：T1 前 Node 实跑（发现夹具矛盾）、T2 前手算基准（06-02/63120/11）先行核验，均在实现前暴露计划缺陷——"先实证后实现"保留为 3B2 默认动作。
3. **质量跟进闭环**：四个任务各有一轮审查跟进（`804d7d0`/`1194117`/`d8da1dc`/`1b8a399`），修复项覆盖幂等/护栏/边界/测试判别力，均随提交附测试与文档镜像，无返工。

## 四、未决事项与续跑指南（3B2）

**3B2 范围（下一步）**：`aps.py`（gate/启发式/局部搜索/指标/评估）→ `ga.py`（DEAP 求解核心 + PARAM_DEFS 增 ga_population/ga_generations/ga_seed）→ `solver.py`（模式门面：ga 默认/确定性基准/heuristic；CP-SAT 延后留痕）→ `schedule_service.py`（载单/运行/批次与分配落库/订单回写，SCHED-010）→ SCHED 清单回写与计划 3 最终审查。

**3B2 开工前注意（从 3B1 传递）**：
1. **重同步悬空**：`sync_order_operations` 删除重建 auto 行后，manual 行的 `depends_on_id` 可能悬空（指向已删旧 id）——service 接入时按 order_id+seq 重挂或清理；
2. **warnings 序列化**：解码返回含 [扩展] `warnings` 键（JS 无），批次落库/API 回显须纳入；缺 WC 告警供前端提示消费；
3. **kanban 错误分支无 groups**：无效日期返回不含 `groups`（JS 同构），消费方须空值防护；
4. **operations Minor 5-10**：评审遗留次要项（非阻塞）留待 service 接入时一并处理；
5. **SCHED 清单回写归 3B2**（001~009 随本批实现完成；010 随 schedule_service）；
6. **回调契约（3B2 消费）**：`schedule_process_constrained(results, base, opts)`、`gantt_chart(planned, {"base_date": …})`、`ledger`/`fluxOf`（周负荷与看板共用）、`merge_manual_bars`。
