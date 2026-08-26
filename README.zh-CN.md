# Codex Project Workflow 插件

[English](README.md) | [简体中文](README.zh-CN.md)

Project Workflow 是一个面向复杂软件工程任务的 Codex 审批门禁工作流。它先形成可审阅的设计与实施计划，等待用户明确确认，再根据任务风险和并行收益选择协调者执行或启动 Codex 原生子智能体，并持续记录验证、恢复和交付证据。

它支持 Git 和无 Git 仓库；普通小改动、格式化和简单 CRUD 通常不需要使用本插件。

## 为什么需要 Project Workflow

长周期工程任务经常把需求、架构、编码、测试和交付放在同一个连续回合里。即使技能写了“等待用户确认”，AI 仍可能把它理解为普通中间步骤，而不是真正的跨回合边界。

Project Workflow 将这个边界明确化：

1. 检查仓库并写入持久化设计与实施计划；
2. 结束当前回合，等待用户明确确认；
3. 校验确认记录与计划版本；
4. 按批准的模式串行执行，或主动创建、调度和验收 Codex 原生子智能体；
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

## 工作流分级

每份新计划都会记录以下一种级别。所有级别保留相同的审批边界：规划必须在实施前停止，只有用户确认当前 revision 后才能开始执行。

| 级别 | 适用场景 | 默认执行与验收 |
| --- | --- | --- |
| `LIGHT` | 用户明确要求使用工作流，但改动局部且风险较低 | 可合并设计与计划；默认由协调者执行；验证主路径、适用的无效输入和受影响回归 |
| `STANDARD` | 多模块或可独立验证，且不涉及迁移、安全、兼容性或数据丢失风险 | 独立设计与计划；覆盖适用边界；仅在并行收益明确时启用原生 Worker |
| `FULL` | 架构、持久化状态迁移、兼容性、安全、隐私、支付、数据丢失、分阶段发布或长期协调任务 | 包含 `STANDARD` 的要求，并增加对抗性恢复、回滚证据、隔离的契约验证者；持久化状态演进时还需迁移状态矩阵 |

多个级别都适用时选择更严格的一档。未声明 `workflow_profile` 的历史计划仍然有效，并按 `FULL` 解释，升级不会悄悄降低原有验收强度。

## 无 Git 运行

Git 不是运行 Project Workflow 的必需条件。每份新计划都会记录请求模式和解析后的版本控制模式：

| 模式 | 行为 |
| --- | --- |
| `AUTO` | Git 可用且项目属于有效工作树时使用 `GIT`，否则安静地解析为 `NONE` |
| `GIT` | 明确要求 Git 和有效工作树；任一能力缺失时 Doctor 阻断 |
| `NONE` | 即使项目位于 Git 仓库内也不执行任何 Git 命令 |

解析结果会在请求确认前持久化，并在执行、恢复和交付时重新校验。解析结果发生变化属于环境漂移，必须先恢复环境，或修订计划并重新确认，不能静默切换证据模型。

`NONE` 会创建内部文件系统基线，通过相对路径、文件大小、权限模式和 SHA-256 稳定报告新增、修改和删除。基于目录描述符的读写会拒绝符号链接竞态，以及 FIFO、socket、设备等无法安全表示的条目；目录权限变化也会进入证据。它不保存文件正文，也不会把清单描述为备份。`STANDARD` 交付必须披露无法提供 Git 级回滚；`FULL` 只有在 `rollback_strategy` 和 `rollback_evidence` 均非空且 `rollback_verification: "VERIFIED"` 时，才认为存在已验证的等价回滚来源。数据迁移、安全整改和潜在数据丢失任务没有可验证回滚能力时也会阻断。

多智能体 `NONE` 只使用共享工作区和互不重叠的字面量写入范围。禁止创建分支或 worktree，也禁止 commit、tag、push 和其他所有 Git 操作；需要 worktree 隔离的任务会自动串行执行。

## 执行模式与原生子智能体

- `SINGLE_AGENT`：协调者串行执行，适用于任务少、写入范围重叠或协调收益不高的情况。
- `AUTO_MULTI_AGENT`：收益门槛驱动的多智能体模式；只有安全且互不冲突的任务在扣除协调成本后预计至少缩短 20% 关键路径时，才主动创建 Codex 原生子智能体。
- `MANUAL_MULTI_AGENT`：仅在用户明确指定分工或拓扑时使用。

规划会记录任务 DAG、字面量写入范围、估时、协调成本、关键路径、Worker 上限和降级策略。新的自动多智能体计划默认最多使用两个原生 Worker。隔离的契约验证者是唯一可在只有一个 Worker 任务就绪时启动的例外，因为其收益来自独立质量审查，而不是缩短耗时。多智能体模式使用 `.codex/project-workflow/<plan-id>/orchestration.json` 保存插件内部恢复状态；它不是需要用户阅读或编辑的计划文档。用户确认计划后，即授权计划范围内的原生子智能体委派，无需逐个任务重复确认；提交、推送、部署、破坏性操作等权限仍需单独授权。

子智能体由当前 Codex 任务的原生协作能力创建，因此可在软件的智能体 UI 中展示。智能体小组件与图标由 Codex 原生界面渲染；插件只提供任务名称和提示词，不引用或配置图标图片。插件先预留任务，原生创建成功并返回 Agent ID 后才把任务标记为 Worker；完成时还必须校验同一 Agent ID。若当前运行时没有该能力或没有空闲槽位，插件会记录并播报原因，再由协调者安全地串行接管；插件不会用后台 shell、模型 API、独立用户任务或单纯的 JSON 记录伪造子智能体。

执行过程默认使用精简进度：主会话呈现阶段变化、一次波次汇总、可操作的重试/回退/阻塞、长任务心跳和最终总结，单个子智能体状态交给 Codex 原生 UI 展示。新计划默认连续静默不超过 5 分钟，每次聚合进度包含当前阶段、完成数、活动任务和下一检查点；更严格的运行时更新要求优先。该约束由当前 Codex 运行时的对话与等待机制执行，插件不引入后台守护进程。工作流还会在 Codex Desktop 提供原生标题能力时，把会话标题同步为当前计划的业务名称；CLI 或能力不可用时安全降级。已自动恢复的路径定位、辅助脚本探测和常规交接只保留在内部证据中，不再增加会话噪声。调试级生命周期输出需要显式开启。

## 环境要求

- 支持插件的 Codex Desktop 或 CLI
- Python 3，用于执行工作流状态脚本
- 只有从 GitHub 克隆或参与开发时需要 Git；压缩包安装和工作流执行支持无 Git 环境

规划前会执行一次安静、只读的 Doctor 预检，检查插件清单与辅助脚本、Python 能力、仓库状态目录以及可选的计划/调度 revision 兼容性。Doctor 不猜测原生智能体容量，该字段稳定返回 `UNKNOWN`；实际槽位由 Codex 原生运行时决定。只有阻塞项会中止规划。显式传入的外部插件根只做静态检查，一律视为不可信且不会执行其中脚本。

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

入口会根据已检查的范围与风险选择 `LIGHT`、`STANDARD` 或 `FULL`。你可以要求使用更严格的级别；已确认的级别不能在未经修订计划并再次确认的情况下被降低。

## Doctor 预检

排查问题时可以直接运行同一个只读预检：

```bash
python3 plugins/project-workflow/scripts/project_workflow_doctor.py --repo <仓库根目录>
python3 plugins/project-workflow/scripts/project_workflow_doctor.py --repo <仓库根目录> --vcs-mode NONE --json
python3 plugins/project-workflow/scripts/project_workflow_doctor.py --repo <仓库根目录> --plan <计划路径> --orchestration <调度状态路径> --json
```

默认输出一行人类可读结论，`--json` 输出稳定的机器可读字段，包括 `version_control.requested`、`resolved`、`git_available`、`git_worktree`、`rollback_capable` 和 `status`。没有计划时，`--vcs-mode` 默认使用 `AUTO`；传入计划时，Doctor 会校验其中记录的请求与解析模式。计划和调度状态路径均相对仓库根目录解析。本机插件位置能够唯一恢复时会安静完成定位，主机专属缓存路径不属于公开契约。

## 工作流状态脚本

工作流脚本位于 `plugins/project-workflow/scripts/`。

```bash
python3 plugins/project-workflow/scripts/workflow_state.py init <plan.md> --plan-id <id> --repo <仓库根目录> --vcs-mode AUTO
python3 plugins/project-workflow/scripts/workflow_state.py experience <plan.md>
python3 plugins/project-workflow/scripts/workflow_state.py start-execution <plan.md> --repo <仓库根目录> --confirmation "<用户确认消息>"
python3 plugins/project-workflow/scripts/workflow_state.py resume <plan.md> --repo <仓库根目录>
python3 plugins/project-workflow/scripts/workflow_state.py complete <plan.md> --repo <仓库根目录>
python3 plugins/project-workflow/scripts/orchestration_state.py validate <state.json> --plan <plan.md> --repo <仓库根目录> --final
python3 plugins/project-workflow/scripts/orchestration_state.py ready <state.json> --plan <plan.md> --repo <仓库根目录> --agent-only
python3 plugins/project-workflow/scripts/orchestration_state.py assign <state.json> <task-id> --plan <plan.md> --repo <仓库根目录> --owner <任务名> --expected-version <状态版本>
python3 plugins/project-workflow/scripts/orchestration_state.py activate <state.json> <task-id> --plan <plan.md> --repo <仓库根目录> --runtime-agent-id <agent-id> --runtime-task-name <canonical-task-name> --expected-version <状态版本>
python3 plugins/project-workflow/scripts/orchestration_state.py complete <state.json> <task-id> --plan <plan.md> --repo <仓库根目录> --runtime-agent-id <agent-id> --evidence <证据> --expected-version <状态版本>
python3 plugins/project-workflow/scripts/orchestration_state.py inspect <state.json> --repo <仓库根目录>
```

`experience` 返回当前业务会话标题和心跳间隔；旧计划会从一级标题或计划 ID 推导标题，并默认使用 5 分钟。生命周期写入会持有稳定计划锁。`start-execution` 会原子记录确认、校验批准的 revision；对当前 `NONE` 计划，它会在进入 `IN_PROGRESS` 前创建并绑定到本次审批的不可变基线，还可用 `--expected-revision`、`--expected-phase` 和 `--expected-sha256` 做显式 CAS。`resume` 对执行中计划幂等成功且不写回，并且是从 `BLOCKED` 恢复执行的唯一门禁入口。`complete` 会持有调度锁、再次验证全部任务并绑定所接受的 `state_version`；对当前 `NONE` 计划还会用调度任务范围或串行计划的 `filesystem_write_scopes` 重新计算并绑定基线比较。失败不修改计划，Doctor 复用同一最终验证器。低层命令继续用于历史兼容，但不能绕过恢复门禁。调度状态每次写入递增 `state_version`，并支持 `--expected-version`；释放已启动 Worker 必须携带运行身份和 `--stopped-evidence`，未启动的预留只能用 `--spawn-failed`。

这些脚本用于增强状态一致性，但它们不是授权或安全边界，也无法通过密码学方式证明自然语言确认的真实性。

`NONE` 的标准 `start-execution` 会自动创建内部基线。下面的低层命令仅用于诊断；普通 `create` 只能首次创建，恢复替换必须携带当前规范摘要 `--replace-if-sha256`：

```bash
python3 plugins/project-workflow/scripts/filesystem_snapshot.py create --repo <仓库根目录> --output .codex/project-workflow/<plan-id>/filesystem-baseline.json --exclude <声明的缓存目录>
python3 plugins/project-workflow/scripts/filesystem_snapshot.py compare --repo <仓库根目录> --baseline .codex/project-workflow/<plan-id>/filesystem-baseline.json --write-scope <允许路径>
```

按计划恢复基线使用：

```bash
python3 plugins/project-workflow/scripts/workflow_state.py create-baseline <plan.md> --repo <仓库根目录> --replace-if-sha256 <现有基线sha256>
```

按需重复 `--write-scope` 和 `--exclude`。创建默认只输出摘要，显式 `--json-details` 才输出完整清单；比较发现越界时默认失败，只有诊断场景可显式使用 `--report-only`。相对证据路径按仓库根目录解析。结果只用于证明文件变化和写入范围，不是可恢复的备份内容。

## 风险驱动验收

`STANDARD` 和 `FULL` 会按实际接口选择相关边界，而不是机械套用固定清单：空值与类型混淆、数值上下界和溢出、重复项与未知项、时钟及时区、幂等重试、原子性、并发、原始异常泄漏和恢复路径。`FULL` 的持久化状态变更还必须明确映射每个旧状态，包括运行中任务、租约缺失或过期、未知状态及其迁移或隔离结果。

独立契约验证者只接收原始需求、公开契约和验收标准，不接收实现讨论或 Worker 自验结论。它在互不重叠的范围内编写黑盒测试或问题报告，失败项返回原实现负责人修正。

## 更新

刷新 marketplace 并重新安装插件：

```bash
codex plugin marketplace upgrade project-workflow-local
codex plugin add project-workflow@project-workflow-local
```

更新后请新建 Codex 任务。

本地开发时不要把 `+codex.<缓存标识>` 写入仓库清单。仓库中的
`plugins/project-workflow/.codex-plugin/plugin.json` 始终保存正式版本号；使用下面的脚本时，
cachebuster 只会写入一次性临时副本，安装完成后自动删除：

```bash
python3 scripts/install_local_plugin.py
```

安装结果会使用 `<正式版本>+codex.<UTC微秒>-<随机尾码>` 作为本机缓存目录版本，但不会修改源码或
marketplace 文件。脚本会在安装期间短暂切换本地 marketplace，并在成功或失败时恢复原路径；
安装后持久化配置与执行前一致。安装后请新建 Codex 任务。

## 历史兼容与回滚

v0.4 保留此前的低层生命周期命令，并继续读取 v0.3 的计划和调度状态。缺少新的可选调度字段不需要迁移，缺少 `workflow_profile` 时按 `FULL` 处理，缺少 `vcs_mode` 时按 `AUTO` 读取且不会为了补字段而改写历史计划。

源码回滚基线为 `v0.3.0` 发布版本。可以恢复或重装该版本的压缩包；从 Git 克隆参与开发时也可以使用对应 tag。插件不会自动 reset、提交、打 tag、推送、部署或覆盖用户改动。本机重装通过标准 marketplace/cachebuster 流程完成，改变当前 Codex 安装时仍需用户明确授权。

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
python3 -m unittest discover -s tests -v
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
- 自动并行必须通过 20% 关键路径收益门槛，并同时受计划上限、就绪任务数量和 Codex 原生协作槽位限制。新计划默认最多两个 Worker；写入范围冲突时不会并行。
- 插件只能调度当前 Codex 运行时真实提供的原生子智能体能力，不能自行增加产品能力或 UI。
- 该插件无法阻止更高优先级指令或被人为修改的状态文件绕过其行为规则。

## 开源协议

本项目基于 [Apache License 2.0](LICENSE) 开源。
