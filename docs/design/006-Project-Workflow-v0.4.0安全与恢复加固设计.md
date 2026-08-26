# Project Workflow v0.4.0 安全与恢复加固设计

## 1. 背景与目标

当前 v0.4.0 的功能与现有回归正常，但独立审查发现 Doctor 信任边界、阻塞恢复、活跃 Worker 释放、无 Git 快照、调度并发、文档命令与用户体验仍有明显缺口。本轮在不改插件 ID 和源码语义版本的前提下完成加固。

目标：

1. Doctor 不执行被检查仓库提供的脚本，并对调度状态进行完整校验。
2. 所有进入或恢复 `IN_PROGRESS` 的路径共用审批、revision、VCS 和回滚门禁。
3. 仍在运行的原生 Worker 不得被调度状态遗忘或释放写入范围。
4. 无 Git 证据不能通过符号链接写出工作区，越界写入默认失败，并能识别可执行权限变化。
5. 并发调度写入不丢失，历史 v0.3/v0.4 状态可安全读取和迁移。
6. 消除确认门禁、CLI 命令、路径语义、标题与心跳文案的自相矛盾。

## 2. 范围与非目标

范围包括四个脚本、三个技能、共享协议/检查表、双语 README、安装器与独立契约测试。保留源码版本 `0.4.0`，通过本机 cachebuster 安装验证。

非目标：不修改插件 ID，不实现 Git 以外的 VCS，不控制 Codex Desktop 的原生智能体图标，不提交、打 tag、推送或部署。

## 3. 信任边界

### 3.1 Doctor

- 脚本契约检查只针对当前正在运行的已安装插件根目录，不从目标仓库自动选择同名脚本。
- `--plugin-root` 不再导致未信任 Python 执行；如保留外部路径检查，只读取静态清单与文件存在性。
- Doctor 复用调度器的 `load_state/validate_state/validate_plan`，对依赖环、范围重叠、Worker 身份、策略和迁移字段给出稳定 blocker。

### 3.2 路径与符号链接

- `.codex/project-workflow` 的未解析路径链不得包含符号链接，解析后仍必须位于解析后的仓库根目录。
- 输出写入前重新检查父链；使用同目录临时文件、`fsync` 与原子替换。
- 带 `--repo` 的命令把相对计划、基线和输出路径统一解析为仓库相对；不带 `--repo` 的历史调用保留当前目录语义。

## 4. 生命周期与回滚门禁

- 新增或统一 `resume` 入口；`BLOCKED -> IN_PROGRESS` 必须校验当前 revision 的完整确认记录、VCS 解析和回滚能力。
- 低层 `transition` 不允许直接恢复 `IN_PROGRESS`，保留其他历史迁移。
- 新计划可持久化 `rollback_required: "true"|"false"`。值为 `true` 时，任何 profile 在 `NONE` 下都需要三字段已验证回滚；迁移、安全整改和潜在数据丢失计划必须设为 `true`。历史缺失值默认 `false`，FULL 仍由 profile 强制回滚。
- `resolved_vcs_mode: NONE` 只允许 `agent_topology: SHARED_WORKSPACE`或单智能体协调者拓扑，调度初始化、恢复和最终校验都拒绝矛盾组合。

## 5. Worker 停止、释放与并发

- `WORKER_PENDING` 在原生创建失败后可直接 `--spawn-failed` 释放。
- `WORKER + RUNNING` 被阻塞时保留 runtime identity、Worker 槽位和写入范围，直到协调者通过同一 runtime agent ID 记录已成功中断。
- 普通 `release` 不得清理未验证停止的 Worker。停止证据写入审计事件，然后才返回 `PENDING`。
- 所有调度读改写使用跨进程文件锁。根状态新增单调 `state_version`；历史缺失值按 0 读取，每次成功写入加 1，用预期版本/CAS 防止过期覆盖。

## 6. 无 Git 证据

- 新快照记录稳定 POSIX 权限位，至少包含普通文件的 executable bits。历史基线没有权限字段时继续按内容证据比较，交付披露该次无权限基线。
- `compare` 在 `out_of_scope` 非空时默认返回稳定非零码；仅显式 `--report-only` 返回 0。
- 新基线默认不排除 `.idea/.vscode` 这类可交付项目配置。额外排除通过可重复 `--exclude` 显式持久化；历史基线沿用其原有排除语义。
- `create` 默认只输出文件数、字节数、证据摘要和保存路径；完整清单仅通过显式 `--json-details` 输出。

## 7. 用户体验与文档

- 删除“在 Project Workflow 内跳过 confirmation gate”的语义。用户明确不要规划/确认时，退出 Project Workflow 并交回普通工作流。
- 修正 `inspect` 命令、仓库相对路径、心跳“静默不超过”文案，并明确 Doctor 不能自行探测原生槽位。
- 标题和心跳是 Codex 运行时协议，脚本无法独立保证 UI 调用。新增轻量 checkpoint 证据，记录最后用户更新时间和标题同步结果；不宣称插件能自行绘制或配置原生智能体图标。

## 8. 迁移状态矩阵

| 历史状态 | 新行为 | 重复/崩溃恢复 |
| --- | --- | --- |
| 缺少 `state_version` | 按 0 读取，下次成功写入升为 1 | 文件锁下只迁移一次 |
| `PENDING` | 保持 `PENDING` | 重复读取无写入 |
| `ASSIGNED + WORKER_PENDING` | 保留预留；创建失败可 `--spawn-failed` | 恢复时先核对原生运行时 |
| `ASSIGNED + WORKER + RUNNING` | 保留槽位和范围 | 中断确认前不得 release |
| `BLOCKED + WORKER + RUNNING` | 视为仍活跃的阻塞 Worker | 继续占用槽位/范围，已停止证据后释放 |
| `BLOCKED` 且无活跃 Worker | 保持普通阻塞任务 | 解决后可返回 `PENDING` |
| `COMPLETED + VERIFIED` | 保持完成 | 不重放 Worker |
| 历史 `COMPLETED` 无 runtime ID | 保持 `UNAVAILABLE` 兼容身份 | 不伪造 ID，交付披露 |
| 缺少 `rollback_required` | 按 `false` 读取；FULL 仍强制回滚 | 不为补字段改写计划 |
| 旧快照无 mode bits | 内容比较保持兼容，权限证据标记不可用 | 新任务创建新基线 |
| `NONE + ISOLATED_WORKTREE/REMOTE_AGENT` | 拒绝调度初始化或恢复 | 修订计划并重新确认 |
| 未知 task state/未知版本 | 稳定阻断，不静默降级 | 保留原 JSON 供诊断 |
| 写入中崩溃 | 旧文件或完整新文件二选一 | 锁释放后重读 `state_version` |
| 重复迁移 | 验证现有字段，不重置版本/证据 | 幂等 |

## 9. 验收与回滚

必须增加恶意仓库 Doctor、符号链接状态根、越界退出码、权限变化、恢复漂移、活跃 Worker 阻塞/中断/释放、并发 CAS、旧状态迁移、调度浅校验及文档命令黑盒测试。

回滚基线为本轮实施前的当前工作区；本轮不执行自动 reset。若一致性修复不能通过历史兼容测试，保留原实现文件并不安装新缓存版本。
