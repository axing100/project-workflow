# Project Workflow v0.4.0 完成门禁与文件安全设计

## 1. 背景与目标

v0.4.0 独立复审确认现有 156 项测试均通过，但仍存在完成门禁、审批记录、恢复语义、无 Git 单智能体拓扑、Mac 路径别名、仓库路径边界和文件系统竞态等未覆盖缺口。本设计在不引入通用事务框架或后台守护进程的前提下完成发布前收口。

目标：

- 计划只有在调度任务与模式证据通过最终校验后才能完成。
- 审批、恢复和生命周期写入具有严格类型、时间、锁与冲突语义。
- `NONE + SINGLE_AGENT`、`IN_PROGRESS` 恢复和 Mac 默认文件系统可以正常、安全工作。
- 调度范围、状态路径、Worker 身份和历史事件结构不可通过别名或损坏数据绕过。
- NONE 快照对符号链接竞态和特殊文件采取 fail-closed；目录权限纳入证据。
- 本地重装 cachebuster 唯一，Markdown 权限保持不变。

非目标：

- 不实现跨平台通用文件系统沙箱。
- 不提供 Windows 文件锁支持；当前目标系统为 macOS。
- 不改变插件 ID、Git 提交历史或原生 Codex UI。
- 本计划不授权 commit、tag、push 或部署。

## 2. 核心方案

### 2.1 原子最终完成

为生命周期完成入口增加显式仓库上下文和调度最终证据校验。存在 `orchestration_state` 时，`complete` 必须加载状态、验证计划关联、确认全部任务完成并绑定所见 `state_version`；NONE 模式还必须验证最终快照比较证据。任何失败都不得改变计划阶段。

Doctor 对 `COMPLETED` 计划复用相同的完整最终验证，而不是只校验计划元数据。

### 2.2 生命周期锁、审批与恢复

- 对计划 Markdown 使用稳定的旁路锁覆盖完整读改写，锁等待上限与调度状态一致。
- 可选 CAS 使用 revision、phase 和内容摘要，冲突只允许一个写入者成功。
- `approved_at` 必须是带时区 ISO-8601 字符串；`confirmation_record` 必须是非空字符串。
- `resume` 对 `IN_PROGRESS` 幂等重放门禁而不写回；对 `BLOCKED` 校验后进入 `IN_PROGRESS`。
- 原子替换继承已有 Markdown mode，新文件使用明确的文档权限。

### 2.3 拓扑、范围和运行身份

- `execution_mode` 决定是否创建 Worker；`agent_topology` 描述工作区。`NONE` 下单智能体和多智能体统一使用 `SHARED_WORKSPACE`，单智能体仍由执行模式保证 coordinator-only。
- 写入范围使用 POSIX 规范路径；拒绝 `.`、`..`、重复分隔符、绝对路径和驱动器路径。
- 针对仓库所在卷生成比较键：Unicode NFC；大小写不敏感卷增加 `casefold()`。
- 活跃 Worker 的 runtime agent ID 与 canonical task name 必须唯一。
- 任务与事件时间统一为严格带时区 ISO-8601；事件对象校验必填字段与类型。

### 2.4 仓库路径边界

带 `--repo` 的计划、调度和 Doctor 路径必须解析在仓库根内。新状态只能写入 `.codex/project-workflow/`；历史外部状态最多只读并给出迁移提示，不允许继续写入。

所有 mutation 在写入前重复检查父路径组件，避免只依赖一次 Doctor 预检。

### 2.5 文件快照安全

普通文件使用 `os.open(..., O_NOFOLLOW)` 和 `fstat` 后按文件描述符哈希；身份在读取前后变化则失败。输出状态路径使用持有目录描述符的逐级无跟随打开与相对 rename，并 fsync 文件及目录。

FIFO、socket、设备节点等无法安全表示的类型默认稳定失败。普通目录记录 type 与 mode，使目录权限变化可见。实现限定为小型 macOS/Unix 适配层，不抽象成通用虚拟文件系统。

### 2.6 安装与发布准备

cachebuster 使用微秒加短随机 nonce，并校验生成值符合 SemVer build metadata。源码 manifest 保持 `0.4.0`。完成后仅本机隔离重装；Git 发布另行等待用户授权。

## 3. 兼容与迁移状态矩阵

| 旧状态 | 新行为 |
| --- | --- |
| `IN_PROGRESS` 调用 resume | 门禁通过后幂等成功，不改写确认与阶段 |
| `BLOCKED` 调用 resume | 重放审批/VCS/回滚门禁后恢复执行 |
| 完成计划但调度不完整 | Doctor 阻断；禁止新 complete 产生该状态 |
| 历史计划无 orchestration_state | 保持单智能体兼容，可完成 |
| 历史 `NONE + coordinator-only` | 读取时兼容并给出规范化提示；修订后写为 SHARED_WORKSPACE |
| 历史 state 无 state_version | 继续按 0 读取，首次写入递增 |
| 历史事件缺少新字段 | 可明确识别的旧事件只读兼容；非法类型或未知结构拒绝 |
| 活跃 Worker 重复 runtime 身份 | 拒绝调度与 Doctor 验证，不自动重写 |
| 外部 orchestration 路径 | 历史只读诊断；禁止 mutation，要求迁移到内部状态根 |
| 历史快照无目录记录 | 可比较普通文件；首次新基线后启用目录 mode 证据 |
| FIFO/socket/设备节点 | fail-closed，不静默报告 clean |
| 写入期间文件变成 symlink | 失败且不生成新证据；恢复后重试 |
| 写入期间状态父目录被替换 | 目录描述符保持可信目标或失败，不写到外部目录 |
| 重复迁移/崩溃重入 | 锁、CAS、原子替换和幂等 resume 防止重复副作用 |
| 回滚 | 不自动 reset；依赖 Git HEAD、当前差异清单和用户现有改动保护 |

## 4. 边界与验收

- 类型：布尔、数字、容器不得冒充审批字符串或时间。
- 时间：naive、非法 offset、溢出和畸形历史事件均拒绝。
- 路径：`a/b`、`a/./b`、`a//b`、大小写和 Unicode 等价路径不得并发。
- 并发：审批、恢复、完成和调度竞争只允许符合 CAS 的写入成功。
- 原子性：最终调度、快照或审批校验失败时计划与证据字节不变。
- 恢复：IN_PROGRESS、BLOCKED、缺失/损坏调度、重复 Worker 身份均有明确结果。
- 文件系统：symlink 交换、FIFO、socket、目录 chmod、输出父目录替换均有黑盒覆盖。

## 5. 风险与回滚

主要风险是 fd-relative 文件操作在 Python/macOS 上的接口差异。实现必须限制在 snapshot 安全适配层，并保留普通路径的清晰错误。若该部分无法在当前 Python 3.9 稳定实现，则降级为检测变化后 fail-closed，不以弱检查冒充强安全。

工作区存在用户未提交改动，任何阶段不得 reset、checkout 覆盖或清理未跟踪文件。回滚采用逐文件补丁撤销和既有 `v0.3.0` 基线；commit、tag、push 均需另行授权。
