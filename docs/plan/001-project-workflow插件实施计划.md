# Project Workflow 插件实施计划

## 文档信息

- 状态：已完成
- 工作流：`project-planner-executor/v1`
- 计划版本：1
- 日期：2026-08-20
- 设计文档：[001-project-workflow插件设计](../design/001-project-workflow插件设计.md)
- 目标目录：`<user-home>/IdeaProjects/project-workflow`
- 执行方式：单代理串行执行
- 提交授权：未授权
- 推送授权：未授权

## 一、目标与范围

### 目标

创建可共享的 `project-workflow` marketplace 仓库和插件，实现 `index`、`plan`、`execute` 三技能分工、跨回合确认门禁、持久化状态校验、本机安装验证及旧技能可恢复停用。

### 范围外

- 不修改 `<user-home>/IdeaProjects/fgpro-license-platform`。
- 不创建远程 Git 仓库，不提交，不推送。
- 不发布到公共 marketplace。
- 不添加 MCP、App、Hook 或网络依赖。

## 二、基线

- 目标目录：不存在。
- 初始 Git 分支：无；目标目录尚未初始化 Git。
- 初始工作树：无。
- 当前业务仓库：`uat` 分支且存在大量与本任务无关的用户改动；全部保留且不触碰。
- 旧技能：`<user-home>/.codex/skills/project-planner-executor` 存在。
- 本机个人 marketplace：`<user-home>/.agents/plugins/marketplace.json` 当前不存在。
- 本机插件源码目录：`<user-home>/plugins` 当前不存在。
- Codex CLI：`/Applications/ChatGPT.app/Contents/Resources/codex`，支持 `plugin add/list/marketplace/remove`。
- 基线测试：目标尚未创建，无可运行测试。
- 环境限制：目标目录和 Codex 用户配置不在当前沙箱写入范围内，实施时需要用户批准相应文件操作。

## 三、任务列表

### T01 创建独立 marketplace 仓库骨架

- 状态：[x]
- 目标：建立独立、可分发且不污染业务仓库的源码结构。
- 范围：
  - `<user-home>/IdeaProjects/project-workflow/.agents/plugins/marketplace.json`
  - `<user-home>/IdeaProjects/project-workflow/plugins/project-workflow/.codex-plugin/plugin.json`
  - `<user-home>/IdeaProjects/project-workflow/LICENSE`
- 范围外：技能正文、状态脚本、本机安装。
- 前置条件：用户确认本计划；获得目标目录写入批准。
- 风险：manifest 字段或 marketplace 相对路径不符合 Codex 规范。
- 实施：使用 `plugin-creator` 提供的脚手架创建 repo/team marketplace 骨架，再按设计完善清单；初始化本地 Git `main` 分支但不提交。
- 验收标准：
  - [x] marketplace 名称为 `project-workflow-local`。
  - [x] 插件名、外层目录名和 manifest 名均为 `project-workflow`。
  - [x] 插件版本为严格 semver `0.1.0`。
  - [x] marketplace 源路径为 `./plugins/project-workflow`。
- 验证：
  - [x] `python3 -m json.tool .agents/plugins/marketplace.json` — 成功。
  - [x] `python3 -m json.tool plugins/project-workflow/.codex-plugin/plugin.json` — 成功。
- 证据：脚手架创建成功；Git 已初始化为未提交的 `main` 分支；两个 JSON 均通过解析。

### T02 实现工作流入口技能

- 状态：[x]
- 目标：提供唯一入口，识别工作流阶段并一次只路由一个子技能。
- 范围：
  - `plugins/project-workflow/skills/index/SKILL.md`
  - `plugins/project-workflow/skills/index/agents/openai.yaml`
- 范围外：规划和执行细节。
- 前置条件：T01。
- 风险：入口描述过窄导致不触发，或过宽导致普通简单修改被接管。
- 验收标准：
  - [x] 覆盖复杂工程、规划、确认、恢复执行场景。
  - [x] 明确简单变更例外和用户显式跳过规划的处理边界。
  - [x] 明确一次只加载 `plan` 或 `execute` 之一。
  - [x] 自身不修改业务代码。
- 验证：
  - [x] `python3 <user-home>/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/project-workflow/skills/index` — 通过。
- 证据：`index` 技能验证通过；其 `allow_implicit_invocation` 为 `true`，且只负责路由。

### T03 实现规划技能与共享协议

- 状态：[x]
- 目标：将方案输出和用户确认形成必须结束当前回合的硬门禁。
- 范围：
  - `plugins/project-workflow/skills/plan/SKILL.md`
  - `plugins/project-workflow/skills/plan/agents/openai.yaml`
  - `plugins/project-workflow/references/workflow-protocol.md`
- 范围外：业务代码实施逻辑。
- 前置条件：T02。
- 风险：停止语义不够明确，或把初始请求中的“直接完成”误判为确认。
- 验收标准：
  - [x] `plan` 只允许仓库分析、设计和计划记录。
  - [x] 计划状态必须写为 `AWAITING_CONFIRMATION`。
  - [x] 明确初始请求不能预先确认尚未生成的计划。
  - [x] 输出确认请求后明确要求立即结束当前回合。
  - [x] 共享协议定义插件所有权、状态转换和其他技能协作边界。
- 验证：
  - [x] `python3 <user-home>/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/project-workflow/skills/plan` — 通过。
  - [x] `rg -n "AWAITING_CONFIRMATION|结束当前回合|不得修改.*代码|初始请求" plugins/project-workflow/skills/plan plugins/project-workflow/references/workflow-protocol.md` — 关键门禁均存在。
- 证据：技能验证与门禁关键字检查通过；`plan` 设置 `allow_implicit_invocation: false`。

### T04 实现执行技能和执行清单

- 状态：[x]
- 目标：只执行已确认计划，并保留可恢复任务状态、测试和交付规则。
- 范围：
  - `plugins/project-workflow/skills/execute/SKILL.md`
  - `plugins/project-workflow/skills/execute/agents/openai.yaml`
  - `plugins/project-workflow/references/execution-checklists.md`
  - `plugins/project-workflow/references/multi-agent-orchestration.md`
- 范围外：状态脚本实现。
- 前置条件：T03。
- 风险：执行技能自行批准计划，或重大变更后继续执行。
- 验收标准：
  - [x] 首次代码写入前必须运行 `check-execute`。
  - [x] 禁止自动批准未确认计划。
  - [x] 重大范围或架构变化必须退回待确认并结束回合。
  - [x] 任务状态、测试、Git 授权和交付报告规则完整。
  - [x] 多代理只在用户或运行时明确允许时启用。
- 验证：
  - [x] `python3 <user-home>/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/project-workflow/skills/execute` — 通过。
  - [x] `rg -n "check-execute|不得.*批准|重大.*变更|AWAITING_CONFIRMATION" plugins/project-workflow/skills/execute plugins/project-workflow/references` — 关键规则均存在。
- 证据：技能验证与执行门禁检查通过；`execute` 设置 `allow_implicit_invocation: false`。

### T05 实现状态检查脚本及单元测试

- 状态：[x]
- 目标：机械校验状态字段、批准版本和合法阶段迁移，减少仅依赖自然语言指令的风险。
- 范围：
  - `plugins/project-workflow/scripts/workflow_state.py`
  - `plugins/project-workflow/tests/test_workflow_state.py`
- 范围外：证明自然语言确认真实性、实现加密或不可绕过授权。
- 前置条件：T03、T04。
- 风险：脚本意外覆盖计划正文，或对合法 Markdown 格式兼容不足。
- 验收标准：
  - [x] 仅使用 Python 标准库。
  - [x] 支持 `inspect`、`init`、`approve`、`check-execute`、`transition`。
  - [x] 保留计划正文，只修改受控 frontmatter 字段。
  - [x] 拒绝未确认、批准版本不一致和非法迁移。
  - [x] 单元测试覆盖成功与失败路径。
- 验证：
  - [x] `python3 -m unittest discover -s plugins/project-workflow/tests -v` — 7 项全部通过。
  - [x] `python3 plugins/project-workflow/scripts/workflow_state.py --help` — 成功。
- 证据：7/7 单元测试通过，覆盖批准、未批准、版本不一致、非法迁移、重确认和完成流程。

### T06 完善分发文档并执行静态验证

- 状态：[x]
- 目标：让其他用户可通过 Git 或压缩包安装，并验证插件归档内容自洽。
- 范围：
  - `README.md`
  - 前述 manifest、技能、参考和脚本的必要修正。
- 范围外：创建远程仓库、提交、推送、公共发布。
- 前置条件：T01-T05。
- 风险：安装说明绑定开发者绝对路径，或遗漏新任务加载要求。
- 验收标准：
  - [x] README 包含克隆/解压、marketplace 添加、插件安装、更新、卸载和回滚说明。
  - [x] 面向他人的命令使用占位路径，不包含 `<user-home>`。
  - [x] 插件 validator 和三个 skill validator 全部通过。
  - [x] 未包含 TODO 占位符或凭据。
- 验证：
  - [x] `python3 <user-home>/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/project-workflow` — 通过。
  - [x] `python3 <user-home>/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/project-workflow/skills/index` — 通过。
  - [x] `python3 <user-home>/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/project-workflow/skills/plan` — 通过。
  - [x] `python3 <user-home>/.codex/skills/.system/skill-creator/scripts/quick_validate.py plugins/project-workflow/skills/execute` — 通过。
  - [x] `! rg -n "TODO|<user-home>|BEGIN .*PRIVATE KEY|api[_-]?key" README.md plugins/project-workflow` — 无命中。
- 证据：插件 validator、三个技能 validator、敏感路径/占位符检查全部通过。

### T07 本机安装验证并可恢复停用旧技能

- 状态：[x]
- 目标：确认 Codex 能发现新插件，并消除旧技能的触发冲突。
- 范围：
  - 本机 Codex marketplace/插件配置。
  - `<user-home>/.codex/skills/project-planner-executor`
  - `<user-home>/.codex/skills-disabled/project-planner-executor-20260820`
- 范围外：删除旧技能、修改其他插件或技能。
- 前置条件：T06 全部验证通过；获得用户目录写入批准。
- 风险：本机配置变更失败，或旧技能停用后新插件尚未加载。
- 验收标准：
  - [x] 添加 `<user-home>/IdeaProjects/project-workflow` marketplace。
  - [x] 安装 `project-workflow@project-workflow-local`。
  - [x] `codex plugin list` 能识别 marketplace 和插件。
  - [x] 仅在新插件发现成功后移动旧技能到备份目录。
  - [x] 原旧技能文件完整保留，可按文档恢复。
- 验证：
  - [x] `codex plugin marketplace list` — 包含 `project-workflow-local`。
  - [x] `codex plugin list` — 插件 `0.1.0` 状态为 `installed, enabled`。
  - [x] `test ! -e <user-home>/.codex/skills/project-planner-executor` — 旧技能不再位于发现路径。
  - [x] `test -f <user-home>/.codex/skills-disabled/project-planner-executor-20260820/SKILL.md` — 备份存在。
- 证据：marketplace 和插件安装成功；缓存目录包含三个技能；旧技能在新插件发现成功后移动到日期备份目录。

### T08 回归、评审与交付

- 状态：[x]
- 目标：完成全量验证、最终审查和交付记录。
- 范围：
  - `docs/plan/001-project-workflow插件实施计划.md`
  - `docs/delivery/001-project-workflow插件交付报告.md`
- 范围外：提交和推送。
- 前置条件：T01-T07。
- 风险：文档状态与实际安装、验证结果不一致。
- 验收标准：
  - [x] 所有任务有终态且无未解释的 `[~]`。
  - [x] 重跑单元测试、skill validator 和 plugin validator。
  - [x] 审查触发边界、确认门禁、状态脚本、分发命令和安全性。
  - [x] 交付报告包含安装、回滚、验证证据和建议提交信息。
- 验证：
  - [x] `python3 -m unittest discover -s plugins/project-workflow/tests -v` — 7 项全部通过。
  - [x] `python3 <user-home>/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/project-workflow` — 通过。
  - [x] 三个 `quick_validate.py` 命令 — 全部通过。
  - [x] `git status --short --branch` — `main` 无提交，所有交付文件未跟踪；无提交和推送。
- 证据：最终回归、插件发现、尾随空白、占位符和敏感文本检查均通过；交付报告已创建。

## 四、测试策略

- 单元测试：验证 frontmatter 解析、状态初始化、批准、版本一致性、迁移合法性及正文保留。
- 静态验证：验证 JSON、插件清单、三个技能 frontmatter、路径和占位符。
- 集成验证：通过 Codex CLI 添加 marketplace、安装插件并检查列表。
- 行为前向测试：当前运行规则不允许主动启动子代理；安装后建议在新的 Codex 任务中分别验证“初始复杂需求必须停在确认”和“明确确认后才执行”。本次不伪造该结果。
- 回归：最终重跑全部单元测试与 validator。

## 五、质量检查清单

### 计划就绪

- [x] 目标、范围、范围外、假设和成功标准明确。
- [x] 已检查现有技能、插件规范、Codex CLI、目标目录和 Git 基线。
- [x] 已考虑安全、兼容性、可维护性、分发和回滚。
- [x] 任务按小范围拆分，前置关系和预计写入路径明确。
- [x] 每个任务包含可观察验收标准和验证命令。
- [x] 已区分目标目录尚不存在、当前业务仓库用户改动及环境限制。
- [x] 提交与推送均记录为未授权。
- [x] 设计和计划已交叉链接，用户确认已记录。

### 每任务开发

- [x] 执行前重读确认后的设计、计划和适用规则。
- [x] 确认前置条件和基线，不覆盖用户改动。
- [x] 变更保持在任务范围内，必要偏差先记录。
- [x] 处理输入、错误、边界、路径和状态一致性。
- [x] 评审 diff 中的意外改动、凭据、占位符和生成物。
- [x] 未获授权时不提交、不推送。

### 每任务测试与验收

- [x] 风险对应测试已添加并通过。
- [x] 先运行最窄检查，再运行插件级验证。
- [x] 失败经过诊断、修复和重跑。
- [x] 命令、结果、跳过项和原因记录到任务证据。

### 完成定义

- [x] 验收标准满足并有证据。
- [x] 单元测试、技能验证和插件验证通过。
- [x] 无已知范围内正确性、安全、兼容或分发缺陷。
- [x] 安装、更新、卸载和回滚说明完整。
- [x] 设计、计划、交付报告、Git 和本机安装状态一致。

## 六、确认记录

- 方案确认：用户明确回复“开始执行”。
- 确认时间：2026-08-20T11:12:23+08:00。
- 允许提交：否。
- 允许推送：否。
