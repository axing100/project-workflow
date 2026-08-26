# Project Workflow v0.4.0 交付报告

## 交付结果

Project Workflow v0.4.0 源码实现完成。新版本在保留审批门禁、仓库持久化与 Codex 原生子智能体 UI 的基础上，降低命令漂移和无收益并行的概率，并把迁移、边界与独立契约验证纳入 FULL 工作流。

源码 manifest 版本为 `0.4.0+codex.20260822192401`。由于用户没有授权本机重装，本轮没有改变 Codex 当前已安装插件，也没有提交、打新 tag 或推送。

## 主要变更

- 新增原子生命周期入口 `start-execution`、受保护的 `complete` 和只读 `validate`；旧低层命令继续兼容。
- 审批时间严格校验带时区 ISO-8601，非法、naive 或越界时间在写入前拒绝。
- 新增安静、只读的 Doctor，检查插件、Python、CLI、状态目录和计划/调度 revision；无法探测原生智能体时明确返回 `UNKNOWN`。
- 新增 `LIGHT`、`STANDARD`、`FULL` 三档强度，所有档位继续要求计划确认。
- 自动多智能体采用默认 20% 收益门槛和最多两个 Worker；零或缺失估时不能证明收益时回退主会话。
- 独立 `CONTRACT_VERIFIER` 可作为单 Worker 例外，但写入范围不得与实现任务重叠。
- 新增边界矩阵、迁移状态矩阵、稳定的 `DISCOVERY / EXACT` 验证命令规则和紧凑诊断呈现。
- 双语 README 与三个技能同步更新；公共文档不包含本机插件缓存版本路径。
- 后续体验增强加入 5 分钟默认业务心跳、可校验的 `experience` 契约，以及 Codex Desktop 原生会话标题同步与无能力降级规则。

## 独立验证闭环

独立验证者首次运行 68 项测试时发现 4 项偏差：

1. 本次 FULL 计划缺少实际迁移状态矩阵。
2. 非法 `--at` 审批时间未被拒绝。
3. 零估时绕过并行收益门槛。
4. 验证者与实现任务可以声明重叠写入范围。

对应实现返工后，验证者使用原测试选择器复验，四项均关闭；最终全量 72 项全部通过。

## 验证证据

- `python3 -m unittest discover -s plugins/project-workflow/tests -v`：72/72 通过。
- `test_documented_commands.py`：6/6 通过。
- `test_workflow_contract.py`：14/14 通过。
- index、plan、execute 三个技能 `quick_validate.py`：全部通过。
- `validate_plugin.py plugins/project-workflow`：通过。
- `git diff --check`：通过。
- Python 编译检查：通过；Mac 沙箱下字节码缓存可定向至 `/private/tmp`。

## 兼容与迁移

- 历史计划缺少 `workflow_profile` 时继续可读，并按严格的 FULL 语义解释。
- 历史调度状态缺少收益与角色字段时继续使用 legacy 调度行为。
- 历史已完成 Worker 缺少运行时身份时保留证据并标为 `UNAVAILABLE`，不伪造身份。
- 新建 FULL 状态必须有独立契约验证者；验证范围与实现范围重叠会被拒绝。
- 详细的 PENDING、ASSIGNED/RUNNING、COMPLETED、BLOCKED、孤儿、未知状态和崩溃重入规则见实施计划迁移状态矩阵。

## 权限、部署与回滚

- 未执行本机插件重装；需用户另行明确授权。
- 未执行 Git commit、`v0.4.0` tag、push、Release 或部署。
- 当前稳定回滚基线为 `v0.3.0` tag。
- 如 v0.4.0 后续安装失败，保留当前源码和证据，继续使用已安装的 v0.3.0；不得使用破坏性 reset 覆盖用户改动。

## 遗留风险

- Doctor 的目录可写判断遵循其运行进程权限；受限 Codex 沙箱可能正确报告状态目录不可写，而宿主终端权限不同。
- 原生子智能体容量无法由脚本可靠探测时保持 `UNKNOWN`，实际并发仍由 Codex 运行时决定。
- 源码修改当前尚未提交，`v0.4.0` tag 也尚未创建；需要单独授权后才能形成新的 Git 发布基线。

## 建议提交信息

`release: project workflow v0.4.0`
