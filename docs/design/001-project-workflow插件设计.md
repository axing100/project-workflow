# Project Workflow 插件设计

## 文档信息

- 状态：已确认，实施中
- 版本：1
- 日期：2026-08-20
- 目标目录：`<user-home>/IdeaProjects/project-workflow`
- 实施计划：[001-project-workflow插件实施计划](../plan/001-project-workflow插件实施计划.md)

## 一、项目概述

### 1.1 背景

现有 `project-planner-executor` 将规划、确认门禁和实施放在同一个技能中。实际使用时，模型可能把“等待用户确认”理解为同一任务中的中间步骤，从而在用户尚未确认方案时继续编码和交付。同时，该技能以独立个人技能存在，缺少插件命名空间、统一路由和可分发安装结构。

### 1.2 目标

创建可独立分发的 `project-workflow` Codex 插件，将项目工作流拆分为路由、规划、执行三个技能，并通过共享协议、持久化状态及机械校验强化确认门禁。

### 1.3 成功标准

- 插件以 `project-workflow` 命名空间暴露 `index`、`plan`、`execute` 三个技能。
- 普通复杂开发请求只由 `index` 入口路由；子技能不会因宽泛描述自行触发。
- `plan` 输出设计和计划后必须结束当前回合，不修改业务代码。
- `execute` 仅能执行已明确确认且版本匹配的计划。
- 插件清单、三个技能及状态检查脚本全部通过验证。
- 插件仓库可被其他用户克隆，并通过仓库内 marketplace 安装。
- 本机旧 `project-planner-executor` 在新插件验证成功后以可恢复方式停用，避免触发冲突。

## 二、范围

### 2.1 包含范围

- 独立 marketplace 仓库和插件清单。
- `project-workflow:index` 路由技能。
- `project-workflow:plan` 规划技能。
- `project-workflow:execute` 执行技能。
- 插件共享工作流协议、执行检查清单和多代理编排参考。
- 计划状态初始化、批准记录和执行前校验脚本。
- Python 标准库单元测试。
- 面向其他用户的安装、升级、卸载和分享说明。
- 本机 marketplace 添加、插件安装和发现验证。
- 旧技能的可恢复停用方案。

### 2.2 不包含范围

- 发布到 OpenAI 官方或第三方公共 marketplace。
- 创建 GitHub/GitLab 远程仓库、提交或推送代码。
- MCP Server、App、Hook 或外部服务集成。
- 修改当前 `fgpro-license-platform` 业务仓库。
- 对 Codex 系统级指令或用户显式指定的其他技能实现绝对屏蔽。

## 三、用户场景与功能需求

### P0：统一入口与路由

- 用户提出复杂、多步骤、跨模块或需要持久化计划的工程任务时，`index` 负责判断当前阶段。
- 初始需求路由至 `plan`；明确确认已有计划的后续消息路由至 `execute`。
- `index` 自身不生成完整方案、不修改业务代码，也不同时加载两个子技能。

### P0：规划确认门禁

- `plan` 只允许仓库读取、基线检查、设计文档和实施计划写入。
- 计划元数据必须包含工作流标识、计划 ID、版本和 `AWAITING_CONFIRMATION` 状态。
- 输出确认请求后立即结束当前回合。
- 初始请求中的“直接做完”“一口气完成”等表述不视为对尚未生成计划的确认。
- 用户要求调整时递增计划版本，并重新进入待确认状态。

### P0：执行门禁

- `execute` 开始前必须读取设计、计划及适用的 `AGENTS.md`。
- 只有当前用户消息明确确认指定计划，或计划已记录有效确认时，才能记录批准。
- 执行前脚本校验 `phase=APPROVED`、`revision=approved_revision`、确认时间和确认依据。
- 校验失败时停止，不允许自动将未确认计划改成已确认。
- 发生重大范围或架构变更时，将状态退回 `AWAITING_CONFIRMATION` 并结束当前回合。

### P0：可恢复执行

- 计划文档是阶段和任务状态的事实来源。
- 上下文压缩、新任务、交接或中断后，执行技能必须从磁盘重新读取状态。
- 任务使用 `[ ]`、`[~]`、`[x]`、`[!]` 记录执行状态和证据。

### P1：隔离与协作

- 工作流启动后，插件独占规划、确认、阶段转换和实施调度。
- 其他专项技能可以提供文档、浏览器、PDF、测试等能力，但不能越过确认门禁或改变阶段。
- 用户显式指定其他技能或更高优先级指令时，按上级规则执行并记录偏差。

### P1：分发与安装

- 仓库包含 marketplace 配置，插件源使用相对路径 `./plugins/project-workflow`。
- 其他用户克隆后可以执行 marketplace 添加和插件安装命令。
- 安装说明不得包含创建者机器的绝对路径。
- 插件不依赖网络服务或额外 Python 包。

## 四、非功能需求

### 4.1 兼容性

- 面向 Codex Desktop/CLI 当前插件清单格式。
- 状态脚本兼容 Mac 默认 Python 3，并尽量兼容其他具备 Python 3 的系统。
- 文件路径处理使用 `pathlib`，不硬编码用户目录。

### 4.2 安全性

- 不读取或写入凭据。
- 不自动提交、推送或执行破坏性 Git 操作。
- 停用旧技能采用移动到备份目录的可恢复方式，不删除原文件。
- 状态脚本只修改显式指定的计划文件。

### 4.3 可维护性

- 三个技能保持职责单一，公共规则只维护在共享协议中。
- 技能正文保持简洁，详细清单和状态格式放在 `references/`。
- 状态逻辑使用脚本和单元测试提供确定性验证。

### 4.4 可观测性

- 每次状态转换在计划文档记录时间、版本和确认依据。
- 执行计划记录校验命令、结果、变更路径和偏差。
- 交付报告记录安装、验证和未执行检查。

## 五、技术方案

### 5.1 仓库与插件结构

```text
project-workflow/
├── .agents/
│   └── plugins/
│       └── marketplace.json
├── docs/
│   ├── design/
│   ├── plan/
│   └── delivery/
├── plugins/
│   └── project-workflow/
│       ├── .codex-plugin/
│       │   └── plugin.json
│       ├── skills/
│       │   ├── index/
│       │   │   ├── SKILL.md
│       │   │   └── agents/openai.yaml
│       │   ├── plan/
│       │   │   ├── SKILL.md
│       │   │   └── agents/openai.yaml
│       │   └── execute/
│       │       ├── SKILL.md
│       │       └── agents/openai.yaml
│       ├── references/
│       │   ├── workflow-protocol.md
│       │   ├── execution-checklists.md
│       │   └── multi-agent-orchestration.md
│       ├── scripts/
│       │   └── workflow_state.py
│       └── tests/
│           └── test_workflow_state.py
├── README.md
└── LICENSE
```

插件名为 `project-workflow`，技能名为 `index`、`plan`、`execute`，安装后自然形成 `project-workflow:*` 命名空间。

### 5.2 技能触发设计

#### `index`

- `description` 覆盖复杂工程需求、制定计划、确认计划、恢复执行等入口语义。
- 正文只包含阶段识别和路由规则。
- 明确声明插件的生命周期所有权以及一次只加载一个子技能。

#### `plan`

- `description` 明确“仅由 `project-workflow:index` 路由或用户显式点名”。
- 正文不包含实施细节，避免规划后顺势编码。
- 末尾设置强制停止规则并要求结束当前回合。

#### `execute`

- `description` 明确只处理用户已确认的持久化计划。
- 首个写代码动作之前必须运行状态校验。
- 不负责从零制定计划，也不能自行批准未确认计划。

### 5.3 状态模型

计划文档使用固定 YAML frontmatter：

```yaml
workflow: project-workflow/v1
plan_id: example-001
revision: 1
phase: AWAITING_CONFIRMATION
approved_revision:
approved_at:
confirmation_record:
```

允许的主要状态：

```text
DRAFT
  → AWAITING_CONFIRMATION
  → APPROVED
  → IN_PROGRESS
  → COMPLETED

APPROVED / IN_PROGRESS
  → AWAITING_CONFIRMATION（重大变更）

任意执行状态
  → BLOCKED（真实阻塞）
```

`workflow_state.py` 提供：

- `inspect`：输出当前工作流状态。
- `init`：初始化或检查待确认元数据。
- `approve`：在明确用户确认后记录批准版本、时间和确认依据。
- `check-execute`：执行前只读校验。
- `transition`：限制合法阶段迁移。

脚本无法证明自然语言确认本身真实存在，因此技能协议仍必须要求 AI 只在后续用户消息明确确认时调用 `approve`。脚本负责防止缺字段、版本不一致和非法状态迁移，不宣称提供安全边界。

### 5.4 Marketplace 与分发

仓库 marketplace 名称暂定为 `project-workflow-local`，插件条目使用：

```json
{
  "name": "project-workflow",
  "source": {
    "source": "local",
    "path": "./plugins/project-workflow"
  },
  "policy": {
    "installation": "AVAILABLE",
    "authentication": "ON_INSTALL"
  },
  "category": "Productivity"
}
```

其他用户的安装流程为：

```bash
git clone <repository-url> project-workflow
codex plugin marketplace add <cloned-project-workflow-path>
codex plugin add project-workflow@project-workflow-local
```

若使用压缩包，解压后执行相同的 marketplace 添加和插件安装命令。仓库可初始化本地 Git，但本次不创建远程、不提交、不推送。

### 5.5 旧技能迁移

新插件通过验证和本机发现后，将：

```text
~/.codex/skills/project-planner-executor
```

移动到带日期的备份目录，例如：

```text
~/.codex/skills-disabled/project-planner-executor-20260820
```

该操作可通过移回原路径恢复。若安装或验证失败，不停用旧技能。

## 六、关键权衡

- 选择插件内三个独立技能，而不是单个技能引用两个参考文件，以获得更清晰的命名空间和触发边界。
- 保留入口技能而不让子技能宽泛自动触发，降低与其他项目管理技能的竞争。
- 使用轻量 Python 状态脚本增强确定性，但不把它描述为无法绕过的授权系统。
- 使用仓库内 marketplace 方便团队分发；代价是首次安装需要执行一次 `marketplace add`。
- 停用旧技能而非删除，兼顾冲突隔离和回滚能力。

## 七、假设与约束

- 插件作者名使用 `chenjiaxing`。
- 初始版本使用 `0.1.0`，许可证使用 MIT；如用户在实施前提出变更，以用户选择为准。
- 插件不包含作者邮箱、主页和远程仓库 URL，待实际发布地址确定后补充。
- 本次只使用单代理实施；当前运行规则不允许主动启动子代理做前向测试。
- 本机 Codex CLI 已提供 `plugin add/list/marketplace/remove` 命令。
- 目标目录当前不存在，当前业务仓库的未提交改动与本插件无关且不触碰。

## 八、验收与回滚

### 8.1 验收

- marketplace JSON 和 plugin JSON 通过语法及插件验证。
- 三个技能分别通过 skill 快速验证。
- 状态脚本单元测试覆盖正常批准、未确认、版本不一致、非法迁移和重大变更回退。
- 本机 marketplace 与插件安装成功，`codex plugin list` 能发现插件。
- README 中的安装命令不包含开发者绝对路径。
- 新插件确认可发现后，旧技能被移动到可恢复备份位置。

### 8.2 回滚

- 使用 `codex plugin remove project-workflow` 卸载插件。
- 移除本地 marketplace 配置时只操作本项目对应条目。
- 将旧技能备份目录移回 `~/.codex/skills/project-planner-executor`。
- 插件源目录保留，除非用户另行明确要求删除。
