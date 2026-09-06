# Native platform operation / 原生跨平台运行

## Validation status / 验证状态

The Windows compatibility work is under acceptance on `feature/010-windows-support`,
not a released all-platform guarantee. Target desktops are Windows 10/11. CI runs
Windows Server 2022 with CPython 3.9 and 3.12, Ubuntu 24.04 with 3.9 and 3.12, and
macOS 14 with 3.12. Passing server CI does not replace customer desktop and native
agent-host acceptance. Consult the repository's current delivery evidence before rollout.

Windows 兼容改造仍在专用分支验收，不能把当前正式版本解释为全平台可用。
目标是 Windows 10/11；CI 的 Windows Server 2022 结果必须与客户桌面、
真实智能体宿主验收分开记录。CPython 最低版本为 3.9；不承诺未验证解释器实现。

## Commands / 命令

Run from the extracted/cloned repository root. These examples use a native Python
launcher and the source plugin path; installed-plugin scripts use their actual discovered path.
Execute only the installation action the user requested. Installation updates local configuration.

从源码仓库根目录执行；安装后的脚本使用实际发现的插件路径，不写死缓存版本。
安装会改变本机配置，只有用户要求安装/更新时才执行。

PowerShell:

```powershell
py -3 --version
py -3 plugins/project-workflow/scripts/project_workflow_doctor.py --repo . --json
py -3 scripts/install_local_plugin.py --help
py -3 scripts/check_platform.py
```

macOS / Linux:

```bash
python3 --version
python3 plugins/project-workflow/scripts/project_workflow_doctor.py --repo . --json
python3 scripts/install_local_plugin.py --help
python3 scripts/check_platform.py
```

If `py` is unavailable, use a verified `python` executable. Windows native `.exe`
and the official npm Codex wrapper layout are supported by the local installer;
official wrappers are resolved to their Node entry point without executing a shell.
Arbitrary `.bat`, `.cmd`, and `.ps1` launchers are rejected. Paths may contain spaces
or Chinese characters; quote each argument. Do not concatenate user paths into shell commands.

缺少 `py` 时可使用已确认版本的 `python`。安装器可识别原生 `.exe` 与官方 npm
Codex 包装器布局；后者直接调用 Node 入口，不执行包装器 shell。
任意自定义 `.bat/.cmd/.ps1` 会被拒绝。中文与空格路径逐参数加引号。

## Safety and recovery / 安全与恢复

- Windows secure state I/O requires a fixed local drive. UNC/network/device paths
  are rejected; cloud sync, network sharing and cross-OS concurrent writers are not certified.
  POSIX requires no-follow descriptor-relative operations and filesystem locking.
- State ancestors reject junctions/reparse points; workspace snapshots record supported
  link payloads without following targets and reject unknown types. Device names, ADS,
  trailing dots/spaces and path traversal are not valid state filenames.
- Windows uses inherited ACLs, not POSIX `0700` privacy guarantees. Doctor's writability
  result is advisory; actual writes enforce operating-system access checks. An ACL denial
  is an error, not a reason to request administrator access or disable safety checks.
- File contents are flushed before atomic publication. Windows directory metadata fsync
  is unavailable, so no equivalent sudden-power-loss durability guarantee is claimed.
- Lock acquisition defaults to a finite 30-second timeout. Sharing/lock conflicts during
  publication have bounded retries. Stop conflicting old writers and retry; never remove
  an unknown lock file merely because it exists. Kernel locks release when processes exit.
- Before upgrading, stop old writers and back up plan documents plus internal state.
  Explicit migration is idempotent; no automatic customer-wide migration is performed.
  Roll back code to the prior version and restore its matching pre-upgrade state copy.
  Snapshot hashes are evidence, not recoverable file contents. Do not silently overwrite
  a baseline after changing operating systems.

Windows 仅接受固定本地磁盘；UNC、网络共享、设备路径不支持，云同步和跨系统
并发写者未经认证。内部状态拒绝 junction/重解析点，不关闭路径保护。
Windows 使用继承 ACL，不把 `chmod(0700)` 当成隐私保障；Doctor 可写性仅作提示，
实际写入以系统权限检查为准，不建议靠管理员运行掩盖权限问题。

文件内容同步后再原子发布；Windows 不提供本实现所需的目录元数据 fsync，
因此不承诺与 POSIX 完全一致的断电持久性。锁默认最多等待 30 秒，占用重试有上限。
升级前停止旧写者并备份计划及内部状态；回滚须恢复匹配的代码和升级前状态副本。
不要删除未知锁，也不要把快照哈希当备份或跨系统后自动重建基线。
