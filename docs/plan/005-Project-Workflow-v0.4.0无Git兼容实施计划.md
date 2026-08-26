---
workflow: "project-workflow/v1"
plan_id: "project-workflow-v0-4-git-optional"
revision: 1
phase: "COMPLETED"
workflow_profile: "FULL"
approved_revision: 1
approved_at: "2026-08-25T05:44:41+00:00"
confirmation_record: "同意"
conversation_title: "Project Workflow 无 Git 兼容"
progress_heartbeat_minutes: 5
vcs_mode: "GIT"
resolved_vcs_mode: "GIT"
execution_mode: "AUTO_MULTI_AGENT"
max_workers: 2
agent_topology: "SHARED_WORKSPACE"
progress_reporting: "COMPACT"
parallelism_policy: "BENEFIT_GATED"
orchestration_state: ".codex/project-workflow/project-workflow-v0-4-git-optional/orchestration.json"
---

# Project Workflow v0.4.0 无 Git 兼容实施计划

## 1. 目标与范围

按[无 Git 兼容设计](../design/005-Project-Workflow-v0.4.0无Git兼容设计.md)把 Git 从隐含必需条件改为可配置能力，为 LIGHT/STANDARD 提供正式文件系统降级，并为 FULL 保留可验证回滚门禁。

范围包括 Doctor、VCS/文件快照辅助脚本、生命周期与调度前置校验、三个技能、共享协议、双语 README 和黑盒测试。不修改插件 ID，不提交、打 tag、推送或发布。

## 2. 基线与授权

- 基线提交：`c4f45e4db678865287ef6f9fb8aa35fc567b5806`；当前工作区包含尚未提交的 v0.4.0 用户改动，必须原样保留。
- 当前源码版本：`0.4.0`；本计划不提升语义版本。
- 已知回归基线：插件测试 81/81、安装器测试 6/6。
- Doctor：插件、Python 与两个 CLI 契约均正常；当前 Codex 沙箱对源码仓库的内部状态目录返回不可写 blocker，已通过受控权限创建并验证内部调度状态，不代表宿主仓库权限异常。
- 用户已认可 AUTO/GIT/NONE 方向，但依照审批协议，该认可发生在本计划持久化之前，不视为 revision 1 的批准。
- commit、tag、push、远程发布和部署：均未授权。
- 本机重装：仅在实现通过全部验收后，沿用用户此前对 v0.4.0 本地更新的授权范围；若安装命令再次触发系统审批则以系统审批为准。

## 3. 任务图

### T01 VCS 探测、文件快照与执行门禁

- 状态：[x]
- Owner：原生 Worker
- Depends-On：none
- Write-Scope：
  - `plugins/project-workflow/scripts/project_workflow_doctor.py`
  - `plugins/project-workflow/scripts/workflow_state.py`
  - `plugins/project-workflow/scripts/filesystem_snapshot.py`
  - `plugins/project-workflow/tests/test_project_workflow_doctor.py`
  - `plugins/project-workflow/tests/test_workflow_state.py`
  - `plugins/project-workflow/tests/test_filesystem_snapshot.py`
- Agent-Eligible：true
- Parallel-Group：wave-1
- Planned-Owner：native-worker
- Estimated-Minutes：40
- Coordination-Minutes：5
- Critical-Path：true
- 目标：实现 AUTO/GIT/NONE 解析、环境漂移校验、FULL 无回滚阻断与原子文件快照/比较。
- 排除：不实现其他 VCS，不备份文件正文，不执行 Git 写操作。
- 验收：设计第 10 节第 1–5 项全部有自动化覆盖；旧生命周期命令保持兼容。
- Validation（DISCOVERY）：
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_*snapshot*.py' -v`
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_project_workflow_doctor.py' -v`
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_workflow_state.py' -v`
- Evidence：六个约定路径完成；快照 6/6、Doctor 12/12、生命周期 26/26，共 44/44 目标测试通过；Python 3.9 编译和 `diff-check` 通过。文件快照明确仅作变更证据，不作为正文备份。

### T02 技能、协议与双语文档

- 状态：[x]
- Owner：原生 Worker
- Depends-On：none
- Write-Scope：
  - `plugins/project-workflow/skills/plan/SKILL.md`
  - `plugins/project-workflow/skills/execute/SKILL.md`
  - `plugins/project-workflow/references/workflow-protocol.md`
  - `plugins/project-workflow/references/execution-checklists.md`
  - `plugins/project-workflow/references/multi-agent-orchestration.md`
  - `README.md`
  - `README.zh-CN.md`
- Agent-Eligible：true
- Parallel-Group：wave-1
- Planned-Owner：native-worker
- Estimated-Minutes：30
- Coordination-Minutes：5
- Critical-Path：true
- 目标：让三个 VCS 模式、NONE 证据模型、FULL 门禁和多智能体退化行为在技能与用户文档中一致。
- 排除：不修改脚本实现，不修改插件 ID 或 marketplace。
- 验收：Git 仅作为 GitHub 安装/贡献依赖；执行技能不再无条件要求 Git；NONE 禁止 branch/worktree/commit/push。
- Validation（DISCOVERY）：
  - 三个技能运行 `quick_validate.py`。
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_documented_commands.py' -v`
- Evidence：七个约定路径完成；三个技能 `quick_validate.py` 与 scoped `diff-check` 通过。文档契约测试 6/7，通过项正常，唯一缺口为新快照脚本尚未登记到测试映射，按依赖交由 T03 关闭。

### T03 独立无 Git 契约验证

- 状态：[x]
- Owner：独立原生 Worker
- Depends-On：T01, T02
- Write-Scope：
  - `plugins/project-workflow/tests/test_vcs_contract.py`
  - `plugins/project-workflow/tests/test_documented_commands.py`
- Agent-Eligible：true
- Planned-Owner：contract-verifier
- Estimated-Minutes：25
- Coordination-Minutes：5
- Critical-Path：true
- Role：CONTRACT_VERIFIER
- Independent-Verification：true
- 输入隔离：仅接收用户要求、本设计公开契约和验收标准，不接收实现讨论或 Worker 自评。
- 验收：覆盖非 Git 目录、Git 命令缺失、显式 NONE、显式 GIT、AUTO 环境漂移、FULL 回滚门禁、符号链接逃逸、快照幂等和历史兼容。
- Validation（DISCOVERY）：
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_vcs_contract.py' -v`
- Evidence：独立验证者仅修改两个约定测试路径；新增无 Git 契约测试 9/9、文档命令测试 8/8、插件全量 106/106 通过，未发现生产契约缺陷。

### T04 集成、回归、交付与本机更新

- 状态：[x]
- Owner：协调者
- Depends-On：T01, T02, T03
- Write-Scope：
  - `docs/plan/005-Project-Workflow-v0.4.0无Git兼容实施计划.md`
  - `docs/delivery/005-Project-Workflow-v0.4.0无Git兼容交付报告.md`
  - `plugins/project-workflow/.codex-plugin/plugin.json`
  - `scripts/install_local_plugin.py`
  - `tests/test_install_local_plugin.py`
- Agent-Eligible：false
- 目标：审查交接、修复集成问题、执行全部回归和插件重装。
- 验收：插件全量、安装器、技能、插件结构、Python 编译与 diff 检查全部通过；源码版本保持 `0.4.0`。
- Validation（DISCOVERY）：
  - `python3 -m unittest discover -s plugins/project-workflow/tests -v`
  - `python3 -m unittest discover -s tests -v`
  - 三个技能 `quick_validate.py` 与插件 `validate_plugin.py`
  - Python 3.9 `py_compile`、`git diff --check`
- Evidence：插件全量 106/106、安装器 6/6 通过；三个技能、插件结构、Python 编译与 `diff-check` 通过。源码版本保持 `0.4.0`，本机已安装 `0.4.0+codex.20260825060618`，并验证新快照脚本与 VCS 技能契约存在。

## 4. 调度与回退

- Wave 1：T01 与 T02 写入范围不重叠，预计串行 70 分钟、并行含协调 50 分钟，预计节省约 28.6%，允许最多两个原生 Worker。
- Wave 2：T03 作为独立契约验证单独执行；失败项返回原任务或协调者修复后复验。
- Wave 3：T04 由协调者串行完成。
- 原生 Worker 不可用时退回协调者串行，不改变已批准范围。
- 任一任务发现 VCS 模式需要改变公开字段或破坏历史兼容时，停止受影响任务并修订计划。

## 5. 迁移与风险验收

采用设计第 8 节的完整迁移矩阵。重点验证：历史字段缺失、AUTO 解析、批准后环境漂移、显式 GIT 缺失、显式 NONE 位于 Git 仓库、重复快照、崩溃写入、活跃 Worker 恢复、未知值拒绝与 v0.3 回滚限制。

边界矩阵：

- 类型/空值：VCS 值缺失、空字符串、布尔/容器值、大小写漂移。
- 集合/路径：空目录、大量文件、重复路径、范围重叠、符号链接逃逸。
- 时间：N/A；VCS 解析不依赖业务时间，快照仅使用内容哈希。
- 重试/原子性：重复 create/compare、临时文件替换失败、旧基线保留。
- 错误表面：Git 不存在、非工作树、权限失败、无效计划字段均返回稳定错误且不泄漏 traceback。
- 并发/恢复：活跃 Worker 环境漂移时不再分配新任务；当前协议没有租约。
- 回滚：哈希清单不是备份；FULL/NONE 缺少等价回滚证据时必须阻断。

## 6. 完成定义

- T01–T04 全部完成并有验证证据。
- 无 Git 与 Git 两条路径均通过黑盒契约测试，历史计划兼容。
- 计划、技能、Doctor、脚本和双语 README 语义一致。
- 本机安装缓存包含修复版本，源码清单仍为 `0.4.0`。
- 未 commit、未 tag、未 push、未部署。

## 7. 确认门禁

计划生成后等待用户明确确认 revision 1。确认仅授权上述文件范围内的实现、测试、计划内原生 Worker 委派和已授权的本机插件更新，不授权提交、tag、push、远程发布、部署或破坏性操作。
