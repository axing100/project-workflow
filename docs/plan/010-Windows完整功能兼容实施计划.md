---
workflow: "project-workflow/v1"
plan_id: "windows-full-support"
revision: 1
phase: "IN_PROGRESS"
approved_revision: 1
approved_at: "2026-09-04T09:38:01+00:00"
confirmation_record: "执行"
workflow_profile: "FULL"
conversation_title: "Windows 完整功能兼容修复"
progress_heartbeat_minutes: 5
vcs_mode: "AUTO"
resolved_vcs_mode: "GIT"
rollback_required: "true"
rollback_strategy: "以 e35e7f9 为代码基线按差异逐文件恢复；全部迁移测试使用临时目录与预先保存副本，生产状态不自动迁移"
rollback_evidence: "从最新 origin/main e35e7f9 创建新分支且初始工作区干净；Git 对象可读；旧版测试夹具和迁移前副本可用于回归"
rollback_verification: "VERIFIED"
execution_mode: "AUTO_MULTI_AGENT"
max_workers: 2
agent_topology: "SHARED_WORKSPACE"
progress_reporting: "COMPACT"
parallelism_policy: "BENEFIT_GATED"
minimum_parallel_savings_percent: 20
orchestration_state: ".codex/project-workflow/windows-full-support/orchestration.json"
commit_authorized: "true"
push_authorized: "true"
policy_contract: "v0.5"
---

# Windows 完整功能兼容实施计划

<!-- project-workflow:summary:start -->
> **任务进度** · 实现 5/6 · 验收 0/6
<!-- project-workflow:summary:end -->

设计：[010-Windows完整功能兼容设计](../design/010-Windows完整功能兼容设计.md)

## 范围与验收原则

完整支持原生 Windows，不以 WSL、关闭文件锁/路径保护、跳过 NONE 或多智能体功能作为修复。跨平台安全语义、真实 Windows 测试与可恢复性都是交付要求。目标补丁版本 0.5.1，未经真实验证不能标记全部验收通过。

使用新分支 feature/010-windows-support，基线 e35e7f9；原分支禁用。Windows 代码和安装入口可分离并行：初步估算 80/60 分钟、协调各 8 分钟，140 分钟串行对比 96 分钟并行约节约 31%；实际开始前重新评估。工作时间是调度估算，不是交付承诺。

## T01 跨平台安全 I/O 后端

<!-- project-workflow:task-status T01:start -->
- 实现状态：✅ 已完成
- 验收状态：🟡 部分通过
- 证据：SecureDirectory及Win32后端、LockFileEx、持句柄原子替换、防reparse与安全参数已实现；15项本机测试11通过4Windows待验；Mac局部回归通过；原生Windows文件句柄锁和安全测试待CI
<!-- project-workflow:task-status T01:end -->

- Depends-On: none
- Write-Scope: plugins/project-workflow/scripts/platform_io.py, plugins/project-workflow/scripts/windows_io.py, plugins/project-workflow/tests/test_platform_io.py
- Agent-Eligible: true
- Estimated-Minutes: 80
- Coordination-Minutes: 8
- Critical-Path: true
- Parallel-Group: platform-foundation
- 目标：统一可信目录、文件锁、原子替换和安全访问能力，提供真实 Windows 后端并保留 POSIX 保证。
- 范围外：现有业务脚本接入、README 和安装器。
- 风险：句柄泄漏、锁身份分裂、目录替换竞态、重解析点逃逸、持久性误报。
- 验收：
  - [ ] Windows 不导入 Unix 模块；所有后端能力有明确接口和错误语义。
  - [ ] 原生跨进程互斥、超时、崩溃释放、异常释放和 CAS 组合测试通过。
  - [ ] 防 junction/链接/目录替换与非法路径，不写出工作区。
  - [ ] 文件占用有限重试、权限错误稳定拒绝，原子写入异常不损坏已有数据。
- Validation (DISCOVERY): python -m unittest discover -s plugins/project-workflow/tests -p test_platform_io.py -v
- Evidence: 待执行；必须分别记录实际平台结果。

## T02 Windows 安装与命令入口

<!-- project-workflow:task-status T02:start -->
- 实现状态：✅ 已完成
- 验收状态：🟡 部分通过
- 证据：Windows exe与官方npm入口安全解析、Unicode参数、失败恢复实现；协调者复核14项安装器测试通过；macOS 14项安装器测试通过，包含真实隔离子进程夹具；Windows及真实Codex隔离安装待CI
<!-- project-workflow:task-status T02:end -->

- Depends-On: none
- Write-Scope: scripts/install_local_plugin.py, tests/test_install_local_plugin.py
- Agent-Eligible: true
- Estimated-Minutes: 60
- Coordination-Minutes: 8
- Critical-Path: false
- Parallel-Group: platform-foundation
- 目标：原生 Windows 可安装和更新，支持可信可执行入口、路径和编码；失败后恢复原 marketplace。
- 范围外：真实个人插件重装、发布清单、核心状态代码。
- 风险：Windows 包装器执行错误、参数注入、临时文件占用、恢复丢失配置。
- 验收：
  - [ ] 原生入口及受支持的包装器解析正确；空格、中文和 shell 元字符参数测试通过。
  - [ ] 安装成功/失败/恢复失败均有准确结果且不污染源码正式版本。
  - [ ] 真实 Windows 隔离配置安装 smoke 通过；mock 不代替实际安装证据。
- Validation (DISCOVERY): python -m unittest discover -s tests -v
- Evidence: 改造前安装器 8 项通过；Windows 待验证。

## T03 核心工作流与快照接入

<!-- project-workflow:task-status T03:start -->
- 实现状态：✅ 已完成
- 验收状态：🟡 部分通过
- 证据：生命周期、任务、编排、Doctor与快照已接入；Mac回归发现的临时目录和错误码问题已修复，复测进行中；快照25项通过；全量复测和Windows原生验证待完成
<!-- project-workflow:task-status T03:end -->

- Depends-On: T01
- Write-Scope: plugins/project-workflow/scripts/workflow_state.py, plugins/project-workflow/scripts/orchestration_state.py, plugins/project-workflow/scripts/task_state.py, plugins/project-workflow/scripts/filesystem_snapshot.py, plugins/project-workflow/scripts/project_workflow_doctor.py, plugins/project-workflow/tests/test_workflow_state.py, plugins/project-workflow/tests/test_orchestration_state.py, plugins/project-workflow/tests/test_task_state.py, plugins/project-workflow/tests/test_filesystem_snapshot.py, plugins/project-workflow/tests/test_project_workflow_doctor.py
- Agent-Eligible: false
- 目标：协调者统一接入跨平台层并保持审批、证据、状态版本及无 Git 门禁；包括异常清理和迁移回滚。
- 范围外：独立安全验收文件及 CI 配置。
- 风险：部分接入导致隐藏 Unix 调用；破坏旧计划；跨系统摘要误用；输出编码造成半成功。
- 验收：
  - [ ] GIT/NONE 生命周期与多智能体编排在 Windows 可运行，不存在平台禁用分支。
  - [ ] 保留中文/英语渲染、CAS、审批、最终任务及运行绑定门禁。
  - [ ] 设计迁移矩阵逐项有测试，损坏状态不覆盖，旧基线不静默重建。
  - [ ] Doctor 先检测实际能力，再给稳定错误；无导入 traceback。
  - [ ] 不改变公开接口或 schema；若确有必要先修订并确认设计。
- Validation (DISCOVERY): python -m unittest discover -s plugins/project-workflow/tests -p test_*state.py -v
- Validation (DISCOVERY): python -m unittest discover -s plugins/project-workflow/tests -p test_*snapshot.py -v
- Validation (DISCOVERY): python -m unittest discover -s plugins/project-workflow/tests -p test_project_workflow_doctor.py -v
- Evidence: 待执行。

## T04 原生跨平台测试与 CI

<!-- project-workflow:task-status T04:start -->
- 实现状态：✅ 已完成
- 验收状态：🟡 部分通过
- 证据：已实现五组原生CI、中文/长路径/非UTF8/ACL测试及固定官方CLI隔离安装更新测试；平台缺陷继续由协调者修复，验收不标通过；Mac 264项257通过7跳过；Linux两组及Mac CI通过；Windows真实安装3.12通过，核心安全兼容仍复测中
<!-- project-workflow:task-status T04:end -->

- Depends-On: T02, T03
- Write-Scope: .github/workflows/cross-platform.yml, scripts/check_platform.py, tests/test_install_local_plugin.py, plugins/project-workflow/tests/test_release_closure_contract.py, plugins/project-workflow/tests/test_project_workflow_doctor.py, plugins/project-workflow/tests/test_orchestration_state.py, plugins/project-workflow/tests/test_recovery_contract.py, plugins/project-workflow/tests/test_workflow_state.py, plugins/project-workflow/tests/test_filesystem_race_contract.py, plugins/project-workflow/tests/test_final_gate_contract.py, plugins/project-workflow/tests/test_vcs_contract.py, plugins/project-workflow/tests/test_safety_contract.py, plugins/project-workflow/tests/test_filesystem_snapshot.py, plugins/project-workflow/tests/test_documented_commands.py, plugins/project-workflow/tests/test_workflow_contract.py, plugins/project-workflow/tests/test_state_ux_contract.py, plugins/project-workflow/tests/test_task_state.py, plugins/project-workflow/tests/test_cross_platform.py, tests/test_cross_platform_install.py
- Agent-Eligible: false
- 目标：协调者整理可移植夹具，新增 Windows/macOS/Linux CI、真实原生流程 smoke 和性能基线。
- 范围外：T05 独立验收文件与报告；不修改生产代码掩盖失败。
- 风险：跳过测试制造假通过；Windows server runner 与桌面环境混淆；安装测试污染个人配置。
- 验收：
  - [ ] 全量套件可在 Windows 启动和执行，无核心模块整组跳过。
  - [ ] 所有核心流程均有原生 Windows 证据，至少覆盖 CPython 3.9 兼容基线与 3.12。
  - [ ] 中文/空格/反斜杠/长路径、文件占用、ACL、junction、崩溃、重试和 NONE 测试通过。
  - [ ] 原生安装 smoke 和宿主流程证据分开记录；客户 Windows 10/11 结果与 CI 系统版本准确列明。
  - [ ] 记录前后耗时；无无界等待/扫描，未运行的 CI 不称为通过。
- Validation (DISCOVERY): python -m unittest discover -s plugins/project-workflow/tests -v
- Validation (DISCOVERY): python -m unittest discover -s tests -v
- Validation (DISCOVERY): python -m compileall -q plugins/project-workflow scripts tests
- Evidence: 需实际 Windows 执行器。当前仅 Mac 可用，未发现本机常用 Windows VM/Wine/PowerShell 入口；允许继续实现但未有真实结果时不能结束验收。

## T05 独立契约与安全验收

<!-- project-workflow:task-status T05:start -->
- 实现状态：✅ 已完成
- 验收状态：🟡 部分通过
- 证据：独立测试与报告已完成，24项Mac22通过2Windows待验；失败验收门禁和迁移状态丢失边界已独立复验通过；Mac独立契约通过；原生Windows全量与桌面宿主仍待验，不标产品验收完成
<!-- project-workflow:task-status T05:end -->

- Depends-On: T04
- Write-Scope: plugins/project-workflow/tests/test_windows_contract.py, docs/verification/010-Windows兼容独立验收.md
- Agent-Eligible: true
- Estimated-Minutes: 45
- Coordination-Minutes: 5
- Critical-Path: true
- Role: CONTRACT_VERIFIER
- Independent-Verification: true
- 目标：独立智能体只读取原始用户要求、公开 CLI 契约和验收标准，构造黑盒功能与对抗验证。
- 范围外：禁止修改实现和计划，禁止接受实现者自评作为证据。
- 风险：无 Windows 环境却宣称验证通过、接受只可导入而核心不可用的补丁。
- 验收：
  - [ ] 未授权开始/失败验收/失配版本/伪造 Worker 均不能绕过门禁。
  - [ ] Windows 原生路径替换、锁竞争及失败恢复不损坏计划和状态。
  - [ ] 功能矩阵无 Windows 特供删减；发现问题交回实现者修复并复测。
- Validation (DISCOVERY): python -m unittest discover -s plugins/project-workflow/tests -p test_windows_contract.py -v
- Evidence: 待独立验证，不能由实现者自证代替；原生能力不可用时如实记录阻塞。

## T06 文档、版本与交付

<!-- project-workflow:task-status T06:start -->
- 实现状态：🔵 进行中
- 验收状态：⚪ 未开始
<!-- project-workflow:task-status T06:end -->

- Depends-On: T05
- Write-Scope: README.md, README.zh-CN.md, plugins/project-workflow/skills, plugins/project-workflow/references, plugins/project-workflow/.codex-plugin/plugin.json, docs/design/010-Windows完整功能兼容设计.md, docs/plan/010-Windows完整功能兼容实施计划.md, docs/delivery/010-Windows完整功能兼容交付报告.md
- Agent-Eligible: false
- 目标：协调者更新双平台命令、受支持环境、排错、安全与恢复说明，只有全部证据满足后收口。
- 范围外：提交/推送/打 tag/发布/本机重装需独立授权，不延用上次权限。
- 风险：文档承诺超过真实证据、计划实现完成却误标验收通过。
- 验收：
  - [ ] 中英 README、技能示例与 CLI 一致，Windows 命令不强制 python3。
  - [ ] 技能、插件结构、全量回归、Doctor、差异检查通过。
  - [ ] 交付报告列出每个 OS/Python/文件系统/宿主环境与真实结果、跳过项和限制。
  - [ ] Windows 真实完整功能验证不足时保持验收未通过，不发布“全平台可用”结论。
- Validation (EXACT): git diff --check
- Validation (DISCOVERY): python -m unittest discover -s plugins/project-workflow/tests -v
- Evidence: 待最终验收。

## 安全、恢复和执行约束

- 所有状态枚举迁移按设计矩阵验证；不新增租约协议，现有运行身份恢复保留原契约。
- 边界矩阵：类型/空值、巨大 revision、重复身份、未知依赖、时间回拨、重试/崩溃、错误面、并发及权限均适用。业务计费/数据库迁移 N/A：本次无此类功能。
- 生产代码安全层由 T01 唯一写入，T03 必须在其完成后接入；T04/T05 不并发写同一测试树。
- 计划和交付由协调者维护；最多两个原生 Worker；无可用槽位时实现可串行，独立验收缺失不能冒充通过。
- 计划文档由工具渲染状态，验收复选框只表示验收条目，不能当作内部状态真值。
- Git diff 是变更证据；保留 e35e7f9 和测试输入副本作为恢复来源。不得 reset、覆盖客户状态或自动清除未知锁。
- 待确认计划授权范围只包括上述实现/测试与原生智能体委派，不包含远端上传。Windows CI 需要时另行取得将本次源码/测试/文档推送到 https://github.com/axing100/project-workflow.git 的授权，不自动合并或发布。

## 检查记录

- 2026-09-05：用户完成 workflow OAuth 授权，专用分支推送成功。首轮 CI 33892983272 的 Linux 3.9/3.12、macOS 3.12 通过；Windows 3.12 插件测试失败，安装器/编译/Doctor通过。协调者接管 T01/T03 已实现代码的原生缺陷修复，未绕过校验；T04继续进行。

- 2026-09-04：修复后最终 Mac/CPython 3.9.6 全量 260 项：255 通过、5 跳过，52.010 秒；compileall 通过。跳过项包含 4 项原生 Windows 后端测试及原有平台条件项，不能计为 Windows 通过。此前偶发 ENOENT 在编排专项、5 次并发 CAS 和最终全量中未复现，未据此声称问题已根治。

- 2026-09-04：本地提交 9e6642b 已保存源码、测试和 CI 配置。向 feature/010-windows-support 推送被 GitHub 拒绝：当前 OAuth 凭据仅含 gist/read:org/repo，缺少 workflow scope，无法创建 .github/workflows/cross-platform.yml；远端分支未创建，Windows CI 未运行。需要用户通过 gh auth refresh -h github.com -s workflow 完成授权；不删除 CI 配置绕过权限，也不宣称 Windows 验收通过。
- 2026-09-04：协调者追加快照集成委派在实际修改前撤回，T03 集成继续由协调者完成。快照专项 25 项、编排专项 50 项、安装器 14 项、重复并发 CAS 5 项本机通过；全量过程中一次锁创建 ENOENT 尚未稳定复现，继续保留待调查事项。

- 2026-09-04 执行授权：用户在明确请求确认本计划，并允许将本次源码、测试、文档提交/推送至 https://github.com/axing100/project-workflow 运行 Windows CI 后，回复“执行”。提交与推送仅限 feature/010-windows-support 的实现与 CI 修复；不合并、不打 tag、不发布、不重装个人插件。

- 2026-09-04：Doctor 在实际授权环境下通过；初始沙箱只读目录诊断为环境限制，未修改插件规避权限。
- 2026-09-04：最新 main e35e7f9，新分支创建前工作区干净，未发现本仓库附加 AGENTS.md。
- 2026-09-04：安装器基线 8 项通过；插件全量共 245 项，244 项通过、1 项预期跳过，用时 52.981 秒。仅为 macOS 基线，不代表 Windows 验收。
