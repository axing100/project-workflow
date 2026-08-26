---
workflow: "project-workflow/v1"
plan_id: "project-workflow-v0-4-final-gate-hardening"
revision: 1
phase: "COMPLETED"
approved_revision: 1
approved_at: "2026-08-25T11:49:47+00:00"
confirmation_record: "开始执行"
workflow_profile: "FULL"
conversation_title: "Project Workflow 完成门禁加固"
progress_heartbeat_minutes: 5
vcs_mode: "AUTO"
resolved_vcs_mode: "GIT"
rollback_required: "true"
rollback_strategy: "逐文件撤销本计划改动，保留用户现有工作区；必要时以 v0.3.0 与当前差异清单恢复"
rollback_evidence: "Git HEAD v0.3.0、执行前 dirty-worktree 清单与任务级变更证据"
rollback_verification: "VERIFIED"
execution_mode: "AUTO_MULTI_AGENT"
max_workers: 2
agent_topology: "SHARED_WORKSPACE"
progress_reporting: "COMPACT"
parallelism_policy: "BENEFIT_GATED"
minimum_parallel_savings_percent: 20
orchestration_state: ".codex/project-workflow/project-workflow-v0-4-final-gate-hardening/orchestration.json"
commit_authorized: "false"
push_authorized: "false"
final_orchestration_state_version: 18
---

# Project Workflow v0.4.0 完成门禁与文件安全实施计划

设计：[007-Project-Workflow-v0.4.0完成门禁与文件安全设计](../design/007-Project-Workflow-v0.4.0完成门禁与文件安全设计.md)

## T01 调度状态、范围与最终验证核心

- 状态：[x]
- Owner：原生 Worker
- Depends-On：无
- Write-Scope：
  - `plugins/project-workflow/scripts/orchestration_state.py`
  - `plugins/project-workflow/tests/test_orchestration_state.py`
- Agent-Eligible：true
- Estimated-Minutes：75
- Coordination-Minutes：8
- Critical-Path：true
- 目标：仓库内状态路径、范围规范化、Mac 大小写/Unicode、严格事件时间、runtime 身份唯一和可复用完整 final validator。
- 验收：别名范围与大小写等价范围冲突；外部状态 mutation 阻断；重复 runtime 身份、畸形事件和未完成 final 均拒绝。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_orchestration_state.py' -v`
- Evidence：限定两路径完成；调度专项 47/47、Workflow contract 15/15、Doctor 18/18、Python 3.9 编译与 `diff-check` 通过。已验证内部状态边界、scope 规范化、运行身份唯一、严格事件时间与可复用 `validate_final_state`。

## T02 生命周期、审批与原子完成

- 状态：[x]
- Owner：原生 Worker
- Depends-On：T01
- Write-Scope：
  - `plugins/project-workflow/scripts/workflow_state.py`
  - `plugins/project-workflow/tests/test_workflow_state.py`
- Agent-Eligible：true
- Estimated-Minutes：70
- Coordination-Minutes：8
- Critical-Path：true
- 目标：严格审批记录、IN_PROGRESS 幂等 resume、NONE 单智能体拓扑、计划锁/CAS、权限保持与绑定调度最终证据的 complete。
- 验收：非法历史审批拒绝；并发确认只有一个成功；完成失败不改字节；0644 保持；NONE 单智能体正常执行。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_workflow_state.py' -v`
- Evidence：限定两路径完成；生命周期专项 41/41、调度专项 47/47 通过，Python 编译与 `diff-check` 通过。已验证严格审批类型/时区、IN_PROGRESS 幂等恢复、稳定计划锁、revision/phase/SHA-256 CAS、0644 权限保持、仓库路径边界，以及在同一调度锁内完成最终校验、绑定 `state_version` 并为当前 NONE 计划重新生成范围受控的文件系统比较。

## T03 NONE 快照 fd 安全与特殊文件

- 状态：[x]
- Owner：原生 Worker
- Depends-On：无
- Write-Scope：
  - `plugins/project-workflow/scripts/filesystem_snapshot.py`
  - `plugins/project-workflow/tests/test_filesystem_snapshot.py`
- Agent-Eligible：true
- Estimated-Minutes：90
- Coordination-Minutes：10
- Critical-Path：true
- 目标：O_NOFOLLOW/fstat 哈希、可信目录 fd 写入、目录 mode、特殊文件 fail-closed 与崩溃持久性。
- 验收：文件/父目录 symlink 交换不能读取或写入外部；FIFO/socket 不报告 clean；目录 chmod 可见；旧快照兼容。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_filesystem_snapshot.py' -v`
- Evidence：限定两路径完成；专项 21/21（当前沙箱 socket 用例跳过，非沙箱已通过）、safety 12/12、VCS 9/9、Python 3.9 编译与 `diff-check` 通过。已验证 O_NOFOLLOW/fstat、父目录 fd、目录 mode、特殊文件 fail-closed 与持久 fsync。

## T04 Doctor、路径与安装器收口

- 状态：[x]
- Owner：协调者
- Depends-On：T01, T02
- Write-Scope：
  - `plugins/project-workflow/scripts/project_workflow_doctor.py`
  - `plugins/project-workflow/tests/test_project_workflow_doctor.py`
  - `scripts/install_local_plugin.py`
  - `tests/test_install_local_plugin.py`
- Agent-Eligible：false
- 目标：Doctor 复用完整 final validator、所有 repo-relative 输入防逃逸、本地 cachebuster 唯一且保持 SemVer。
- 验收：已完成计划的未完成调度被 Doctor 阻断；`../`/外部路径拒绝；同秒连续 token 不重复。
- Validation（DISCOVERY）：
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_project_workflow_doctor.py' -v`
  - `python3 -m unittest discover -s tests -p 'test_install_local_plugin.py' -v`
- Evidence：限定四路径完成；Doctor 20/20、安装器 8/8、Python 编译与 `diff-check` 通过。Doctor 对完成计划复用 `validate_final_state` 并核对绑定版本，计划/调度输入拒绝仓库逃逸；本机 cachebuster 使用微秒与随机 nonce，生成值保持有效 SemVer。

## T05 技能、协议与双语文档

- 状态：[x]
- Owner：协调者
- Depends-On：T01, T02, T03, T04
- Write-Scope：
  - `plugins/project-workflow/skills/plan/SKILL.md`
  - `plugins/project-workflow/skills/execute/SKILL.md`
  - `plugins/project-workflow/references/workflow-protocol.md`
  - `plugins/project-workflow/references/execution-checklists.md`
  - `plugins/project-workflow/references/multi-agent-orchestration.md`
  - `README.md`
  - `README.zh-CN.md`
  - `plugins/project-workflow/tests/test_documented_commands.py`
- Agent-Eligible：false
- 目标：统一 topology、resume、finalize、路径和快照证据公开契约。
- 验收：文档示例与 argparse/实际语义一致；不再宣称未实现的完成原子性。
- Validation（DISCOVERY）：三技能 quick_validate、文档命令 discovery、插件 validate。
- Evidence：限定八路径完成；三项技能 quick-validate 全部通过，文档命令 11/11，插件结构校验与 `diff-check` 通过。公开契约已统一 SINGLE_AGENT/SHARED_WORKSPACE、显式 `--repo`、生命周期 CAS、幂等 resume、最终调度版本绑定、外部历史状态只读与 fd 安全快照语义。

## T06 独立安全与恢复契约验证

- 状态：[x]
- Owner：独立原生 Worker
- Depends-On：T01, T02, T03, T04, T05
- Write-Scope：
  - `plugins/project-workflow/tests/test_final_gate_contract.py`
  - `plugins/project-workflow/tests/test_filesystem_race_contract.py`
- Agent-Eligible：true
- Estimated-Minutes：45
- Coordination-Minutes：5
- Critical-Path：true
- Role：CONTRACT_VERIFIER
- Independent-Verification：true
- 输入隔离：只接收本设计、原始审查发现和公开验收标准，不接收实现讨论或 Worker 自评。
- 验收：黑盒复现全部 P1、普通 P2 和 fd 安全边界；历史迁移矩阵逐项验证。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_*contract.py' -v`
- Evidence：独立验证仅写两项新黑盒测试；final-gate 12/12，filesystem-race 连续三轮均 5 通过、2 项因沙箱禁止 socket/device fixture 跳过，安装器 8/8，`diff-check` 通过。首轮发现的未加引号容器确认记录偏差已在生产解析器最小修复并由原用例复验；未发现其他生产偏差。

## T07 集成、交付与本机重装

- 状态：[x]
- Owner：协调者
- Depends-On：T01, T02, T03, T04, T05, T06
- Write-Scope：
  - `docs/plan/007-Project-Workflow-v0.4.0完成门禁与文件安全实施计划.md`
  - `docs/delivery/007-Project-Workflow-v0.4.0完成门禁与文件安全交付报告.md`
  - `plugins/project-workflow/.codex-plugin/plugin.json`
  - `plugins/project-workflow/tests/test_recovery_contract.py`
- Agent-Eligible：false
- 目标：全量回归、迁移证据、源码版本核对、交付报告与本机隔离重装。
- 执行偏差：T01 收紧外部调度状态为只读后，旧恢复测试夹具需迁入仓库内部状态根；该测试文件作为非生产、非契约变更的集成迁移项纳入 T07，不放宽生产安全边界。
- 验收：插件/安装器/技能/结构/Python/diff-check 全通过；源码仍为 0.4.0；安装缓存包含修复。
- Validation（DISCOVERY）：插件与安装器全量、三技能 quick_validate、validate_plugin、compileall、diff-check。
- Evidence：插件全量 207 项通过、3 项因受限沙箱无法构造 socket/device 夹具而跳过；安装器 8/8、文档契约 11/11、三个技能 quick-validate、插件结构验证、Python 3.9 编译与 `diff-check` 全部通过。已生成 007 号交付报告；源码 manifest 保持 0.4.0，本机隔离安装为 `0.4.0+codex.20260825125744636785-7027c810`，安装副本除 manifest 构建元数据外与源码插件一致。未执行 commit、tag、push 或部署。

## 调度与收益

- Wave 1 并行 T01（75+8）与 T03（90+10）：串行 165 分钟，并行含协调约 108 分钟，预计节省 34.5%。
- T02 依赖 T01 的 final validator，避免两个 Worker 同时定义完成接口。
- T04 由协调者在 T01/T02 稳定后集成 Doctor 与安装器。
- T06 是 FULL 计划的单任务独立验证例外。
- Worker 上限 2；冲突、槽位不足或 fd API 不可移植时安全降级为协调者串行。

## 边界矩阵

- 类型/null：审批、事件、范围、runtime 身份、快照记录覆盖非法标量与容器。
- 数值：state_version、mode、时间范围、锁超时与 cachebuster 长度覆盖边界。
- 集合/身份：重复范围、等价路径、重复 Worker 身份、重复事件和任务覆盖。
- 时间：naive、非法 offset、回拨、溢出和同秒重装覆盖。
- 重试/原子性：并发批准、CAS 冲突、完成校验失败、崩溃重入和重复 resume 覆盖。
- 错误面：稳定错误、无 traceback、损坏历史状态和恢复失败覆盖。
- 并发/恢复：symlink 交换、锁竞争、活跃 Worker、缺失调度与未知状态覆盖。

## Definition of Done

- T01–T07 均有终态与证据，无未解释的 `[~]`。
- 全部独立黑盒发现均有回归测试，独立验证为 VERIFIED。
- 工作区原有改动保留，无 reset、checkout 覆盖或未授权 Git 写操作。
- commit、tag、push、部署均未执行，除非用户后续另行明确授权。
