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

---

# MPS 改造计划 3 执行记录与经验教训（3B2：APS·GA·求解门面·排产落库，进行中）

- 日期：2026-10-16（首次会期；本批 Task 2~5 待续）
- 分支：`mps-rework`
- 计划：`docs/superpowers/plans/2026-10-14-mps-rework-plan3b2-aps-ga-persistence.md`（编制并独立审查修正，`d2c2a10`）

## 一、执行摘要（3B2，至暂停点）

| 项 | 结果 |
|---|---|
| 完成范围 | ①计划编制+独立审查+修正（`d2c2a10`）；②Task 1（`aps.py` 移植）实现+勾选（`bbbcc13`/`9fd31c7`）；Task 2~5 未开始 |
| 测试基线 | **174 passed, 1 skipped**（166 → 174，Task1 +8） |
| 待推送 | origin 落后 3 个提交（`d2c2a10`/`bbbcc13`/`9fd31c7`）——网络中断（github 443 连接失败），续跑首步重试 `git push` |
| 审查状态 | 计划独立审查 ✅（隔离工作区计划代码块实跑 57/57 全绿；修正 4 项已并入计划）；Task 1 规格审查 ✅ 合规（镜像逐字一致、独立复算全吻合，5 项非阻断建议）；Task 1 质量审查 ⏸ 会话中止未完成，续跑重发 |

## 二、关键决策与修正留痕（计划独立审查产物，已入 `d2c2a10`）

1. **F1 清单回写列序修正**：check-list 实为 6 列（…｜测试用例｜状态）。计划原说明"前 6 列保持/状态在前"机械套用会写反 → Step 5.1 改为"前 4 列保持；第 5 列=测试用例（实测文件）、第 6 列=状态"，并声明预设 `test_kernel_sched.py` 路径为编制期占位。
2. **F2 D12 契约缺口（实装修正）**：原计划 `run_schedule` 未消费 `merge_manual_bars`（手工条不参与服务端排产，与 docstring/Self-Review 声明不符）→ Task 4 实装：载入 manual 行（`depends_on_id`→前道 seq）→ `merge_manual_bars` 并入 → 分配行按 manual 行顺序（seq 升序）与手工条一一关联 `operation_id`（免对象身份依赖）；新增服务级测试 `test_run_schedule_manual_operation_participates`（探针实证：37 行=32+5、手工条 2026-06-28 起 5 天、每天 1052/5、该资源键合计 2104）；计数 188→189。
3. **F3 micro 差异补录**：`产能闸值超 1.0`（JS 渲染 `1`）写入 `aps.py` docstring 差异清单。
4. **F4 注释修正**：ga 测试"输入序（=GT 序）"不准确 → 输入序（优先序）目标；GT 序另见种子用例。

## 三、经验教训（本批次真实事件）

1. **计划独立审查高 ROI（保留为 3B2 默认动作）**：审查员在隔离 temp 工作区按计划补丁组装临时仓库，把计划全部代码块实跑 57/57 全绿 + 逐条复算数值 + 逐函数对照 `aps.js` → 执行前有实证底气。本次抓 4 项；其中 **F2 属"自检声明与代码调用链不符"类缺陷——模块存在≠被消费，声明必须沿调用链核对**。
2. **回写类指令必须对照目标文件实证**：F1（列数/列序）若不打开 checklist 实际表头核对，机械回写必错。
3. **渲染差异要穷举**：F3 表明"数值相等≠文案一致"（`1` vs `1.0`），移植差异清单须覆盖字符串渲染。
4. **探针先行再次命中**：编制期探针抓出 date 归一 bug（DB 直读 `date` 与 `"9999"` 哨兵不可比）；F2 修正亦先探针实证期望值（37/2104/06-28）再改计划，未二次返工。
5. **网络中断留痕续跑**：推送连续失败不停滞主线程（继续 Task 1 实现），本地垒好分段提交后暂停；续跑首步=重试 push（先例：3B1 期间同故障重试即通）。

## 四、未决事项与续跑指南（3B2 续跑）

1. **首步：重试推送**（3 个提交：`d2c2a10`/`bbbcc13`/`9fd31c7`）。
2. **Task 1 质量审查重发**（本次未完成）；规格审查 5 项非阻断建议择要跟进（入"质量跟进"提交）：①评估隔离断言（`assert "plan" not in r`，变异实验证明现测试不钉此项）；②`aps_optimize` 改进分支（fixture 下不可达）留痕即可；③门控缺 kit_date/`cap_threshold` 覆盖可补轻量用例；④use_peak/peak_factor、base_date 缺省、setup=False 覆盖（可选）。
3. **Task 2~5 依计划执行**：ga.py（DEAP）+PARAM_DEFS+`deap==1.4.4` 入 requirements → solver.py+week_days 透传修复 → schedule_service.py+operations 依赖重挂修复（F2 已并入计划）→ 清单回写+计划 3 最终审查。
4. **3B1 移交 6 条现状**：第 1 条（重同步悬空）已由 Task 4 计划覆盖修复；第 2/3/5/6 条随 Task 2~5 落地；第 4 条（operations Minor 5-10）留待 service 接入时一并处理。

---

# MPS 改造计划 3 执行记录与经验教训（3B2 完成 / 计划 3 收尾）

- 日期：2026-10-17（续跑完成；首次会期 2026-10-16 至暂停点）
- 分支：`mps-rework`
- 计划：`docs/superpowers/plans/2026-10-14-mps-rework-plan3b2-aps-ga-persistence.md`

## 一、执行摘要（3B2 完成）

| 项 | 结果 |
|---|---|
| 完成范围 | **Task 2~5 全部完成**（Task 1 已于首次会期完成）：ga.py + PARAM_DEFS 增补；solver.py + week_days 透传修复；schedule_service.py + operations 依赖重挂修复；SCHED 清单回写 + 计划 3 收尾 |
| 测试基线 | **189 passed, 1 skipped**（174→179→185→189，本批 +15；install 命令 `git push` 前置收尾见下） |
| 提交序列 | `9b0a48c`(Task2 GA) → `6ab6101`(Task3 solver) → `8c72a64`(Task4 service) → 目录迁移 `0d5b617`（前置）→ 收尾文档提交 |
| 主要交付物 | `app/mps/ga.py`（DEAP 序列搜索核心）、`app/mps/solver.py`（ga/deterministic/heuristic/cp_sat 门面）、`app/mps/schedule_service.py`（唯一碰 DB 的排产模块：载单→手工条并入→求解→批次/分配落库→订单回写） |
| 接口改动 | `consts.py`/`context.py` 增 3 个 `ga_*` 参数；`strategy.py`/`schedule.py`/`aps.py` week_days 透传；`operations.py` `sync_order_operations` 依赖重挂 |
| 测试 | 新增 test_mps_ga.py(5)、test_mps_solver.py(5)、test_mps_schedule_service.py(3)；改 test_consts.py(+3 断言)、test_mps_strategy.py(+1)、test_mps_schedule.py(改 1)、test_mps_operations.py(+1) |

## 二、关键决策记录

1. **GA 染色体 = 索引排列**：DEAP `tools.cxOrdered` 要求整数基因，故以 `list(range(n))` 的重排作染色体、索引映射回 passed（探针实证：直接以结果 dict 作基因不可行）。
2. **确定性基准默认关 setup**：`deterministic` 仅传 strategy/P（+显式 setup 透传），与直接调用 `schedule_process_constrained` 逐条等价（CHK-SCHED-009），故 `metrics.setupTotal==0`；换型成本只在 GA/heuristic 评估口径计入。
3. **CP-SAT 延后留痕**：`mode=="cp_sat"` 抛 `NotImplementedError("CP-SAT 延后（设计 D11，非验收基准）")`；验收以 GA + deterministic 为准。
4. **随机流隔离**：`run_ga` 内 `random.seed` 前保存、结束恢复 `random.getstate()`，不污染全局随机流（多单串行排产可复现）。
5. **D12 手工条服务管道接入**：`run_schedule` 读 manual 行（`depends_on_id`→前道 seq）→ `merge_manual_bars` 并入甘特参与排产 → 分配行按 manual 行 seq 升序与手工条一一关联 `operation_id`（免对象身份依赖）。
6. **batch_no 单调**：`SCH-{YYYYMMDD}-{序号:03d}`（序号=同前缀最大+1）。
7. **目录迁移（D:→F:）前置修复**：MPS 只读资料目录 `D:\MPS`→`F:\MPS`、项目 `D:\aps-hap`→`F:\aps-hap`。修复 5 个已跟踪文件硬编码路径并参数化 MPS 源目录（`MPS_DIR` 环境变量，默认 `F:\MPS`）；`worksheet_ids*.json` 改为相对本文件定位 `deploy/`；plan3b2 内 pytest/参照命令 D:→F:。修复后基线复现 174 passed。

## 三、经验教训（本批次真实事件）

1. **date 归一 bug（编制期已捕获）**：DB 直读 `date` 对象与 `"9999"` 哨兵字符串不可比——Task 1 已留痕修正。
2. **cxOrdered 整数基因约束**：次序交叉只接受可比较整数基因，索引排列是正确解法。
3. **HallOfFame deepcopy**：`tools.HallOfFame(1)` 内部 deepcopy 保管最优个体，避免后续世代原地变异污染最优。
4. **手工条 operation_id 关联不依赖对象身份**：按 bars 顺序 + 计数对齐（seq 升序），稳健且可测。
5. **回写类指令须对照目标文件**：checklist 为 6 列（测试用例在前、状态在后），按 F1 修正逐行列序核对后回写。
6. **PowerShell 中文乱码**：统一 `$env:PYTHONIOENCODING="utf-8"`；必要时落盘读回。
7. **Git 身份缺失（新机器）**：首次提交报 "Author identity unknown"，按仓库历史作者设仓库级 `user.name/email` 后恢复。

## 四、3B1 移交项收口

| # | 移交项 | 结论 |
|---|---|---|
| ① | 重同步悬空 | ✅ Task 4 修复（新增 `test_sync_rehang_manual_dependency`） |
| ② | week_days 透传 | ✅ Task 3 修复（三处；新增 `test_order_by_priority_week_days_tiebreak`） |
| ③ | warnings 序列化 | ✅ 随 solver/service 落地（`out["warnings"]` 外露） |
| ④ | kanban 无 groups 空值防护 | ⏳ 留待计划 5（消费方：前端/API） |
| ⑤ | SCHED 清单回写 | ✅ Task 5.1 完成（001~010 全「通过」，日期 2026-10-16 按计划表回写） |
| ⑥ | operations Minor 5-10 | ⏳ 非阻塞，留待 API 层接入时处理 |

## 五、开放问题（移交计划 4/5）

1. `ga_*` 参数是否需前端参数页展示（`PARAM_DEFS` group="求解" 会随参数管理页自动出现）——待前端确认。
2. deap 版本策略：锁定 `deap==1.4.4`（升级需复跑 GA 复现性用例）。
3. 计划 3 最终审查：SCHED 十条全绿、无遗留「待实现」（除 PRIO-009/SYNC/UI/COL 等归后续计划）——见下节收尾报告。

## 六、质量审查（本次实现，独立评审）

- 方式：独立评审员用脚本抽取计划全部 ```python 代码块与实际文件做 unified diff，逐条复算边界用例，grep 核对清单引用的用例名，并实跑测试。
- 结论：**无阻断级缺陷，可进入计划 4**。`ga.py`/`solver.py`/`schedule_service.py` 及 `operations.py` 修复、`strategy.py`/`schedule.py`/`aps.py` 透传、3 个测试文件与计划代码块**逐字一致**（diff 无实质偏差）；任务书列举的边界（GA 索引排列/种子/seed=0/随机隔离/improved 阈值；solver 确定性等价/异常文案/objective≤baseline；service 单事务/batch_no 单调/operation_id 关联/逐日拆分/回写；operations 依赖重挂）全部验证正确；`depends_on_id` 无 FK，先删后挂不触发外键违例（PG 双库无忧）。实跑：本批 3 文件 13 passed；全量 189 passed, 1 skipped。

**本次采纳的更正**：计划文本「`orders` 回写 16 字段」订正为「15 字段」（与 `schedule_service.py` 实现、Task 4 断言及 `2026-10-14-mingdao-app-bootstrap.md`「核算回写 15」一致）。

**留待计划 4 处理（重要，非阻断）**：
1. `batch_no` 词法单调在**单日 >999 批次**时失效（`order_by(batch_no.desc())` 词法序；`-999`>`-1000`）——单日重排 >999 不现实，计划 4 批量重跑/多基准对比时改纯数字排序或加宽位数。
2. `run_schedule` 隐式依赖调用方先 `sync_order_operations`（否则自动条 `operation_id=None` 且手工条不并入）——计划 4 API 契约固化前置步骤或在入口断言。
3. GA `improved=True` 分支在现有夹具下不可达（两种子目标恒等）——计划 4/5 造可改进夹具覆盖该分支。
4. 测试覆盖缺口：`run_ga` 不传 `weights`（KeyError）、`seeds` 数 > population 截断、非完整排列种子；solver `improved=True` ga/heuristic 文案、`weights` 覆盖、deterministic 显式 setup；service batch_no≥003、缺工作中心手工条缺 flux、同单多手工条、ga+手工条组合、事务回滚；operations 手工→手工依赖清空留痕。计划 4 按需补。
5. `CHK-SCHED-010` 第 2 列（规则描述）仍写 `schedule_result`，实际模型/表为 `ScheduleAllocation`/`schedule_allocations`（Task 5 仅改第 5/6 列）——计划 4 顺手订正描述列。

**次要**（不处理，留痕）：`ga.py` `weights` 无缺省（独立调用易 KeyError）、`solver.py` heuristic `seed≤0` 用全局 `random` 未还原（与 `run_ga` 隔离策略不一致）、`1e-9`/`0.5`/默认 `30/20/42` 字面量重复、`ga.py` 对 `n<2` 无护栏。

---

## 七、质量跟进（2026-10-17，审查留待项处理）

| 项 | 状态 | 说明 |
|---|---|---|
| ⑥-1 `batch_no` 词法单调 >999 失效 | ✅ 修复 | 序号改「同前缀**数字**最大+1」（去 `order_by(desc)+limit(1)`）；镜像同步订正；新增 `test_batch_no_sequence_is_numeric_not_lexical`（-999/-1000 → -1001） |
| ⑥-2 `run_schedule` 隐式预同步依赖 | ✅ 修复 | 契约由「不同步（调用方先行）」改为「**零工序行兜底自动补建**」（计算无错订单 `sync_order_operations`）；镜像 + 模块 docstring 同步；新增 `test_run_schedule_autosyncs_missing_operations` |
| ⑥-3 GA `improved=True` 不可达 | ✅ 修复 | 新增 `improve_fixture`（策略序=GT 序 15.0475 → 最优 4.1475）；heuristic `(已改进)` 后缀与 GA improved=True 各一测；另以最差序种子覆盖 GA 改进语义 |
| ⑥-4 测试覆盖缺口 | ✅ 部分补齐 | 新增 7 测：seed 截断（含最差序 `[2,3,1,4,0]`）、weights 缺省兜底、improved 两分支、同单多手工条、自动兜底同步、batch_no 数字序、手工→手工依赖清空 |
| ⑥-5 `CHK-SCHED-010` 描述列 | ✅ 订正 | `schedule_result` → `schedule_allocation` + `orders` 回写 |
| 次要：`ga.py` `weights` 无缺省 | ✅ 修复 | `opts.get("weights") or DEFAULT_WEIGHTS` 兜底（同测覆盖） |
| 次要：heuristic `seed≤0` 全局 random | ⏳ 留待 | 计划 4/5（连同 `n<2` 护栏、字面量重复一并择机） |

**探针实证（本次）**：
1. `seq_fixture` 全排列枚举（`aps_evaluate`/`schedule` 口径 120 排列）**0 个优于 GT 序** → 原夹具 improved 分支原理性不可达；GA 解码器（`schedule_process_constrained`）口径复枚举同证（最差 8.1033…= `[WO-5,WO-4,WO-2,WO-1,WO-3]`）。
2. `improve_fixture` 探针：GT/策略序 15.0475 → 交换后 4.1475，`optimize(seed=42, iters=200)` 稳定 improved=True；solver 两模式（heuristic/ga）复验同值。
3. **教训**：`aps_gate` 输出的 `passed` **已按优先级排序**（`WO-3` 居首），构造种子索引须以 `passed` 实际顺序为准；首版按规格序假设致 2 断言失败，探针捕获后改 `(2,3,1,4,0)`。另：GA 解码器与 `aps_evaluate` 目标地形不同，夹具探针必须用与实现同口径的解码器。

**验证**：相关 4 文件 28 passed；全量 **196 passed, 1 skipped**（189→196，+7）；镜像校验脚本抽取计划代码块与 `ga.py`/`schedule_service.py` 逐字一致。

**提交**：单提交（源码修复 + 测试 + 计划镜像/清单/本记录同步）。

**计划 4/5 衔接**：本次契约变更（兜底同步）已入 `run_schedule` docstring 与计划镜像，计划 4 API 层可省略显式预同步（仍可先行为之）；`improve_fixture` 供后续 UI/KPI 对照复用。


