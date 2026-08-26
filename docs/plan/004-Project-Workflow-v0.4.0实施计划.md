---
workflow: "project-workflow/v1"
plan_id: "project-workflow-v0-4"
revision: 1
phase: "COMPLETED"
workflow_profile: "FULL"
execution_mode: "AUTO_MULTI_AGENT"
max_workers: 2
agent_topology: "SHARED_WORKSPACE"
parallelism_policy: "BENEFIT_GATED"
approved_revision: 1
approved_at: "2026-08-22T19:09:35+00:00"
confirmation_record: "确认"
---

# Project Workflow v0.4.0 实施计划

## 1. 目标

在保持审批门禁、仓库持久化和 Codex 原生子智能体机制不变的前提下，完成 v0.4.0 的可靠性与体验升级：生命周期复合命令、Doctor 预检、工作流分级、收益门槛调度、风险矩阵、独立契约验证和文档命令契约测试。

## 2. 基线

- 基线提交：`c4f45e4db678865287ef6f9fb8aa35fc567b5806`
- 基线 tag：`v0.3.0`
- 当前分支：`main`，相对远端 ahead 1；本计划不推送。
- 当前单元测试基线：27 项通过。
- 版本目标：`0.4.0+codex.<timestamp>`。

## 3. 授权边界

计划确认后允许：

- 修改 `plugins/project-workflow/`、项目双语 README 和本计划对应的交付文档。
- 使用 Codex 原生子智能体按本计划并行实施。
- 运行本地单元测试、技能验证、插件验证和 cachebuster 更新。
- 在用户同时明确允许本机重装时，通过本地 marketplace 重装插件。

计划确认不自动授权：

- Git commit、创建 `v0.4.0` tag、推送或远程发布。
- 部署到任何业务环境。
- 修改本计划写入范围之外的项目。

## 4. 任务图

### T01 生命周期 CLI 与 Doctor

- 状态：已完成 / 已验证
- 负责人：原生 Worker
- 依赖：无
- 预计实施：35 分钟
- 预计协调：5 分钟
- 关键路径：是
- 写入范围：
  - `plugins/project-workflow/scripts/workflow_state.py`
  - `plugins/project-workflow/scripts/project_workflow_doctor.py`
  - `plugins/project-workflow/tests/test_workflow_state.py`
  - `plugins/project-workflow/tests/test_project_workflow_doctor.py`
- 工作内容：
  1. 新增 `start-execution` 与 `complete`，保留旧命令兼容。
  2. 保证审批记录与阶段迁移的原子性。
  3. 实现 Doctor 的文本与 JSON 输出、退出码和静默路径恢复。
  4. 覆盖异常参数、不可写目录、revision 不匹配和缓存路径失效。
- 验证命令（DISCOVERY）：
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_workflow_state.py' -v`
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_project_workflow_doctor.py' -v`

### T02 分级工作流与风险验收协议

- 状态：已完成 / 已验证
- 负责人：原生 Worker
- 依赖：无
- 预计实施：30 分钟
- 预计协调：5 分钟
- 关键路径：是
- 写入范围：
  - `plugins/project-workflow/skills/index/SKILL.md`
  - `plugins/project-workflow/skills/plan/SKILL.md`
  - `plugins/project-workflow/skills/execute/SKILL.md`
  - `plugins/project-workflow/references/execution-checklists.md`
  - `plugins/project-workflow/references/workflow-protocol.md`
- 工作内容：
  1. 落实 LIGHT/STANDARD/FULL 选择与兼容规则。
  2. 规划阶段先运行 Doctor，并记录非阻塞建议。
  3. 固化边界矩阵、迁移矩阵与 DISCOVERY/EXACT 命令规则。
  4. 执行阶段使用生命周期复合命令，压缩可自动恢复的内部提示。
- 验证：技能结构验证、引用完整性检查、文档命令契约测试在 T04 统一执行。

### T03 收益门槛调度与状态校验

- 状态：已完成 / 已验证
- 负责人：协调者
- 依赖：无
- 预计实施：35 分钟
- 关键路径：是
- 写入范围：
  - `plugins/project-workflow/scripts/orchestration_state.py`
  - `plugins/project-workflow/tests/test_orchestration_state.py`
  - `plugins/project-workflow/references/multi-agent-orchestration.md`
- 工作内容：
  1. 增加可选估时、协调成本、关键路径、角色和独立验证字段。
  2. 计算并解释并行收益，默认 20% 门槛、最多两个 Worker。
  3. 对独立契约验证提供单任务启动例外。
  4. FULL 模式校验迁移任务与独立验证任务的存在性。
- 验证命令（DISCOVERY）：
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_orchestration_state.py' -v`

### T04 黑盒契约验证

- 状态：已完成 / 已验证
- 负责人：独立原生 Worker
- 角色：CONTRACT_VERIFIER
- 独立验证：是
- 依赖：T01、T02、T03
- 预计实施：25 分钟
- 预计协调：5 分钟
- 写入范围：
  - `plugins/project-workflow/tests/test_documented_commands.py`
  - `plugins/project-workflow/tests/test_workflow_contract.py`
- 输入隔离：仅提供本设计、原始问题清单、公开 CLI/技能契约和验收标准，不提供实现过程总结。
- 工作内容：
  1. 验证技能、README 与 argparse 的命令契约一致。
  2. 构造类型极值、时间、幂等、失败恢复与历史计划兼容用例。
  3. 验证 FULL 迁移矩阵和独立验证要求。
  4. 只新增或修改验证文件，不直接修补生产实现。
- 验证命令（DISCOVERY）：
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_documented_commands.py' -v`
  - `python3 -m unittest discover -s plugins/project-workflow/tests -p 'test_workflow_contract.py' -v`

### T05 双语用户文档

- 状态：已完成 / 已验证
- 负责人：原生 Worker
- 依赖：T01、T02、T03
- 预计实施：20 分钟
- 预计协调：5 分钟
- 写入范围：
  - `README.md`
  - `README.zh-CN.md`
- 工作内容：
  1. 说明三档工作流、Doctor、原生智能体呈现和收益门槛。
  2. 使用稳定、可测试的命令示例。
  3. 移除本机绝对缓存路径和冗余内部状态叙述。
- 验证：由 T04 文档命令契约测试和协调者双语一致性检查完成。

### T06 集成、版本与本机插件更新

- 状态：已完成 / 已验证
- 负责人：协调者
- 依赖：T04、T05
- 预计实施：25 分钟
- 写入范围：
  - `plugins/project-workflow/.codex-plugin/plugin.json`
  - `docs/plan/004-Project-Workflow-v0.4.0实施计划.md`
  - `docs/delivery/004-Project-Workflow-v0.4.0交付报告.md`
- 工作内容：
  1. 审核各 Worker 写入范围、身份和交接证据。
  2. 运行全量测试、技能验证和插件验证。
  3. 使用 plugin-creator cachebuster 更新版本。
  4. 若用户明确授权本机重装，则删除旧安装并从本地 marketplace 重新添加；否则只交付源码和重装命令。
  5. 生成交付报告，记录测试数量、遗留风险、诊断摘要和回滚基线。
- 验证命令：
  - `python3 -m unittest discover -s plugins/project-workflow/tests -v`
  - `python3 plugins/project-workflow/scripts/workflow_state.py validate docs/plan/004-Project-Workflow-v0.4.0实施计划.md`
  - `python3 plugins/project-workflow/scripts/orchestration_state.py validate .codex/project-workflow/project-workflow-v0-4/orchestration.json --plan docs/plan/004-Project-Workflow-v0.4.0实施计划.md --final`
  - 运行 skill-creator 的 `quick_validate.py`。
  - 运行 plugin-creator 的 `validate_plugin.py`。

## 5. 调度波次

### Wave 1

- T01 与 T02 由两个原生 Worker 并行执行。
- 协调者同时执行 T03。
- 三者写入范围互不重叠，预计相对串行关键路径节省超过 20%。

### Wave 2

- T04 作为隔离的契约验证 Worker 启动。
- T05 作为文档 Worker 并行启动。
- T04 不接收实现过程总结，避免验证偏置。

### Wave 3

- 协调者执行 T06，统一修复冲突、验证并交付。

## 6. 回退策略

### 6.1 迁移状态矩阵

本版本保持 `project-workflow/orchestration/v1`，新增字段均为可选并在读取时归一化；只有新建状态写入 `policy_contract: v0.4`。迁移与恢复行为如下：

| v0.3 状态或边界 | v0.4 结果 | 恢复与验证 |
| --- | --- | --- |
| `PENDING` | 保持 `PENDING` | 缺失收益、角色字段使用兼容默认值；历史计划不启用收益门槛。 |
| `ASSIGNED` / 有效原生 Worker `RUNNING` | 保持 `ASSIGNED` | runtime 身份完整时继续；重启后先与原生 roster 对账。 |
| `ASSIGNED` / Worker 身份缺失 | 拒绝为有效运行态 | 视为孤儿候选；协调者检查写入范围后显式 release 或接管，不自动伪造身份。 |
| `COMPLETED` / 历史 Worker 身份缺失 | 保持 `COMPLETED` | 标记 `runtime_verification: UNAVAILABLE`，保留证据且不倒推身份。 |
| `BLOCKED` | 保持 `BLOCKED` | 继续要求明确原因，问题解除后显式 release。 |
| 原始状态值为未知状态（包括不符合 schema 的裸 `RUNNING`） | 拒绝加载 | 不静默映射、不丢弃数据；由协调者隔离并人工确认。 |

当前调度协议不使用任务租约，因此“缺失租约”和“过期租约”均为 N/A；等价的活性判断由 runtime 身份、原生 roster 与 `spawn_status` 共同完成。若未来引入租约，必须新增 revision 和实际租约迁移规则，不能把本矩阵当作授权。

- 重复迁移：归一化使用幂等默认值；重复读取结果一致。
- 崩溃重入：状态写入采用临时文件与原子替换；重启后先对账，避免重复分配。
- 回滚：v0.3.0 能忽略可选扩展字段；若新策略异常，保留状态证据并按 `v0.3.0` tag 重装，不执行破坏性 reset。

1. 单个 Worker 失败：协调者读取交接与工作区变更，在原写入范围内重试一次或收回任务。
2. CLI 兼容失败：保留 v0.3.0 原命令路径，新复合命令不进入文档主路径。
3. 调度字段导致历史状态失败：将新字段降为纯可选并恢复历史默认行为。
4. 本机插件重装失败：保留源码结果，继续使用已安装的 v0.3.0，并给出可恢复命令。
5. 整体回滚依据为 Git tag `v0.3.0`；不自动 reset、checkout 或覆盖用户文件。

## 7. 完成定义

- T01 至 T06 均为 `COMPLETED / VERIFIED`。
- 全量测试、技能验证、插件验证全部通过。
- 未出现跨任务写入范围冲突。
- 历史计划兼容性和文档命令契约通过黑盒验证。
- 工作流状态切换为 `COMPLETED`，交付报告落盘。
- 未经单独授权，不创建新 commit/tag，不推送。

## 8. 确认门禁

用户已于 `2026-08-22T19:09:35+00:00` 明确确认 revision 1，原始确认文本为“确认”。该确认授权计划范围内的原生子智能体委派，但没有授权本机重装、Git commit、创建新 tag 或推送。

## 9. 执行证据

- Wave 1：两个原生 Worker 分别完成生命周期/Doctor 与分级协议，协调者完成调度器；写入范围无冲突。
- Wave 2：独立验证者首次发现 4 项偏差，原负责人和协调者完成返工后，原测试选择器全部关闭；文档 Worker 完成双语说明。
- 关键返工：严格 ISO-8601 带时区审批时间、零/缺失估时串行回退、验证者写入范围隔离、迁移状态矩阵。
- 全量单元与契约测试：72/72 通过。
- 三个技能 `quick_validate.py`：全部通过。
- `validate_plugin.py`：通过。
- 源码版本：`0.4.0+codex.20260822192401`。
- 本机重装：未授权，未执行；当前 Codex 会话继续使用已安装的 v0.3.0。
- Git：未 commit、未创建 `v0.4.0` tag、未 push。
