# Project Workflow 插件交付报告

## 文档信息

- 状态：已完成
- 日期：2026-08-20
- 设计文档：[001-project-workflow插件设计](../design/001-project-workflow插件设计.md)
- 实施计划：[001-project-workflow插件实施计划](../plan/001-project-workflow插件实施计划.md)
- 插件版本：`0.1.0`
- Marketplace：`project-workflow-local`

## 一、交付结果

已在独立目录 `<user-home>/IdeaProjects/project-workflow` 创建可分发的 Codex marketplace 仓库，并在本机安装启用 `project-workflow@project-workflow-local`。

插件提供：

- `project-workflow:index`：唯一隐式入口，负责阶段识别和路由。
- `project-workflow:plan`：只制定持久化设计和计划，输出确认请求后结束当前回合。
- `project-workflow:execute`：校验明确批准记录后执行、测试和交付。
- `workflow_state.py`：初始化、批准、检查执行资格和控制合法状态迁移。

`plan` 与 `execute` 均设置 `policy.allow_implicit_invocation: false`，避免与入口或其他相似技能竞争触发。

## 二、主要文件

- `.agents/plugins/marketplace.json`：可共享 marketplace 配置。
- `plugins/project-workflow/.codex-plugin/plugin.json`：插件清单。
- `plugins/project-workflow/skills/*`：三个技能及 UI 元数据。
- `plugins/project-workflow/references/workflow-protocol.md`：确认门禁、所有权和状态协议。
- `plugins/project-workflow/references/execution-checklists.md`：执行质量门禁。
- `plugins/project-workflow/references/multi-agent-orchestration.md`：可选多代理规则。
- `plugins/project-workflow/scripts/workflow_state.py`：标准库状态脚本。
- `plugins/project-workflow/tests/test_workflow_state.py`：状态机回归测试。
- `README.md`、`LICENSE`：分发说明和 MIT 许可证。

## 三、验证证据

### 自动化测试

```text
python3 -m unittest discover -s plugins/project-workflow/tests -v
Ran 7 tests
OK
```

覆盖：

- 未确认计划不能执行；
- 当前版本明确确认后可执行；
- 批准版本不一致时拒绝执行；
- 非法状态迁移被拒绝；
- 重大变更必须递增版本并清除旧确认；
- `IN_PROGRESS` 恢复与 `COMPLETED` 流程；
- Markdown 正文保持不变。

### 结构验证

- 三个 `quick_validate.py` 检查全部通过。
- `validate_plugin.py plugins/project-workflow` 通过。
- marketplace JSON 与 plugin JSON 解析通过。
- README 与插件归档未发现 TODO、开发者绝对路径、私钥或 API Key 文本。
- 未发现尾随空白或生成缓存目录。

### 安装验证

- `codex plugin marketplace list` 包含 `project-workflow-local`。
- `codex plugin list` 显示 `project-workflow` 为 `installed, enabled`，版本 `0.1.0`。
- 安装缓存包含三个技能、共享参考、脚本和测试。

## 四、旧技能迁移与回滚

旧技能已从发现路径移动到：

```text
<user-home>/.codex/skills-disabled/project-planner-executor-20260820
```

未删除任何旧技能文件。若需回滚：

1. 执行 `codex plugin remove project-workflow`；
2. 必要时执行 `codex plugin marketplace remove project-workflow-local`；
3. 将上述备份目录移回 `~/.codex/skills/project-planner-executor`；
4. 新建 Codex 任务以重新加载技能。

## 五、分发说明

可以将整个 `project-workflow` 目录压缩后发送，或推送到任意 Git 仓库。接收方克隆或解压后执行：

```bash
codex plugin marketplace add <path-to-project-workflow>
codex plugin add project-workflow@project-workflow-local
```

安装后需要新建 Codex 任务加载插件。

## 六、Git 与授权状态

- 本地 Git 分支：`main`。
- 当前无提交，全部交付文件处于未跟踪状态。
- 未执行 `git commit`。
- 未配置远程，未执行 `git push`。
- 建议提交信息：`feat: add approval-gated project workflow plugin`

## 七、限制与后续验证

- 状态脚本能校验字段、版本和迁移，但不能从技术上证明自然语言确认真实性；技能协议负责语义约束。
- 受当前运行规则限制，未启动子代理做独立前向测试。
- 建议在一个新的 Codex 任务中验证真实行为：首次复杂需求必须停在确认门禁，后续明确确认才进入执行。
