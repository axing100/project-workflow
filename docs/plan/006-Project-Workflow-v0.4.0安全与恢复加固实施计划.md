---
workflow: "project-workflow/v1"
plan_id: "project-workflow-v0-4-safety-hardening"
revision: 1
phase: "COMPLETED"
workflow_profile: "FULL"
approved_revision: 1
approved_at: "2026-08-25T09:42:56+00:00"
confirmation_record: "确认执行"
conversation_title: "Project Workflow 安全加固"
progress_heartbeat_minutes: 5
vcs_mode: "AUTO"
resolved_vcs_mode: "GIT"
rollback_required: "false"
execution_mode: "AUTO_MULTI_AGENT"
max_workers: 2
agent_topology: "SHARED_WORKSPACE"
progress_reporting: "COMPACT"
parallelism_policy: "BENEFIT_GATED"
minimum_parallel_savings_percent: 20
orchestration_state: ".codex/project-workflow/project-workflow-v0-4-safety-hardening/orchestration.json"
---

# Project Workflow v0.4.0 安全与恢复加固实施计划

## 1. 目标与基线

按[006 号设计](../design/006-Project-Workflow-v0.4.0安全与恢复加固设计.md)修复独立审查的全部明确问题。基线提交为 `c4f45e4db678865287ef6f9fb8aa35fc567b5806`；当前工作区含用户尚未提交的 v0.4.0 变更，全部保留。已知回归基线为插件 106/106、安装器 6/6。

Doctor 因当前 Codex 沙箱无法直接写源仓库内部状态目录而报 `STATE_DIRECTORY_NOT_WRITABLE`；仓库可读、Git 可用且 VCS 解析为 `GIT`。计划内部状态将通过受控权限创建。

本轮未授权 commit、tag、push、远程发布或部署。全部验收通过后可沿用用户对 v0.4.0 本机更新的授权；如系统再次要求审批，以系统审批为准。

## 2. 任务图

### T01 Doctor 信任与完整预检

- 状态：[x]
- Owner：原生 Worker
- Depends-On：none
- Write-Scope：
  - `plugins/project-workflow/scripts/project_workflow_doctor.py`
  - `plugins/project-workflow/tests/test_project_workflow_doctor.py`
- Agent-Eligible：true
- Parallel-Group：wave-1
- Estimated-Minutes：30
- Coordination-Minutes：5
- Critical-Path：true
- 目标：只执行当前已安装的可信脚本，静态处理外部根；复用完整调度校验，Doctor 阻止状态根符号链接逃逸。
- 验收：恶意目标仓库脚本不被执行；缺字段、依赖环、范围冲突、伪造 Worker 均稳定阻断。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_project_workflow_doctor.py' -v`
- Evidence：两个约定路径完成；Doctor 专项 16/16、Python 3.9 编译与 `diff-check` 通过。已验证目标仓库脚本绝不执行、外部插件根静态检查并阻断、调度状态深校验和状态目录符号链接阻断。

### T02 生命周期、Worker 停止与并发状态

- 状态：[x]
- Owner：原生 Worker
- Depends-On：none
- Write-Scope：
  - `plugins/project-workflow/scripts/workflow_state.py`
  - `plugins/project-workflow/scripts/orchestration_state.py`
  - `plugins/project-workflow/tests/test_workflow_state.py`
  - `plugins/project-workflow/tests/test_orchestration_state.py`
- Agent-Eligible：true
- Parallel-Group：wave-1
- Estimated-Minutes：55
- Coordination-Minutes：8
- Critical-Path：true
- 目标：统一 resume 门禁，增加高风险回滚字段、NONE 拓扑校验、活跃 Worker 中断后释放、文件锁与 `state_version` CAS。
- 验收：恢复不得绕过审批/VCS；未停止 Worker 仍占用槽位和范围；并发写入不丢失；设计第 8 节历史状态映射有自动化覆盖。
- Validation（DISCOVERY）：
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_workflow_state.py' -v`
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_orchestration_state.py' -v`
- Evidence：四个约定路径完成；新增恢复门禁、Worker 停止证据、5 秒文件锁、`state_version`/CAS、NONE 拓扑校验与统一路径规范化。目标测试 67/67、插件全量 128/128、安装器 6/6，Python 编译与 `diff-check` 通过。

### T03 无 Git 证据与路径安全

- 状态：[x]
- Owner：原生 Worker
- Depends-On：none
- Write-Scope：
  - `plugins/project-workflow/scripts/filesystem_snapshot.py`
  - `plugins/project-workflow/tests/test_filesystem_snapshot.py`
- Agent-Eligible：true
- Parallel-Group：wave-1
- Estimated-Minutes：40
- Coordination-Minutes：5
- Critical-Path：true
- 目标：阻止状态根符号链接逃逸，越界默认失败，记录 mode bits，支持持久化排除和精简输出，保留旧基线兼容。
- 验收：工作区外不产生文件；`out_of_scope` 非空返回非零；`chmod` 可检测；大清单不默认进入 stdout；旧基线比较可用。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_filesystem_snapshot.py' -v`
- Evidence：两个约定路径完成；快照专项 13/13、Python 编译与 `diff-check` 通过。已验证符号链接状态根阻断、越界默认退出 3、mode 变化、排除持久化、旧基线兼容、摘要输出与仓库相对路径。

### T04 技能、协议与双语文档一致性

- 状态：[x]
- Owner：协调者（收益门禁判定单任务不适合额外 Worker）
- Depends-On：T01, T02, T03
- Write-Scope：
  - `plugins/project-workflow/skills/index/SKILL.md`
  - `plugins/project-workflow/skills/plan/SKILL.md`
  - `plugins/project-workflow/skills/execute/SKILL.md`
  - `plugins/project-workflow/references/workflow-protocol.md`
  - `plugins/project-workflow/references/execution-checklists.md`
  - `plugins/project-workflow/references/multi-agent-orchestration.md`
  - `README.md`
  - `README.zh-CN.md`
  - `plugins/project-workflow/tests/test_documented_commands.py`
- Agent-Eligible：true
- Estimated-Minutes：35
- Coordination-Minutes：5
- Critical-Path：true
- 目标：删除跳过门禁矛盾，同步新 resume/release/snapshot 契约，修正 `inspect`、路径、心跳和原生智能体图标能力边界。
- 验收：公开命令与 argparse 全部对齐；明确“不要门禁即退出插件”；不宣称插件可配置原生 Agent 图标。
- Validation（DISCOVERY）：
  - 三个技能 `quick_validate.py`
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_documented_commands.py' -v`
- Evidence：九个约定路径完成；公开文档已统一恢复、CAS、Worker 停止证据、NONE 快照与原生 UI 能力边界。文档命令 10/10、三技能校验、插件校验与 `diff-check` 全部通过。

### T05 独立安全与迁移契约验证

- 状态：[x]
- Owner：独立原生 Worker
- Depends-On：T01, T02, T03, T04
- Write-Scope：
  - `plugins/project-workflow/tests/test_safety_contract.py`
  - `plugins/project-workflow/tests/test_recovery_contract.py`
- Agent-Eligible：true
- Estimated-Minutes：30
- Coordination-Minutes：5
- Critical-Path：true
- Role：CONTRACT_VERIFIER
- Independent-Verification：true
- 输入隔离：只接收本设计公开契约与验收标准，不接收实现讨论或 Worker 自评。
- 验收：以黑盒方式覆盖恶意仓库、路径逃逸、越界退出码、恢复漂移、活跃 Worker、竞争写入、高风险回滚、旧状态与文档命令。
- Validation（DISCOVERY）：`python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_*contract.py' -v`
- Evidence：两个约定测试文件新增 24 个隔离黑盒用例；安全 12/12、恢复 12/12、插件全量 156/156、全部插件 Python 编译与 `diff-check` 通过，独立结论为 VERIFIED。

### T06 集成、交付与本机更新

- 状态：[x]
- Owner：协调者
- Depends-On：T01, T02, T03, T04, T05
- Write-Scope：
  - `docs/plan/006-Project-Workflow-v0.4.0安全与恢复加固实施计划.md`
  - `docs/delivery/006-Project-Workflow-v0.4.0安全与恢复加固交付报告.md`
  - `plugins/project-workflow/.codex-plugin/plugin.json`
  - `scripts/install_local_plugin.py`
  - `tests/test_install_local_plugin.py`
- Agent-Eligible：false
- 目标：完成集成复核、全量回归、迁移证据、交付报告和本机 cachebuster 重装。
- 验收：插件全量、安装器、三技能、插件结构、Python 编译、`git diff --check` 通过；源码版本保持 `0.4.0`；已安装缓存含修复。
- Validation（DISCOVERY）：
  - `python3 -m unittest discover -s plugins/project-workflow/tests -v`
  - `python3 -m unittest discover -s tests -v`
  - 三个技能 `quick_validate.py`、插件 `validate_plugin.py`、Python `py_compile`、`git diff --check`
- Evidence：插件全量 156/156、安装器 6/6、三技能与插件结构校验、Python 编译、`diff-check` 全部通过；源码保持 `0.4.0`，本机已安装并核验 `0.4.0+codex.20260825103138` 包含本轮修复。交付报告已生成。

## 3. 调度与回退

- Wave 1 优先并行 T02（55+8 分钟）与 T03（40+5 分钟），预计串行 95 分钟、并行含协调 68 分钟，约节省 28.4%；T01 由协调者在空闲槽位或下一波执行。
- T04 在脚本契约稳定后执行；T05 作为独立验证者单独执行；T06 由协调者串行交付。
- Worker 不可用时由协调者接管，不改变已批准范围。
- 任一发现需改插件 ID、版本主线、无法兼容的状态破坏或需要破坏性操作，立即停止并修订计划。

## 4. 质量矩阵

- 类型/空值：新字段缺失、空、布尔伪装、未知枚举。
- 数值：`state_version` 负数、布尔、极大值与溢出；心跳上下界保持。
- 集合/身份：重复 task/owner/runtime ID、空范围、范围重叠和符号链接。
- 时间：审批与中断证据保持带时区 ISO-8601；时钟回拨不降低 `state_version`。
- 重试/原子性：重复 resume/release/compare，锁等待，崩溃替换，CAS 冲突重读。
- 错误表面：稳定非零退出码与结构化错误，不泄漏 traceback。
- 并发/恢复：活跃、阻塞、失联、已中断、过期版本和竞争写入。
- 迁移：按设计第 8 节逐行验证，未知状态隔离，重复迁移幂等。
- 性能：快照默认不输出全清单；锁有界等待，不无限阻塞。

## 5. 完成定义

- T01–T06 全部有终态与验收证据。
- 全部 P1 可复现条件和明确 P2 契约缺口已关闭，独立验证者通过。
- 历史 v0.3/v0.4 计划、完成 Worker、活跃/阻塞 Worker 和旧快照的映射有证据。
- 本机重装后的缓存版本包含修复，新建 Codex 任务可加载。
- 未发生未授权 commit、tag、push、部署或破坏性操作。

## 6. 确认门禁

本计划 revision 1 持久化后等待用户明确确认。确认授权上述路径内实现、测试、原生 Worker 委派和全部验收通过后的本机重装；不授权 commit、tag、push、发布、部署或破坏性操作。
