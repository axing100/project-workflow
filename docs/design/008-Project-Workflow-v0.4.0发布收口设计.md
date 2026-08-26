# Project Workflow v0.4.0 发布收口设计

## 1. 背景与目标

007 号交付后的独立复审确认现有 207 项插件测试全部通过，但仍存在五个发布阻断缺口：新 NONE 计划可被误判为历史契约、基线可覆盖且未绑定批准记录、v0.4 完成 Worker 可错误继承历史身份兼容、调度状态字符串路径写入仍存在父目录交换窗口，以及完成后的 validate/Doctor 不复核文件系统证据。

本轮不增加业务能力，只关闭上述证据链和持久化边界。完成标准不是“新增测试通过”，而是原始五项复现全部失败关闭、全量回归通过，并由隔离的黑盒验证者再次审查后没有明显 P0/P1/P2 缺口。

## 2. 范围

### 2.1 范围内

- 为新计划持久化明确的 `policy_contract: "v0.4"`，并统一当前契约与纯历史契约的识别规则。
- 使 NONE 基线默认不可覆盖，并把基线内容摘要、计划 ID、revision 和批准记录绑定到生命周期状态。
- 完成时持久化可复核的最终差异 artifact；计划绑定 artifact 摘要与增改删计数。
- `validate` 与 Doctor 复用同一 completed-evidence validator，拒绝缺失、删除、篡改或不一致的 NONE 证据。
- `policy_contract: "v0.4"` 的完成 Worker 必须具有完整原生运行身份、完成状态和验证证据；历史状态继续只读兼容。
- 调度状态的读取、锁和原子替换改用持有的仓库内部目录 fd，避免父目录重命名或符号链接替换把读写重定向到仓库外。
- 更新公开命令、迁移说明、黑盒契约和交付报告；完成后重新安装本机隔离缓存。

### 2.2 范围外

- 不改变插件 ID、发布版本号、Codex 原生 UI 或智能体图标。
- 不引入数据库、后台守护进程、通用事务框架或 Windows 文件系统兼容层。
- 不重构与五项缺口无关的调度、技能或安装器逻辑。
- 不执行 commit、tag、push、部署或清理用户工作区。

## 3. 方案

### 3.1 明确的新旧契约

`workflow_state init` 为所有新计划写入 `policy_contract: "v0.4"`。严格契约不再依赖单一可选字段是否存在。为兼容 007 之前已经创建但尚无 marker 的 v0.4 计划，存在 `workflow_profile`、`vcs_mode`、`resolved_vcs_mode`、`rollback_required`、编排字段或 v0.4 展示字段中的任一组时按过渡 v0.4 严格校验；只有缺少这些新字段的纯历史计划进入 legacy 分支。

未知或未来 `policy_contract` 失败关闭，不静默降级为历史契约。

### 3.2 基线不可变与批准绑定

快照 `create` 默认只创建新目标，目标已存在即失败。恢复性替换必须显式提供旧摘要 CAS，避免误重跑命令重置基线。

当前 NONE 计划的 baseline 持久化以下绑定：plan ID、revision、approved revision 和确认记录摘要。生命周期通过受计划锁保护的绑定入口记录 baseline 路径与 canonical JSON SHA-256。完成入口同时验证：

1. 当前计划仍是同一批准 revision；
2. baseline 绑定字段与计划一致；
3. baseline 实际摘要等于计划绑定摘要；
4. scopes/excludes 与批准配置一致；
5. 最终变化不越过任务写入范围。

### 3.3 可复核的完成证据

完成入口把最终比较写入仓库内部 `filesystem-final-diff.json`，其中包含 plan ID、revision、baseline SHA-256、当前快照摘要、scopes/excludes 和增改删/越界列表。计划只在 artifact 持久化成功后进入 `COMPLETED`，并绑定 artifact 路径、摘要和计数。

`workflow_state validate` 与 Doctor 调用共享验证器，核对 baseline、final artifact、摘要、计数、plan/revision 与调度版本。完成后不重新扫描实时工作区，因为后续合法修改不应篡改历史交付结论；它们验证的是完成时持久化证据的完整性。

### 3.4 v0.4 Worker 身份

任务验证器接收根级 policy contract。只有纯 legacy 状态允许已完成 Worker 缺少原生身份并规范化为 `UNAVAILABLE`。v0.4 完成 Worker 必须具有非空 `runtime_agent_id`、canonical task name、合法 spawn/finish 时间、`spawn_status=COMPLETED` 与 `runtime_verification=VERIFIED`。

### 3.5 调度状态 fd 安全

调度状态在显式 repo 下从真实仓库根目录 fd 逐级 `O_NOFOLLOW|O_DIRECTORY` 打开内部状态父目录。锁文件、状态读取、临时文件、rename 和目录 fsync 都相对同一持有 fd 执行，不再在安全检查后重新解析字符串父路径。缺少所需 Unix API 时失败关闭。

不带 repo 的历史只读 inspect/validate 保持兼容；所有 mutation 继续要求内部状态路径。

## 4. 迁移状态矩阵

| 旧状态 | 新行为 |
| --- | --- |
| 新建计划 | 显式写入 `policy_contract: "v0.4"` |
| 缺 marker 但含 v0.4 计划字段 | 作为过渡 v0.4 严格校验，不享受 legacy 绕过 |
| 缺 marker 且缺全部 v0.4 字段的纯历史计划 | 保持 legacy 读取与原有单智能体兼容 |
| 未知/未来 plan policy | 隔离并失败，不自动降级 |
| 当前 NONE 计划无 baseline 绑定 | 阻断开始/完成，要求创建并绑定证据 |
| 历史无绑定 baseline | 仅历史计划兼容；修订后必须升级为 v0.4 绑定格式 |
| baseline 已存在 | 普通 create 拒绝；显式恢复需旧摘要 CAS |
| 完成 artifact 缺失、摘要或计数不符 | validate 与 Doctor 阻断，不自动重建历史证据 |
| orchestration 无 policy marker | 按 legacy 读取；完成 Worker 缺身份显示 `UNAVAILABLE` |
| `policy_contract: "v0.4"` 完成 Worker 缺身份/时间/验证 | 阻断最终验证，不自动补造身份 |
| v0.4 活跃 Worker 身份完整 | 保持运行；阻塞仍占槽位与范围 |
| 活跃 Worker 身份缺失或损坏 | 隔离为无效状态，禁止完成；由协调者依据 stopped evidence 恢复 |
| 未知任务状态或未来 policy | 失败关闭，不改写原文件 |
| 调度写入中父目录重命名 | 持有目录 fd 继续写原可信目录或稳定失败，不写外部目标 |
| 重复 mutation/CAS 冲突 | 只有版本匹配者成功，重试前重新检查状态 |
| 写入崩溃重入 | 原文件或完整新文件二选一；临时文件不成为有效状态 |
| 回滚 | 逐文件撤销本轮局部改动；不 reset、不覆盖用户现有修改 |

本插件没有租约字段；“有效/缺失/过期 lease”维度 N/A。对应恢复边界由 runtime 身份、状态版本、stopped evidence 和 Worker slot/scope 所有权承担。

## 5. 安全、兼容与可维护性

- 不建立新的通用抽象层；文件系统 fd 适配限定在已有状态 helper 内的小型函数。
- baseline 和 final artifact 使用现有 JSON schema 的可选绑定字段扩展；纯历史文档保持只读兼容。
- 同权限本地进程仍能直接编辑普通文件，插件不宣称是恶意本机用户的密码学安全边界；目标是让公开 helper、恢复和误操作不可静默伪造证据。
- 所有错误保持稳定非零退出码且不泄露 traceback。

## 6. 验收与回滚

五个原始黑盒复现必须全部由失败门禁关闭：新 STANDARD/NONE 无证据、baseline 重建掩盖改动、v0.4 Worker 无身份、调度父目录交换外写、完成证据删除/伪造。

完成后运行插件全量、安装器、三技能、插件结构、Python 编译和 diff-check，并对实际安装副本做一致性验证。独立验证者只接收本设计、原始五项复现和公开契约，不接收实现讨论。

回滚限于本轮文件的逐文件补丁撤销。仓库已有未提交改动全部保留；不执行 Git reset、checkout、commit、tag 或 push。
