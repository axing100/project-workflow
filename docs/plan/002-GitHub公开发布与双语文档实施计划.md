---
workflow: "project-workflow/v1"
plan_id: "project-workflow-github-public-release"
revision: 1
phase: "IN_PROGRESS"
approved_revision: 1
approved_at: "2026-08-20T05:43:37+00:00"
confirmation_record: "同意，开始执行"
---

# Project Workflow GitHub 公开发布与双语文档实施计划

- 设计文档：[002-GitHub公开发布与双语文档设计](../design/002-GitHub公开发布与双语文档设计.md)
- 执行方式：单代理串行执行
- 目标远程：`https://github.com/axing100/project-workflow.git`
- 目标分支：`main`
- 仓库可见性：Public
- 提交授权：已由用户请求公开上传；待计划确认后生效
- 推送授权：仅限本次验证后的初始提交推送到 `origin/main`；待计划确认后生效

## 一、基线

- 本地分支：`main`，尚无提交。
- 本地文件：全部未跟踪，无远程地址。
- 插件版本：`0.1.0`，本机状态为 `installed, enabled`。
- 当前许可证：MIT。
- 当前 README：仅英文。
- GitHub CLI：已安装于 `/opt/homebrew/bin/gh`。
- GitHub 账户：`axing100`，当前认证令牌无效。
- 远程同名仓库：公开搜索未发现可靠结果；认证恢复后必须通过 GitHub API 再次确认。
- 已有回归：状态机 7 项测试通过，三个技能与插件 validator 通过。

## 二、任务

### T01 更新双语介绍和许可证

- 状态：[x]
- 目标：提供完整中英文介绍，并切换到 Apache License 2.0。
- 范围：`README.md`、`README.zh-CN.md`、`LICENSE`、`.gitignore`。
- 范围外：插件业务逻辑。
- 前置条件：本计划已确认。
- 风险：双语命令不一致、许可证文本不完整。
- 验收标准：
  - [x] 两份 README 互相链接并保持相同章节结构。
  - [x] 两份 README 包含 GitHub 和本地安装方式。
  - [x] `LICENSE` 为完整 Apache License 2.0 文本。
  - [x] `.gitignore` 排除 Python 缓存与 `.DS_Store`。
- 验证：
  - [x] `rg -n "Apache License 2.0|marketplace add axing100/project-workflow" README.md README.zh-CN.md LICENSE` — 关键内容存在。
  - [x] `! find . -name .DS_Store -o -name __pycache__ -o -name '*.pyc'` — 无生成物。
- 证据：中英文 README 均为 143 行且章节一一对应；关键内容扫描通过；生成物扫描为空。

### T02 更新插件公开元数据并回归验证

- 状态：[x]
- 目标：发布 `0.2.0`，声明 Apache-2.0 和公开仓库地址。
- 范围：`plugins/project-workflow/.codex-plugin/plugin.json` 及必要文档记录。
- 范围外：三个技能和状态机行为变更。
- 前置条件：T01。
- 风险：manifest 字段不符合插件校验规则。
- 验收标准：
  - [x] 版本为 `0.2.0`。
  - [x] `license` 为 `Apache-2.0`。
  - [x] `homepage`、`repository` 指向 `axing100/project-workflow`。
  - [x] 测试与所有 validator 通过。
- 验证：
  - [x] `python3 -m json.tool plugins/project-workflow/.codex-plugin/plugin.json` — 通过。
  - [x] `python3 -m unittest discover -s plugins/project-workflow/tests -v` — 7 项通过。
  - [x] 三个 `quick_validate.py` 命令 — 全部通过。
  - [x] `validate_plugin.py plugins/project-workflow` — 通过。
- 证据：manifest JSON 解析通过；7/7 单元测试通过；index、plan、execute 和插件 validator 全部通过。

### T03 恢复 GitHub 认证并检查远程目标

- 状态：[x]
- 目标：安全恢复 `axing100` 认证，确认同名仓库不会被覆盖。
- 范围：GitHub CLI 登录状态与 `axing100/project-workflow` 远程检查。
- 范围外：仓库文件修改和推送。
- 前置条件：T02 验证通过。
- 风险：需要用户完成浏览器或设备授权；同名仓库可能已存在其他内容。
- 验收标准：
  - [x] `gh auth status` 显示 `axing100` 登录有效。
  - [x] 确认目标仓库不存在，或为空且安全可用。
  - [x] 不在日志和仓库中暴露令牌。
- 验证：
  - [x] `gh auth status` — 认证成功。
  - [x] `gh repo view axing100/project-workflow --json nameWithOwner,isPrivate,url,defaultBranchRef` — 确认不存在。
- 证据：GitHub CLI 显示 `axing100` 为有效活动账户；API 明确返回目标仓库不存在，可安全创建。

### T04 创建初始提交并发布公开仓库

- 状态：[~]
- 目标：创建公开 GitHub 仓库并推送经过验证的 `main`。
- 范围：当前仓库全部预期交付文件、Git 初始提交、`origin/main`。
- 范围外：Tag、Release、强制推送和其他远程。
- 前置条件：T03。
- 风险：误提交敏感信息或推送到错误目标。
- 验收标准：
  - [ ] 敏感信息与生成物检查无命中。
  - [ ] 初始提交只包含预期文件。
  - [ ] `origin` 精确指向 `https://github.com/axing100/project-workflow.git`。
  - [ ] 远程仓库为 Public，`main` 推送成功。
- 验证：
  - [ ] `git status --short` — 提交前范围已审查，提交后为空。
  - [ ] `git remote get-url origin` — 精确匹配目标。
  - [ ] `git rev-parse HEAD` 与 `git ls-remote origin refs/heads/main` — SHA 一致。
  - [ ] `gh repo view axing100/project-workflow --json isPrivate,url` — `isPrivate=false`。
- 证据：待执行。

### T05 刷新本机插件并交付

- 状态：[ ]
- 目标：让本机 Codex 获取更新版本，并记录公开地址和回滚方式。
- 范围：插件 cachebuster、本机重新安装、交付报告、计划状态。
- 范围外：修改已推送的公开版本为本机 cachebuster。
- 前置条件：T04。
- 风险：本地缓存仍指向旧版本，或 cachebuster 意外进入远程提交。
- 验收标准：
  - [ ] 使用官方辅助脚本生成单个本机 cachebuster 并重新安装。
  - [ ] 安装后源码 manifest 恢复为公开提交的 `0.2.0`。
  - [ ] Git 工作树保持干净，远程不包含本机 cachebuster。
  - [ ] 交付报告包含 GitHub URL、提交 SHA、测试和安装结果。
- 验证：
  - [ ] `codex plugin list` — 插件为 `installed, enabled`。
  - [ ] `git status --short` — 为空。
  - [ ] `git diff origin/main...HEAD` — 无差异。
- 证据：待执行。

## 三、测试与质量清单

### 计划就绪

- [x] 目标、范围、范围外、假设和成功标准明确。
- [x] 已检查本地 Git、插件版本、许可证、README 和 GitHub CLI 状态。
- [x] 已考虑公开仓库覆盖、凭据泄露、许可证不可撤销和本地缓存风险。
- [x] 每项任务包含范围、前置条件、验收标准与验证命令。
- [x] 提交与推送目标已限定为 `axing100/project-workflow` 的 `main`。
- [x] 设计和计划已交叉链接，用户已确认 revision 1。

### 执行检查

- [x] 重读已确认设计、计划和适用规则。
- [x] 一次只有一个任务处于 `[~]`。
- [x] 保留无关用户文件，不执行强制推送。
- [ ] 提交前检查凭据、绝对路径、生成物和文件范围。
- [x] 先运行单元测试和 validator，再提交和推送。
- [ ] 公开仓库状态、远程 SHA、本地 Git 和交付报告一致。

## 四、确认记录

- 计划确认：用户已确认 revision 1，原文为“同意，开始执行”。
- 确认时间：`2026-08-20T05:43:37+00:00`。
- 公开仓库创建授权：已生效，仅限 `axing100/project-workflow` Public 仓库。
- 提交授权：已生效，仅限本计划交付文件。
- 推送授权：已生效，仅限 `origin/main`，禁止强制推送。
