# Windows 完整功能兼容：独立契约验收

- 验收日期：2026-09-05
- 作者：chenjiaxing
- 实现状态：独立黑盒测试与本报告已编写。
- 验收状态：**原生 Windows 总体验收仍未通过**。失败完成门禁缺陷已通过独立黑盒复验关闭；本报告尚无原生 Windows 执行及安装更新证据。

## 独立性与证据边界

仅使用原始需求、README、中英公共参考文档、公开 CLI `--help` 及运行返回的错误说明构造夹具；未导入、阅读生产实现，未阅读实施者自验报告或其他测试。遵循 Project Workflow 的独立验收隔离规则，不修改生产实现、计划或调度状态。所有被测状态均在临时仓库创建并清理。

测试路径：`plugins/project-workflow/tests/test_windows_contract.py`。

执行命令：

```text
python3 -m unittest discover -s plugins/project-workflow/tests -p test_windows_contract.py -v
```

2026-09-05 首次本机 macOS / Python 3 结果：23 个用例，20 通过，1 失败，2 跳过，耗时约 4.18 秒，退出码 1。

收到修复通知后，未阅读实现，先运行原有 23 个测试，结果 21 通过、2 跳过；再补充任务状态丢失边界并完整复跑：**24 个用例，22 通过，0 失败，2 跳过**，耗时约 4.39 秒，退出码 0。两个跳过项分别为原生 Windows junction 输出越界和保留设备名/ADS。这不是 Windows 通过证据，也没有执行本机插件安装或更新。其余原生验证由协调者接管，不把未见证据计为通过。

## 发现问题

### P1（已独立复验关闭）：验收失败后计划仍可完成

复现用例：`test_failed_verification_blocks_completion`。

1. 使用公开 frontmatter 创建 STANDARD / NONE 计划，通过公开 `task_state migrate` 建立任务状态。
2. `start-execution` 记录确认；任务开始实现、完成实现并提供证据。
3. 开始验收，执行 `fail-verification --evidence "contract failed"`。
4. `task_state inspect` 明确包含 `FAILED`。
5. `workflow_state complete` 却返回退出码 0，输出 `completed contract revision 1`。

预期：退出非零，并保持计划原字节不变。首次实际：失败任务仍被认定为计划完成，违反“实现与验收独立记录”和“失败验收不得完成”的交付契约。

复验：保留原断言重跑通过，确认 `FAILED` 后完成返回非零且计划原字节不变。新增 `test_missing_task_state_blocks_completion` 也通过：迁移并开始执行后删除临时工作区的任务状态，完成被拒绝、计划不变、状态不会被重新伪造。本报告只记录黑盒行为，不推断内部根因或采用实现方自验结论。

### P1 验收缺口：尚未证明原生 Windows 完整交付

没有原生 Windows runner 的结果、原生 Codex marketplace 安装/更新记录或真实 Windows 多智能体生命周期证据，不得据 Mac 测试通过宣称生产 Windows 已支持。

### P2 契约能力限制：CLI 身份一致性不等于运行时真实性

独立用例证明预留未激活不能完成、激活后不同 ID 不能完成，但 `activate` 接受测试提供的普通 ID 字符串。该夹具仅测试结构绑定，不代表真实 native worker。README 已说明脚本不是授权安全边界；因此真实 reserve → native spawn → activate → handoff → complete 必须由协调者绑定原生 runtime 返回值并交叉核验，不能以 JSON 或 CLI fixture 代替。若需求被解释为 CLI 本身必须识别所有虚构 ID，现有公共接口不足以证明此能力。

## 已覆盖契约

| 范围 | 独立结果与边界 |
| --- | --- |
| 五个公开 CLI 启动 | Mac 原生 Python 成功 |
| 审批 | 未批准、空确认、旧 revision 均失败且保留计划 |
| 并发 | 六个真实子进程用同一旧摘要竞争，恰好一个成功；不等于穷尽锁实现与杀进程恢复 |
| 任务/调度 CAS | 旧版本拒绝且字节不变 |
| GIT/NONE | 串行批准到通过验收并完成的正向生命周期成功 |
| 失败验收 | 修复后独立复验通过：失败状态阻断完成且计划不变 |
| 任务状态丢失 | 迁移后的状态文件丢失时阻断完成，不补造状态 |
| 身份 | pending completion 拒绝、不同 ID completion 拒绝；真实性仍需 native runtime |
| 损坏/未知状态 | 损坏任务 JSON、未来 schema、未知计划 phase 保留原内容并拒绝覆盖 |
| 快照 | create-only、错误恢复摘要、外部输出、字面量范围越界拒绝 |
| 路径 | Unicode、空格、超过传统 MAX_PATH 总长度的嵌套路径在 Mac 成功 |
| 中英展示 | 两种语言经 migrate 选择后重复 render 幂等 |
| Doctor | NONE 预检成功且不创建内部文件 |

## 原生 Windows 待验与未覆盖项

1. 在原生 Windows Python 执行完整独立测试，不以 WSL、Git Bash 或关闭锁/安全检查替代；保留 OS、Python、文件系统、命令、退出码和日志。
2. Windows junction、设备保留名、ADS 已编写平台专有用例，需实际执行；总长路径用例不得因失败被改为无条件跳过。
3. 真实跨进程长时间争用、持锁进程被终止后的恢复、目录替换与 junction 交换竞态、落盘中断/磁盘写入失败恢复，仍需独立压力/故障注入证据。本测试的 CAS 竞争和错误恢复摘要不覆盖这些故障窗口。
4. Windows 原生 Codex 本地/归档安装、marketplace 更新与失败回滚，须验证配置恢复和重启后技能可用，不能只运行脚本 `--help`。
5. 真实原生多智能体完整生命周期（GIT 与 NONE）、失败 spawn 释放、被中断 worker 的停止证据与重试，须提供 runtime 身份与 handoff 交叉验证；本地 fixture 不构成通过证据。
6. NONE 不调用 Git 的强验证、网络共享/UNC 等未声明路径支持范围、目录替换原子性和既有历史状态全矩阵，本套测试未证明；需协调者依据明确公共支持范围补充独立证据。

结论：测试交付及 Mac 独立复验已完成，原 P1 功能缺陷在本机复验关闭；原生 Windows 产品总体验收仍未通过。不得把 Mac 通过写成 Windows 产品验收通过，也不得把缺少 Windows 证据掩盖为实现未完成。
