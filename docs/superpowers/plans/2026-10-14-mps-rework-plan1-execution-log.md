# MPS 改造计划 1 执行记录与经验教训

- 日期：2026-10-14（收工记录）
- 分支：`mps-rework`（基线 `4a85584` 在 master）
- 计划：`docs/superpowers/plans/2026-10-14-mps-rework-plan1-checklist-data-layer.md`
- 规格：`docs/superpowers/specs/2026-10-14-mps-rework-design.md`

## 一、执行摘要

| 项 | 结果 |
|---|---|
| 完成范围 | Task 0~6 / 共 9 项（Task 7 种子、Task 8 清理与全量回归、最终整体审查 未开始） |
| 测试基线 | **40 passed, 1 skipped**（内嵌 Python 3.13.5；PG 用例需 `TEST_PG_URL` 时全跑） |
| 提交序列 | `4a85584`(基线) → `a3332ce` `9bc512d` `2bfbfaf` `c18f386`(Task1) → `575d9ef` `31a1961`(Task2) → `b5961aa` `89a9506`(Task3) → `2d28c1f` `61e61da`(Task4) → `124a645` `3fa0f34`(Task5) → `bf531f3` `c41f5bd`(Task6)，共 15 提交 |
| 主要交付物 | ① check-list 101 条（含测试用例命名与覆盖自查）② MPS 13 张表模型 ③ Alembic 迁移 `62ad14d88051` ④ SQLite/PG 双库引擎 ⑤ 本地模式启动（自动建表+Redis 降级）⑥ 特征/参数常量模块 |

## 二、关键决策记录

1. **运行环境**：项目内嵌 Python `offline\runtime\python\python.exe`（3.13.5，含全部运行依赖）。系统 Python 3.14 缺 asyncpg 等运行依赖，不可用于本项目。
2. **7 项"排产约束"参数有意延后**：mps-web PARAM_DEFS 中 `day_cap_mode/takt_window` 等 7 项仅其未接入的 `balance.js` 使用；已在 `app/mps/consts.py` 注释记录，待计划 3 确定均衡/节拍策略时按需补入并同步参数页。
3. **计划 ↔ 实现逐字镜像**：每个任务评审后的修复均同步回写计划文件代码块，保持二者一致（作为审计记录与后续计划模板）。
4. **评审流程**：每任务 = 实现 → spec 审查 → 质量审查 → 修复提交（部分含复审）；所有修复独立成提交，可追溯。

## 三、经验教训（来自真实事件）

1. **子代理长任务不稳定**：单次超长生成（100+ 行文档 / 300+ 行模型文件）出现过空返回与中途中断。对策：拆小任务分两段产出（Task 1）、失败后换新会话或控制器直接接手（Task 2/5 即如此完成）。结论：任务颗粒度 ≤1 个文件一次性写出的量最稳。
2. **计划代码必须做可运行性预检**：计划 Task 3 测试里写了 `AsyncEngine.run_sync(...)`（该 API 不存在），由质量审查发现并修正计划；教训：写入计划的代码在定稿前应过一遍编译/运行冒烟。
3. **两段审查回报显著**（全部为审查发现，非实现者自查发现）：
   - Task 1：编号规范系统性偏离（`CHK-` 前缀）、FLUX-011 预期值自相矛盾（会把测试带偏）；
   - Task 2：`init_schema` 可把建表误打到生产引擎、PG 测试守卫 `"test" in url` 过弱（`tester@prod` 会通过导致 drop_all 清库）、核心函数无测试；
   - Task 3：模型/迁移索引漂移、JSON 原地修改不被追踪（静默丢写）、约束测试缺口；
   - Task 5：Redis 为惰性连接（启动"成功"不代表可达，降级分支仅覆盖配置错误）、本地 SQLite 模型演进无缺列校验→已录入规格 §11 风险表；
   - Task 6：7 项参数被静默裁剪、关键映射缺快照断言（改名可静默通过）。
4. **环境陷阱清单**：
   - `.gitignore` 忽略 `backend/scripts/` → 新增维护脚本放 `backend/tools/`（已弃用旧目录放一次性调试脚本）；
   - PowerShell 控制台中文乱码、内联 python 引号转义易错 → 一律写临时 .py 脚本执行；
   - `Start-Process` 重定向日志必须用绝对路径（否则进程起不来）；
   - 内嵌 Python 补装的 `pytest/pytest-asyncio/aiosqlite/simpy` 不在 `offline/python_packages` 中——**离线包交付前需补入/重建**（记入计划 6 部署任务）。
5. **安全红线保持**：`backend/.env`（含真实密钥）全程未入 git；每次提交经 `git show --stat` 核对无夹带。
6. **文档即资产**：check-list 的"编号 + 测试用例 + 状态"三列结构让"规则→测试→实现"可双向追溯；后续计划 2~6 均以它作为验收锚点。

## 四、未决事项与续跑指南

**下一步（计划 1 剩余）：**
1. Task 7 种子转换/加载/导入（转换脚本读 `D:\MPS\mps-web\seed.json` 只读，产物 `backend/app/seed/mps_seed.json` + `demo_orders.json`；loader 参数只补缺失；demo 单 only-once）；
2. Task 8 旧数据清理（dry-run 默认）+ 全量回归；
3. 最终整体代码审查（dispatch final reviewer）→ `finishing-a-development-branch`（合并/保留分支决策）。

**计划 2 开工前建议动作（评审提出）：**
- 模型-迁移漂移自动守卫：scoped `compare_metadata` / `alembic check` 固化为 pytest 或 CI 步骤（对 `TEST_PG_URL` 测试库）；
- Task 7 合入时补"种子全部 distinct feature 均可被 FEATURE_MAP 解析"回归测试；
- 视需要在计划 4/5 落地 Redis 短超时 ping / fail-open（当前无消费方）。

**运行命令速查（backend 目录）：**
```powershell
# 测试（必须用内嵌 Python）
& "D:\aps-hap\offline\runtime\python\python.exe" -m pytest tests -v
# 本地 SQLite 模式启动
$env:DATABASE_URL="sqlite+aiosqlite:///./data/mps.db"
& "D:\aps-hap\offline\runtime\python\python.exe" -m uvicorn app.main:app --port 8010
```

**待业务确认（阻塞项 12 条，见 check-list "阻塞(疑点)"）：** WB 自动通量 12000/20000、批量项取整、订单缓冲、爬坡触发、BOM 特征数据源、优先级与齐套组合排序语义等。
