# Codex Project Workflow 插件

[English](README.md) | [简体中文](README.zh-CN.md)

Project Workflow 是一个为复杂软件项目设计的 Codex 确认门禁插件。它将方案制定与代码实施拆分到不同阶段，在仓库中持久化项目状态，并防止新生成的方案未经用户确认就继续修改代码。

## 为什么需要 Project Workflow

长周期工程任务经常把需求、架构、编码、测试和交付放在同一个连续回合里。即使技能写了“等待用户确认”，AI 仍可能把它理解为普通中间步骤，而不是真正的跨回合边界。

Project Workflow 将这个边界明确化：

1. 检查仓库并写入持久化设计与实施计划；
2. 结束当前回合，等待用户明确确认；
3. 校验确认记录与计划版本；
4. 执行任务、测试、评审并生成交付报告；
5. 重大变更导致原计划失效时，重新回到确认阶段。

## 技能组成

| 技能 | 职责 | 允许隐式触发 |
| --- | --- | --- |
| `project-workflow:index` | 独占工作流生命周期，每次只路由一个阶段 | 是 |
| `project-workflow:plan` | 创建或修改设计与实施计划，然后停止 | 否 |
| `project-workflow:execute` | 校验并执行已经确认的计划 | 否 |

只有入口技能可以隐式触发。规划和执行技能只能由插件入口路由或用户显式调用，从而减少与其他项目管理类技能发生触发冲突。

## 确认状态流转

```text
DRAFT
  -> AWAITING_CONFIRMATION
  -> APPROVED
  -> IN_PROGRESS
  -> COMPLETED

APPROVED / IN_PROGRESS
  -> AWAITING_CONFIRMATION  （发生重大变更）
```

插件内置的 `workflow_state.py` 会校验必填字段、计划版本、确认记录和合法状态迁移，仅依赖 Python 标准库。

## 环境要求

- 支持插件的 Codex Desktop 或 CLI
- Python 3，用于执行工作流状态脚本
- 通过 GitHub 安装或参与开发时需要 Git

## 从 GitHub 安装

将本仓库添加为 Codex marketplace，然后安装插件：

```bash
codex plugin marketplace add axing100/project-workflow
codex plugin add project-workflow@project-workflow-local
```

安装后请新建 Codex 任务，使新技能被加载。

## 从本地克隆或压缩包安装

```bash
git clone https://github.com/axing100/project-workflow.git
codex plugin marketplace add <project-workflow所在路径>
codex plugin add project-workflow@project-workflow-local
```

如果使用压缩包，请将其解压到稳定目录，再把该目录传给 `marketplace add`。

## 使用方式

可以使用类似下面的提示启动复杂项目：

```text
使用 Project Workflow 设计并实现这个跨模块迁移需求。
```

规划阶段会在仓库中生成设计和实施计划文档，然后结束当前回合。审阅文件后，在后续消息中明确确认对应计划：

```text
我确认刚才生成的实施计划，开始执行。
```

初始需求中的“直接做”“全部完成”“一口气执行”等措辞，不会预先确认一个尚未生成的计划。

## 工作流状态脚本

状态脚本位于 `plugins/project-workflow/scripts/workflow_state.py`。

```bash
python3 plugins/project-workflow/scripts/workflow_state.py init <plan.md> --plan-id <id>
python3 plugins/project-workflow/scripts/workflow_state.py approve <plan.md> --confirmation "<用户确认消息>"
python3 plugins/project-workflow/scripts/workflow_state.py check-execute <plan.md>
python3 plugins/project-workflow/scripts/workflow_state.py transition <plan.md> IN_PROGRESS
```

该脚本用于增强状态一致性，但它不是授权或安全边界，也无法通过密码学方式证明自然语言确认的真实性。

## 更新

刷新 marketplace 并重新安装插件：

```bash
codex plugin marketplace upgrade project-workflow-local
codex plugin add project-workflow@project-workflow-local
```

更新后请新建 Codex 任务。

## 卸载

```bash
codex plugin remove project-workflow
codex plugin marketplace remove project-workflow-local
```

只有在没有其他所需插件依赖该 marketplace 时，才移除 marketplace。

## 分享与参与开发

可以直接分享 GitHub 地址，也可以分发整个仓库的压缩包。`.agents/plugins/marketplace.json` 使用相对插件路径，因此克隆或解压后的副本仍然可以安装。

提交修改前请运行：

```bash
python3 -m unittest discover -s plugins/project-workflow/tests -v
python3 <skill-creator路径>/scripts/quick_validate.py plugins/project-workflow/skills/index
python3 <skill-creator路径>/scripts/quick_validate.py plugins/project-workflow/skills/plan
python3 <skill-creator路径>/scripts/quick_validate.py plugins/project-workflow/skills/execute
python3 <plugin-creator路径>/scripts/validate_plugin.py plugins/project-workflow
```

## 安全与限制

- 系统、开发者、仓库和用户显式指令仍遵循原有优先级。
- 其他专项技能可以在已确认范围内提供能力，但不得改变工作流阶段或跳过确认。
- 提交、推送、部署和破坏性操作权限单独记录，不能从计划确认中自动推断。
- 该插件无法阻止更高优先级指令或被人为修改的状态文件绕过其行为规则。

## 开源协议

本项目基于 [Apache License 2.0](LICENSE) 开源。
