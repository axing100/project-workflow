---
workflow: "project-workflow/v1"
plan_id: "project-workflow-v0-5-state-ux"
revision: 1
phase: "COMPLETED"
approved_revision: 1
approved_at: "2026-08-31T05:17:25+00:00"
confirmation_record: "帮我改"
policy_contract: "v0.4"
workflow_profile: "FULL"
conversation_title: "Project Workflow 状态体验改造"
progress_heartbeat_minutes: 5
vcs_mode: "AUTO"
resolved_vcs_mode: "GIT"
rollback_required: "true"
rollback_strategy: "按 Git 差异逐文件撤销 009 号计划改动；迁移测试使用临时仓库，真实旧计划不自动迁移；必要时删除新建的内部 v0.5 状态目录并恢复迁移前计划副本"
rollback_evidence: "当前 feature/project-workflow-v0.4.1 分支 HEAD、执行前干净工作区、v0.4.1 全量测试与旧计划兼容夹具"
rollback_verification: "VERIFIED"
execution_mode: "SINGLE_AGENT"
max_workers: 1
agent_topology: "SHARED_WORKSPACE"
progress_reporting: "COMPACT"
parallelism_policy: "BENEFIT_GATED"
commit_authorized: "false"
push_authorized: "false"
---

# Project Workflow v0.5.0 状态体验与内部锁实施计划

<!-- project-workflow:summary:start -->
> **任务进度** · 实现 5/5 · 验收 5/5
<!-- project-workflow:summary:end -->

设计：[009-Project-Workflow-v0.5.0状态体验与内部锁设计](../design/009-Project-Workflow-v0.5.0状态体验与内部锁设计.md)

> 本计划由 v0.4.1 创建，现已作为真实样例迁移为 v0.5 中文双状态展示；内部状态是任务进度唯一事实来源。

## T01 内部锁迁移

<!-- project-workflow:task-status T01:start -->
- 实现状态：✅ 已完成
- 验收状态：✅ 已通过
- 证据：workflow_state 与 orchestration_state 共 99 项锁与并发回归通过；显式 repo 锁进入 .codex/project-workflow；无相邻计划锁
<!-- project-workflow:task-status T01:end -->

- Depends-On：无
- Write-Scope：
  - `plugins/project-workflow/scripts/workflow_state.py`
  - `plugins/project-workflow/scripts/orchestration_state.py`
  - `plugins/project-workflow/tests/test_workflow_state.py`
  - `plugins/project-workflow/tests/test_orchestration_state.py`
- Agent-Eligible：false
- 目标：停止在计划文档旁创建锁文件，把显式仓库上下文的锁放入内部状态目录，并为无仓库兼容命令提供私有临时锁。
- 范围外：任务双状态、Markdown 渲染和语言资源。
- 风险：锁路径变化造成新旧进程互斥失效；删除锁文件造成 inode 竞态；NONE 模式意外依赖 Git。
- 验收标准：
  - [x] 新生命周期和调度命令不会创建 `docs/plan/.*.md.lock`。
  - [x] 显式 repo 的锁位于可信 `.codex/project-workflow` 内，NONE 模式不执行 Git。
  - [x] 无 repo 的兼容命令使用权限受限的稳定临时锁。
  - [x] 并发写、符号链接、父目录交换和锁超时测试通过。
  - [x] 旧锁只显式清理，不在可能有旧进程时自动删除。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_workflow_state.py' -v`
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_orchestration_state.py' -v`
- Evidence：见上方受控状态块及交付报告。

## T02 双维度任务状态与双语渲染

<!-- project-workflow:task-status T02:start -->
- 实现状态：✅ 已完成
- 验收状态：✅ 已通过
- 证据：双维状态、CAS、依赖门禁、中文/英语渲染与幂等迁移已实现；test_task_state.py 7 项全部通过
<!-- project-workflow:task-status T02:end -->

- Depends-On：T01
- Write-Scope：
  - `plugins/project-workflow/scripts/task_state.py`
  - `plugins/project-workflow/locales/zh-CN.json`
  - `plugins/project-workflow/locales/en-US.json`
  - `plugins/project-workflow/tests/test_task_state.py`
- Agent-Eligible：false
- 目标：建立所有执行模式通用的内部任务状态、原子转换、进度汇总与中英 Markdown 渲染。
- 范围外：生命周期完成门禁、Doctor、技能文档和 README。
- 风险：展示块覆盖用户正文；状态与文档失步；同一状态在中英文中语义不一致。
- 验收标准：
  - [x] 实现与验收状态集合、合法转换、证据要求和 CAS 均有测试。
  - [x] SINGLE_AGENT 同时最多一个实现中任务，依赖未完成不能开始。
  - [x] 中文与英语符号一致、文字准确；其他语言稳定回退英语。
  - [x] 渲染只替换受控标记块，重复执行字节级幂等，不翻译自由文本。
  - [x] 实现完成但验收部分通过能分别统计，不再显示为编码进行中。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_task_state.py' -v`
- Evidence：见上方受控状态块及交付报告。

## T03 生命周期、调度与旧计划迁移集成

<!-- project-workflow:task-status T03:start -->
- 实现状态：✅ 已完成
- 验收状态：✅ 已通过
- 证据：生命周期开始/恢复/完成门禁、v0.4/v0.5 调度兼容、Doctor 与显式旧锁清理已实现；workflow 50、orchestration 50、Doctor 22、final gate 12 与 task state 8 项通过
<!-- project-workflow:task-status T03:end -->

- Depends-On：T02
- Write-Scope：
  - `plugins/project-workflow/scripts/workflow_state.py`
  - `plugins/project-workflow/scripts/orchestration_state.py`
  - `plugins/project-workflow/scripts/project_workflow_doctor.py`
  - `plugins/project-workflow/tests/test_workflow_state.py`
  - `plugins/project-workflow/tests/test_orchestration_state.py`
  - `plugins/project-workflow/tests/test_project_workflow_doctor.py`
  - `plugins/project-workflow/tests/test_final_gate_contract.py`
- Agent-Eligible：false
- 目标：把双状态接入计划开始、恢复、阻塞和完成门禁，并提供保守、显式、幂等的 v0.4 迁移。
- 范围外：用户文档措辞和插件安装。
- 风险：旧计划完成语义回退；双重状态源；迁移失败后留下半写计划。
- 验收标准：
  - [x] 新计划以内部状态为任务状态唯一事实来源，调度状态只负责所有权与运行身份。
  - [x] 最终完成要求全部实现完成且所有适用验收通过。
  - [x] PARTIAL、FAILED、BLOCKED 或缺证据均不能完成计划。
  - [x] v0.4 计划迁移按设计矩阵保守映射，重复迁移幂等，失败原子回滚。
  - [x] 未迁移旧计划继续兼容；未知 schema、状态和未来版本失败关闭。
  - [x] Doctor 能区分无状态旧计划、可迁移计划、损坏状态和完成不一致。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_*state.py' -v`
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_final_gate_contract.py' -v`
- Evidence：见上方受控状态块及交付报告。

## T04 技能协议与双语公开文档

<!-- project-workflow:task-status T04:start -->
- 实现状态：✅ 已完成
- 验收状态：✅ 已通过
- 证据：计划/执行技能、工作流协议、检查清单及中英 README 已统一为双状态和双语契约；documented_commands 12 项通过，index/plan/execute 三个技能快速校验通过
<!-- project-workflow:task-status T04:end -->

- Depends-On：T03
- Write-Scope：
  - `plugins/project-workflow/skills/index/SKILL.md`
  - `plugins/project-workflow/skills/plan/SKILL.md`
  - `plugins/project-workflow/skills/execute/SKILL.md`
  - `plugins/project-workflow/references/workflow-protocol.md`
  - `plugins/project-workflow/references/execution-checklists.md`
  - `plugins/project-workflow/references/multi-agent-orchestration.md`
  - `plugins/project-workflow/tests/test_documented_commands.py`
  - `README.md`
  - `README.zh-CN.md`
- Agent-Eligible：false
- 目标：让新计划和执行流程使用双状态、中文/英语展示与内部锁，不再要求模型手工维护旧符号。
- 范围外：增加第三种语言、自动翻译任务正文、修改 Codex UI。
- 风险：技能仍指导旧标记；中英文 README 命令不一致；公开文档暴露内部枚举或路径。
- 验收标准：
  - [x] 计划技能解析并持久化 `zh-CN` 或 `en-US`，执行和恢复沿用既定语言。
  - [x] 用户可见状态使用本地化文字与固定符号，内部枚举仅用于机器状态。
  - [x] 技能不再要求通过手工 `[~]/[x]` 管理任务状态。
  - [x] 中英文 README、协议、命令帮助和 argparse 保持一致。
  - [x] skill-creator 快速校验通过，技能描述仍保持准确触发边界。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_documented_commands.py' -v`
- Validation（DISCOVERY）：`python3 /Users/chenjiaxing/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/project-workflow/skills/index`
- Evidence：见上方受控状态块及交付报告。

## T05 黑盒兼容验证、版本与交付

<!-- project-workflow:task-status T05:start -->
- 实现状态：✅ 已完成
- 验收状态：✅ 已通过
- 证据：v0.5.0 清单、黑盒契约、全量测试与交付报告已完成；插件 245 项通过/1 项预期跳过；安装器 8 项通过；技能、插件、编译、Doctor 与 diff 检查通过
<!-- project-workflow:task-status T05:end -->

- Depends-On：T01, T02, T03, T04
- Write-Scope：
  - `plugins/project-workflow/tests/test_state_ux_contract.py`
  - `plugins/project-workflow/.codex-plugin/plugin.json`
  - `.agents/plugins/marketplace.json`
  - `scripts/install_local_plugin.py`
  - `tests/test_install_local_plugin.py`
  - `docs/plan/009-Project-Workflow-v0.5.0状态体验与内部锁实施计划.md`
  - `docs/delivery/009-Project-Workflow-v0.5.0状态体验与内部锁交付报告.md`
- Agent-Eligible：false
- Role：CONTRACT_VERIFIER
- Independent-Verification：受当前会话禁止子智能体约束，由协调者以只读取原始需求、公开契约和验收标准的黑盒测试阶段执行；该隔离弱于原生独立 Worker，交付时明确披露。
- 目标：从用户视角验证文档不再出现相邻锁、实现/验收进度准确、中文/英语稳定、旧计划兼容，并完成版本和交付收口。
- 范围外：commit、tag、push、发布和未经授权的本机重装。
- 风险：实现形状影响测试；版本清单不一致；真实安装包漏资源。
- 验收标准：
  - [x] 黑盒临时仓库验证新计划从创建到完成的状态、渲染和锁布局。
  - [x] 中文与英语各完成一条完整生命周期，其他语言回退英语。
  - [x] 真实 v0.4 夹具迁移后不再出现多个“编码进行中”的错误展示。
  - [x] 本 009 计划作为自举样例迁移为新中文双状态展示。
  - [x] 插件全量测试、安装器测试、Python 编译、skill 校验和 `git diff --check` 通过。
  - [x] 源码版本、marketplace 与安装器资源清单一致；未授权时不执行本机重装。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -v`
- Validation（DISCOVERY）：`python3 -m unittest discover -s tests -v`
- Validation（DISCOVERY）：`python3 -m compileall -q plugins/project-workflow scripts tests`
- Evidence：见上方受控状态块及交付报告。

## 边界矩阵

- 类型/空值：缺 plan ID、task ID、语言、状态、证据，布尔冒充整数，错误容器。
- 数值：revision/stateVersion 的负数、零、布尔、极大值和 CAS 不一致。
- 集合/身份：重复任务、未知依赖、循环依赖、未知任务、空任务计划。
- 时间：本功能不新增业务时间字段；锁超时和原子替换时序适用。
- 重试/原子性：重复迁移、重复渲染、重复完成、崩溃中断、CAS 冲突和半写恢复。
- 错误面：损坏 JSON、未知 schema/状态/语言、缺翻译键、稳定退出码、无 traceback。
- 并发/恢复：两个状态写者、锁目录替换、旧新版本并行、活动任务所有权和恢复。

## 迁移状态矩阵

迁移矩阵以设计文档第 7 节为准。特别要求：旧 `[~]` 和 `[!]` 不得根据自由文本猜测验收完成度；迁移必须保守且显式提示歧义。迁移测试只在临时仓库和夹具上执行，未经用户确认不批量改写现有业务计划。

## 执行与授权

- 采用 `SINGLE_AGENT`，严格串行；不创建子智能体。
- Git 是主要变更证据；执行前工作区已确认干净。
- 回滚使用当前分支 HEAD 和逐文件差异，不执行 reset、checkout 或删除用户文件。
- commit、tag、push、发布、本机插件重装均未授权。
- 旧版规划 helper 在本计划确认时可能创建一个相邻 `.lock`；T01 完成后由新显式清理流程在确认无旧进程持锁的测试条件下移除，后续不再生成。
