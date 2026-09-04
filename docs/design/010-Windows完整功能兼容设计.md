# Windows 完整功能兼容设计

计划：[010-Windows完整功能兼容实施计划](../plan/010-Windows完整功能兼容实施计划.md)

## 目标与交付底线

用户要求：插件面向生产级客户，原生 Windows 必须可安装并使用完整功能，不以 WSL、Git Bash、关闭锁或关闭安全检查作为解决方案。保留 macOS/Linux 行为与中文、英语体验。

范围覆盖安装/更新、Doctor、规划审批、开始/恢复/完成、任务双状态、渲染、迁移、单智能体与多智能体编排、无 Git 快照及回滚检查。原生智能体能力仍由宿主提供，插件不得以模拟进程冒充原生 Worker。

计划版本为 0.5.1；只有目标平台功能及安全验证通过后才允许声明可交付。构建通过、Mac 模拟测试通过、CLI --help 通过均不能代替 Windows 全流程验收。

## 基线与缺陷

- 基于 main 的合并提交 e35e7f9 创建 feature/010-windows-support；不复用已删除的 feature/project-workflow-v0.4.1。
- workflow_state.py、orchestration_state.py、filesystem_snapshot.py 无条件导入 fcntl。
- getuid、fchmod、目录 fsync、O_NOFOLLOW/O_DIRECTORY、dir_fd、fwalk 等存在平台假设；部分路径显式拒绝没有 POSIX 描述符能力的系统。
- task_state.py 通过 InternalStateAccess 依赖上述能力，迁移回滚也直接使用 dir_fd。
- 安装器直接调用 codex，未覆盖 Windows 的可执行文件/命令包装器、字符编码和路径场景。
- 仓库没有 .github/workflows 跨平台验收；既往 macOS 证据不足以证明 Windows 支持。

## 技术方案

### 1. 统一平台能力层

新增有限职责的平台 I/O 门面及 Windows 后端，核心工作流只调用稳定接口：可信目录访问、普通文件打开、互斥锁、原子替换、同步、删除、快照枚举与文件身份检查。Windows 专用导入只在 Windows 后端发生；POSIX 分支保留既有安全语义。尽量使用标准库与 Windows 原生 API，不要求客户额外安装编译工具。

- POSIX 保留 fcntl 文件锁与描述符相对访问，锁路径和互斥范围不得意外改变。
- Windows 使用原生文件句柄和字节范围锁（优先 LockFileEx/UnlockFileEx），显式处理非阻塞获取、单调时钟超时、异常释放、进程退出回收和句柄关闭；不能用锁文件“存在与否”代替操作系统互斥。
- 内部锁路径保持稳定，不在每次解锁后删除；无仓库兼容入口使用用户私有目录及稳定身份，不调用 getuid。
- 能力缺失应由 Doctor 输出可操作诊断，不能在模块导入时崩溃，也不能以返回成功掩盖未执行的功能。

### 2. 等价安全语义

Windows 不能仅以 exists/resolve 检查之后直接路径写入作为 POSIX 安全访问的替代。通过 CreateFileW 打开目录/文件句柄，控制共享模式，检查 reparse point 和文件身份，并在操作期间保持可信祖先有效，防止检查后目录被替换或重定向。实现后以 Windows 原生竞态测试验证。

- 插件状态目录拒绝符号链接、junction 和其他可能重定向访问的 reparse point，不写入仓库外。
- 普通工作区快照不跟随外部链接；链接/junction 记录自身信息或明确拒绝未知类型，不能静默遗漏内容。
- 临时文件与目标同目录；写入并同步后原子替换，区分替换前失败与替换后同步失败，确保可恢复且证据真实。
- Windows 文件占用只做有上限重试；ACL 拒绝、路径非法、磁盘错误不得被当作短暂竞争吞掉。
- 不调用不存在的 fchmod；Windows 权限使用其 ACL/只读属性语义，不能把 chmod(0700) 宣称为 Windows 私有权限保障。
- 不承诺各平台完全一致的断电持久性；明确文件同步和目录元数据同步能力，缺失影响既定安全要求时阻止写入而非假成功。

### 3. 全链路接入与兼容

生命周期、调度、任务状态、Doctor、快照统一接入同一安全层，清除业务脚本对父目录描述符的直接依赖，包括异常清理路径。保持现有 CLI 参数、审批门禁、CAS、调度所有权及中英状态展示。

新增 Windows 路径测试：中文和空格、反斜杠、盘符大小写、跨盘越界、保留设备名、ADS、尾点/尾空格、长路径与受控长路径失败。磁盘根目录/网络路径不能与相对任务作用域混淆。未验证的网络文件系统必须明确能力限制，不默认承诺跨系统共享目录并发安全。

安装器优先解析可信原生 codex 可执行入口；兼容受支持的 Windows 启动方式，使用正确的参数编码并测试 shell 元字符，禁止把任意路径拼入 shell 命令。子进程统一使用当前 Python 解释器；文档分别给出 PowerShell 和 POSIX 命令，不要求所有系统都存在 python3。

中文/英文文档保持 UTF-8；终端不支持 Emoji 时不得因输出编码导致操作半成功或 traceback，重定向输出与 JSON 必须可解析。

### 4. 状态兼容与迁移矩阵

| 现有状态 | 升级处理 |
| --- | --- |
| v0.4 未迁移计划 | 继续兼容读取/执行；只有显式命令才迁移双状态 |
| v0.5 待开始/进行中/已完成任务 | 保留原枚举、证据与版本；更换 I/O 后端不重置进度 |
| 已批准计划 | 保留审批原文及修订绑定，不能隐式重批 |
| 多智能体待分配/预留/活动/完成状态 | 保留任务身份和运行绑定；跨主机失联不伪造活动 Worker，按已有恢复协议处理 |
| 仍被持有的旧锁 | 不强制删除；要求旧进程退出后升级，不允许混用不互通的锁后端 |
| 无 Git 已有基线 | 同环境保持摘要和比较语义；跨系统模式/身份差异明确诊断，不能隐式覆盖基线 |
| 损坏 JSON/未知 schema/未来版本 | 稳定拒绝，不覆盖原文件 |
| 迁移/替换中断 | 原数据完整或新数据完整；多文件状态不一致可诊断并受控恢复，不能标记验收通过 |
| 重复执行/重启 | 幂等迁移、渲染与恢复，CAS 冲突不盲目重试 |

尽量不变更持久化 schema。若安全实现必须新增持久字段或改变基线含义，先说明迁移和回滚影响并修订方案。

## 验证与发布门禁

目标是 Windows 10/11 原生常规用户环境的完整功能；CI 使用真实 Windows runner，明确其系统版本与客户桌面版本的区别，并保留客户目标系统 smoke 验收项。同时回归 macOS 和 Linux。支持的 Python 下限以实现前兼容检查确定并公开，至少包含现有 3.9 基线和当前主流 Python 3.12；不得为通过测试无说明提高最低版本。

- Windows 原生进程测试：锁竞争/超时/释放/持锁进程退出、状态 CAS、文件占用、目录替换、junction、权限拒绝、迁移失败恢复。
- 每平台覆盖 GIT 与 NONE 完整生命周期、双语渲染、失败验收不得完成、调度 reserve/activate/complete/release；外部宿主不能运行原生智能体时，明确区分编排 CLI 契约测试与实际宿主验证。
- Windows 安装/更新/失败恢复和安装包内全部资源校验；测试临时配置不得覆盖个人真实配置。
- 不允许整模块 Windows skip 来掩盖核心功能；仅 POSIX 特有设备/权限夹具可说明 N/A，Windows 必须有等价安全测试。
- 新增 Windows/macOS/Linux CI 矩阵和明确的失败门禁。上传代码、运行托管 CI 需要对应 Git 授权；未获授权时完成本地工作但真实 Windows 验收保持未通过，不能先宣告交付。
- 性能：记录相同任务集上的前后耗时及 Windows 绝对耗时；不引入无界扫描、每次启动外部 shell、无上限等待或重试。

## 部署、回滚与边界

生产升级需停止旧版活动写者，备份用户计划与内部状态，再更新插件并在新任务中验证。默认不批量迁移客户计划。回滚代码使用已记录 Git 基线的逐文件差异；恢复状态使用升级前副本，不以文件哈希充当备份。

本次不包含客户生产数据操作、第三种语言、改变审批规则、自动合并 PR、发布 tag 或本机重装。提交、推送及运行托管 CI 的授权分别记录；先前 v0.5.0 的发布授权不沿用到本次修复。

## 技术依据

- [Microsoft LockFileEx](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-lockfileex)：锁竞争及进程退出释放语义。
- [Microsoft CreateFileW](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)：共享模式、目录句柄和 reparse point 打开行为。
- [Python os](https://docs.python.org/3/library/os.html)：平台能力与描述符相对接口的差异。
- [CPython subprocess 文档](https://github.com/python/cpython/blob/main/Doc/library/subprocess.rst)：Windows 命令包装器与参数安全。
