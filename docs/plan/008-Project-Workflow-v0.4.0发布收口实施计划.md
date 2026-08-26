---
workflow: "project-workflow/v1"
plan_id: "project-workflow-v0-4-release-closure"
revision: 1
phase: "COMPLETED"
approved_revision: 1
approved_at: "2026-08-25T16:53:40+00:00"
confirmation_record: "确认执行"
policy_contract: "v0.4"
workflow_profile: "FULL"
conversation_title: "Project Workflow 发布收口"
progress_heartbeat_minutes: 5
vcs_mode: "AUTO"
resolved_vcs_mode: "GIT"
rollback_required: "true"
rollback_strategy: "逐文件撤销 008 号计划的局部改动，保留此前 v0.4.0 工作区与用户现有修改"
rollback_evidence: "当前 Git HEAD、执行前 dirty-worktree 清单、五项原始黑盒复现与任务级差异证据"
rollback_verification: "VERIFIED"
execution_mode: "AUTO_MULTI_AGENT"
max_workers: 2
agent_topology: "SHARED_WORKSPACE"
progress_reporting: "COMPACT"
parallelism_policy: "BENEFIT_GATED"
minimum_parallel_savings_percent: 20
orchestration_state: ".codex/project-workflow/project-workflow-v0-4-release-closure/orchestration.json"
commit_authorized: "false"
push_authorized: "false"
final_orchestration_state_version: 14
---

# Project Workflow v0.4.0 发布收口实施计划

设计：[008-Project-Workflow-v0.4.0发布收口设计](../design/008-Project-Workflow-v0.4.0发布收口设计.md)

## T01 NONE 证据链与当前契约

- 状态：[x]
- Owner：none-evidence-worker
- Depends-On：无
- Write-Scope：
  - `plugins/project-workflow/scripts/workflow_state.py`
  - `plugins/project-workflow/scripts/filesystem_snapshot.py`
  - `plugins/project-workflow/tests/test_workflow_state.py`
  - `plugins/project-workflow/tests/test_filesystem_snapshot.py`
- Agent-Eligible：true
- Estimated-Minutes：80
- Coordination-Minutes：8
- Critical-Path：true
- 目标：明确 v0.4 plan contract，阻止 baseline 覆盖并绑定批准记录，持久化和复核最终文件证据。
- 范围外：Doctor、调度 Worker 身份、公开文档。
- 验收：STANDARD/NONE 无证据无法完成；同路径 create 不能覆盖；CAS 恢复可控；完成计划绑定可复核 artifact；历史纯 v0.3 仍兼容。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_workflow_state.py' -v`
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_filesystem_snapshot.py' -v`
- Evidence：限定四路径完成；生命周期 45/45、快照 24 通过 1 项环境跳过、竞态 5 通过 2 项环境跳过、Python 编译与 scoped diff-check 通过。新旧契约分类、审批配置摘要、不可覆盖 baseline、摘要 CAS 恢复、批准绑定、final artifact 与共享完成证据验证器均已验证。

## T02 调度状态 fd 写入与 Worker 身份

- 状态：[x]
- Owner：orchestration-fd-worker
- Depends-On：无
- Write-Scope：
  - `plugins/project-workflow/scripts/orchestration_state.py`
  - `plugins/project-workflow/tests/test_orchestration_state.py`
- Agent-Eligible：true
- Estimated-Minutes：70
- Coordination-Minutes：7
- Critical-Path：true
- 目标：调度状态读锁写统一使用可信目录 fd；v0.4 完成 Worker 必须具备真实原生身份与验证证据。
- 范围外：快照、Doctor、技能文档。
- 验收：持锁状态下父目录交换不能外写；v0.4 无身份 Worker 最终验证失败；纯 legacy 状态继续显示 UNAVAILABLE；CAS 与恢复语义不回退。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_orchestration_state.py' -v`
- Evidence：限定两路径完成；调度专项 50/50、Workflow contract 15/15、并发 writer 压力 5/5、Python 编译与 scoped diff-check 通过。显式 repo 的内部状态读锁写已绑定可信目录 fd；v0.4 完成 Worker 身份、状态、验证与时间严格校验，纯 legacy 继续兼容。

## T03 Doctor 与公开契约集成

- 状态：[x]
- Owner：协调者
- Depends-On：T01, T02
- Write-Scope：
  - `plugins/project-workflow/scripts/project_workflow_doctor.py`
  - `plugins/project-workflow/tests/test_project_workflow_doctor.py`
  - `plugins/project-workflow/skills/plan/SKILL.md`
  - `plugins/project-workflow/skills/execute/SKILL.md`
  - `plugins/project-workflow/references/workflow-protocol.md`
  - `plugins/project-workflow/references/execution-checklists.md`
  - `plugins/project-workflow/references/multi-agent-orchestration.md`
  - `plugins/project-workflow/tests/test_documented_commands.py`
  - `README.md`
  - `README.zh-CN.md`
- Agent-Eligible：false
- 目标：Doctor/validate 复用完成证据验证器；公开命令准确描述 baseline 创建、绑定、恢复和最终 artifact。
- 验收：删除或伪造完成证据时 Doctor 阻断；文档命令与 argparse 一致；不扩大到无关 UX 或功能。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_project_workflow_doctor.py' -v`
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_documented_commands.py' -v`
- Evidence：Doctor 复用共享完成证据验证器，完成后的基线、最终 artifact、摘要、计数或调度版本缺失/篡改均稳定阻断；Doctor 22/22、文档契约 11/11、插件全量 222 项通过（3 项因沙箱禁止 socket/device fixture 跳过）、安装器 8/8、Python 编译与 diff-check 通过。为适配已批准的新安全契约，仅迁移 `test_final_gate_contract.py`、`test_safety_contract.py`、`test_recovery_contract.py`、`test_vcs_contract.py` 四个既有黑盒夹具/预期；未扩大生产代码或产品功能范围。

## T04 独立发布收口验证

- 状态：[x]
- Owner：release-closure-verifier
- Depends-On：T01, T02, T03
- Write-Scope：
  - `plugins/project-workflow/tests/test_release_closure_contract.py`
- Agent-Eligible：true
- Estimated-Minutes：35
- Coordination-Minutes：5
- Critical-Path：true
- Role：CONTRACT_VERIFIER
- Independent-Verification：true
- 输入隔离：只提供原始五项复现、本设计和公开验收标准，不提供实现讨论或实现者自评。
- 验收：五项原始复现全部失败关闭；迁移矩阵、篡改、覆盖、目录交换和历史兼容均有黑盒证据；继续审查并报告任何明显 P0/P1/P2。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_release_closure_contract.py' -v`
- Evidence：独立原生 Worker 仅新增 `test_release_closure_contract.py`，8/8 黑盒契约通过；插件全量 230 项通过、3 项环境跳过，安装器 8/8、Python 编译与 diff-check 通过。五项原始复现、canonical NONE 确认入口、冲突重试、legacy 兼容均失败关闭或按契约兼容；未发现新的明显 P0/P1/P2 生产问题。

## T05 集成、交付与本机重装

- 状态：[x]
- Owner：协调者
- Depends-On：T01, T02, T03, T04
- Write-Scope：
  - `docs/plan/008-Project-Workflow-v0.4.0发布收口实施计划.md`
  - `docs/delivery/008-Project-Workflow-v0.4.0发布收口交付报告.md`
  - `plugins/project-workflow/.codex-plugin/plugin.json`
- Agent-Eligible：false
- 目标：完整回归、迁移核对、实际安装副本验证和最终独立复审收口。
- 验收：插件/安装器/技能/结构/Python/diff-check 全通过；源码仍为 0.4.0；本机缓存包含最终修复；独立复审不存在明显问题。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -v`
- Validation（DISCOVERY）：`python3 -m unittest discover -s tests -v`
- Evidence：源码清单保持 `0.4.0`；本机已安装 `0.4.0+codex.20260825175047281354-4ddea5ec`。四个核心脚本与 execute skill 的安装副本 SHA-256 和源码一致，安装副本 CLI 帮助正常，安装副本 Doctor 在可写临时仓库返回 OK。源码插件全量 230 项通过、3 项环境跳过，安装器 8/8、Python 编译与 diff-check 通过；交付报告已落盘。未 commit、tag、push 或部署。

## 调度与收益

- Wave 1 并行 T01（80+8）与 T02（70+7）：串行实现约 150 分钟，并行含协调约 95 分钟，预计节省约 36.7%。
- T03 在两个生产契约稳定后串行集成 Doctor 与文档，避免重复定义完成验证器。
- T04 是 FULL 计划的独立验证例外，只写新的黑盒测试文件。
- Worker 上限 2；创建失败、范围冲突或运行容量不足时由协调者串行接管，不改变范围。

## 适用边界矩阵

- 类型/null：policy marker、绑定对象、摘要、计数、runtime 身份的缺失、容器、布尔和错误标量。
- 数值：revision/state_version/计数的负数、布尔、极大值和不一致值。
- 集合/身份：重复 scopes/excludes、重复 runtime 身份、空任务与未知字段。
- 时间：审批、spawn、finish 的 naive、非法 offset、先后关系与缺失值。
- 重试/原子性：baseline 重复 create、摘要 CAS 冲突、完成 artifact 已存在、计划写失败、重复完成。
- 错误面：损坏 JSON、缺失 artifact、未知 policy、稳定退出码和无 traceback。
- 并发/恢复：计划/状态竞争、父目录交换、崩溃重入、活跃或孤儿 Worker。

## N/A 边界

- 租约期限：当前 schema 没有 lease 字段；以 runtime identity、state_version、slot/scope 与 stopped evidence 覆盖恢复所有权。
- 网络/数据库迁移：插件仅修改本地 Markdown/JSON 状态，没有网络协议或数据库结构。
- UI：不修改 Codex 原生组件、标题 API 或智能体图标。

## 发布门禁

- 五项原始复现全部被契约测试关闭。
- 独立验证者没有未解决的明显 P0/P1/P2；若发现则回到对应实现任务返工并复验。
- 工作区原有修改保留；不 reset、checkout 或删除用户文件。
- commit、tag、push、部署均未授权。
