# Project Workflow v0.4.0 完成门禁与文件安全交付报告

交付日期：2026-08-25

关联设计：[007-Project-Workflow-v0.4.0完成门禁与文件安全设计](../design/007-Project-Workflow-v0.4.0完成门禁与文件安全设计.md)

关联计划：[007-Project-Workflow-v0.4.0完成门禁与文件安全实施计划](../plan/007-Project-Workflow-v0.4.0完成门禁与文件安全实施计划.md)

## 交付结论

本轮完成了 v0.4.0 的最终门禁、生命周期并发控制、调度状态边界、NONE 文件系统证据、Doctor 复核和本机安装安全收口。所有已识别的 P1/P2 缺口均有生产修复及黑盒回归；失败门禁保持计划和证据原子不变。

源码发布版本保持 `0.4.0`。本机已安装隔离缓存版本 `0.4.0+codex.20260825125744636785-7027c810`，除安装副本 manifest 的构建元数据外，安装目录与源码插件目录一致。

## 主要变更

- `workflow_state.py`：增加稳定计划锁、revision/phase/SHA-256 CAS、严格审批类型与带时区时间校验、幂等 resume、显式仓库边界、完成时的调度最终校验和 `state_version` 绑定。
- `orchestration_state.py`：新增可复用 `validate_final_state`，严格校验任务、事件、运行身份、范围别名和 Mac 大小写/Unicode 等价路径；新状态只允许写入仓库内部状态根。
- `filesystem_snapshot.py`：使用 fd-relative 遍历与写入、`O_NOFOLLOW`、`fstat` 前后身份检查、文件与目录 fsync；目录 mode 纳入证据，FIFO/socket/device 等特殊类型 fail-closed。
- `workflow_state.py complete`：对当前 `NONE` 计划重新生成最终文件系统比较。多智能体取调度任务写入范围并集，串行计划取 `filesystem_write_scopes`；越界变化拒绝完成，成功时绑定比较摘要及增改删数量。
- Doctor：复用最终调度验证器并核对已绑定版本，阻断逃逸路径、损坏状态和不可信外部插件根。
- 本地安装器：使用微秒时间与随机 nonce 生成合法 SemVer 构建元数据，异常时恢复 marketplace，且不修改源码 manifest。
- 技能、协议、清单与双语 README：统一 `SHARED_WORKSPACE`、`resume`、显式 `--repo`、CAS、最终调度绑定及 NONE 最终比较契约。

## 兼容与迁移

| 旧数据/状态 | v0.4.0 行为 |
| --- | --- |
| 无 `state_version` 的内部调度状态 | 按 0 读取，首次合法写入递增 |
| 仓库外历史调度状态 | 允许只读诊断，禁止 mutation |
| 无 `orchestration_state`、无新 NONE 契约字段的历史串行计划 | 保持可完成，不追溯制造证据 |
| 历史快照缺目录记录、mode 或 excludes | 保持可读；生成新基线后启用完整目录证据 |
| 历史已完成 Worker 无原生运行身份 | 保持只读兼容，不伪造身份 |
| `IN_PROGRESS` 重复 resume | 门禁通过后幂等成功，不改写计划 |
| `BLOCKED` resume | 重放审批、VCS 与回滚门禁后恢复 |
| 已完成计划的调度版本漂移 | Doctor 阻断并报告不一致 |

## 验证结果

- 插件全量：`207` 项通过，`3` 项跳过。
- 生命周期专项：`41/41`。
- 最终门禁黑盒：`12/12`。
- 文档命令契约：`11/11`。
- 本地安装器：`8/8`。
- 三个技能 `quick_validate`：全部通过。
- 插件结构 `validate_plugin`：通过。
- Python 3.9 目标脚本编译：通过。
- `git diff --check`：通过。
- 文件系统竞态黑盒连续三轮通过；未读取或写入仓库外目标。

## 跳过项与残余风险

当前受限沙箱不允许构造 Unix socket 和设备节点，因此全量中的 socket/device 夹具共跳过 3 项。T03 已在非沙箱环境验证 Unix socket fail-closed；设备节点仍受主机权限限制。实现依赖 macOS/Unix 的 `fcntl`、`os.fwalk`、`dir_fd` 和 `O_NOFOLLOW`，缺少这些能力的平台会明确 fail-closed；本轮不提供 Windows 兼容层。

文件系统哈希证据只能证明范围内增改删及元数据变化，不是备份，也不提供 Git 级回滚能力。

## 安装与发布状态

- 源码 manifest：`0.4.0`。
- 本机安装：`0.4.0+codex.20260825125744636785-7027c810`。
- 安装根：`/Users/chenjiaxing/.codex/plugins/cache/project-workflow-local/project-workflow/0.4.0+codex.20260825125744636785-7027c810`。
- 未执行 commit、tag、push 或部署。
- 回滚方式仍为逐文件撤销本计划变更，并保护用户原有工作区；必要时参考 `v0.3.0` 与当前差异清单。
