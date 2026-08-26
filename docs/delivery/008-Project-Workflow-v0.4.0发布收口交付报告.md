# Project Workflow v0.4.0 发布收口交付报告

## 交付结论

v0.4.0 发布收口修复已完成。五项原始高风险复现均由独立黑盒契约关闭，独立验证未发现新的明显 P0/P1/P2 生产问题。源码清单版本保持 `0.4.0`；本次未提交、未打 tag、未推送、未部署。

## 已修复行为

- current `STANDARD/NONE` 等 v0.4 计划必须具备审批绑定的不可变文件基线和可复核最终 artifact，不能以缺字段方式退化为 legacy。
- canonical `start-execution` 一次调用原子记录原始确认、绑定文件策略与基线，并进入 `IN_PROGRESS`；冲突或失败不产生部分批准，幂等重试可恢复同绑定基线。
- 普通 baseline `create` 为 create-only；恢复替换必须提供匹配旧规范摘要的 `--replace-if-sha256` CAS。
- `complete`、`validate` 与 Doctor 共用完成证据验证器，复核 baseline、final artifact、摘要、计数、write scopes 与调度 `state_version`。
- 调度状态的内部读取、锁、CAS、临时写、rename 与 fsync 绑定同一可信目录 fd；父目录交换不能把写入重定向到仓库外符号链接。
- v0.4 completed Worker 必须具备完整原生运行身份、时序、`spawn_status=COMPLETED` 与 `runtime_verification=VERIFIED`；仅纯 legacy 历史状态允许 `UNAVAILABLE`。
- 公开技能、协议和双语 README 已同步 canonical NONE 基线、显式恢复和最终复核语义。

## 主要变更路径

- 生命周期与文件证据：`plugins/project-workflow/scripts/workflow_state.py`、`filesystem_snapshot.py`
- 调度持久化：`plugins/project-workflow/scripts/orchestration_state.py`
- 只读诊断：`plugins/project-workflow/scripts/project_workflow_doctor.py`
- 技能与协议：`plugins/project-workflow/skills/`、`plugins/project-workflow/references/`、双语 README
- 契约测试：`plugins/project-workflow/tests/`
- 本计划与交付：`docs/plan/008-Project-Workflow-v0.4.0发布收口实施计划.md`、本报告

## 验证证据

- 插件测试：230 项通过，3 项跳过。
- 独立发布收口契约：8/8 通过。
- Doctor：22/22 通过。
- 文档命令契约：11/11 通过。
- 安装器模拟：8/8 通过。
- Python 编译检查：通过。
- `git diff --check`：通过。
- 独立审查：未发现新的明显 P0/P1/P2。

3 项跳过均为当前沙箱禁止创建 Unix socket 或 device node 的环境限制；普通文件、FIFO、目录 fd、符号链接交换和失败关闭路径均已覆盖。已有非沙箱专项记录验证过可创建的 Unix socket 场景。

## 兼容与迁移

- 明确 `policy_contract: "v0.4"` 的计划和调度状态采用严格新契约。
- 无当前契约标记的纯 legacy 计划、旧快照和旧 completed Worker 保持只读兼容，不伪造原生身份。
- 为适配已批准的新契约，仅迁移四个受影响的既有黑盒测试夹具/预期；没有扩大生产代码或产品功能范围。
- fd 安全实现依赖当前 macOS/Unix 的 `dir_fd`、`O_NOFOLLOW` 等能力；平台缺少这些能力时失败关闭，不静默降级。

## 安装与版本

- 源码清单必须保持干净发布版本 `0.4.0`。
- 本机安装使用隔离 staging copy，仅给安装副本增加 `+codex.<cachebuster>`，不会修改源码版本。
- 已安装版本：`0.4.0+codex.20260825175047281354-4ddea5ec`。
- 已逐一核对四个核心脚本和 execute skill 的 SHA-256，安装缓存与源码完全一致；安装副本四个 CLI 的帮助契约正常，安装副本 Doctor 在可写临时仓库返回 `OK`。
- 安装包内测试仍以源码仓库布局定位根级 README/计划，因此不把“直接从缓存目录运行全套源码测试”列为受支持入口；发布验证以源码 230 项全量测试、安装器 8 项模拟、安装副本哈希与 CLI/Doctor 冒烟为准。

## 回滚

如需撤销本次 008 收口，可按执行前 dirty-worktree 清单逐文件撤销本计划的局部变更，保留此前 v0.4.0 工作区与用户修改；也可重新安装此前已验证的 v0.4.0 本机缓存副本。插件不会自动 reset、commit、tag、push 或覆盖用户文件。

## 未执行事项

- 未 commit。
- 未创建或移动 Git tag。
- 未 push 到 GitHub。
- 未部署任何服务。
