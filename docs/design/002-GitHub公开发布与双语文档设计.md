# Project Workflow GitHub 公开发布与双语文档设计

## 文档信息

- 状态：待确认
- 日期：2026-08-20
- 目标仓库：`https://github.com/axing100/project-workflow`
- 可见性：Public
- 实施计划：[002-GitHub公开发布与双语文档实施计划](../plan/002-GitHub公开发布与双语文档实施计划.md)

## 一、背景与目标

当前 `project-workflow` 已在本机完成插件开发、测试和安装，但本地 Git 仓库尚无提交、无远程地址，README 仅为英文，许可证为 MIT。用户要求将插件公开上传到个人 GitHub，并提供中英文双语介绍，改为 Apache License 2.0。

目标是形成一个公开、可安装、可复用的 GitHub 仓库，使其他用户可以直接从 `axing100/project-workflow` 添加 marketplace 并安装插件。

## 二、成功标准

- GitHub 仓库 `axing100/project-workflow` 为公开仓库。
- 默认分支为 `main`，本地与远程初始提交一致。
- `README.md` 提供英文介绍，并链接中文文档。
- `README.zh-CN.md` 提供完整中文介绍，并链接英文文档。
- 两份 README 均包含定位、三技能职责、确认门禁、安装、使用、更新、卸载、分享、限制和回滚说明。
- `LICENSE` 使用完整 Apache License 2.0 文本。
- 插件清单声明 `Apache-2.0`，并补充公开仓库与主页地址。
- 插件版本更新为干净的公开版本 `0.2.0`。
- 单元测试、三个技能验证和插件验证全部通过。
- 本机插件刷新成功，新建 Codex 任务后能加载更新版本。

## 三、范围

### 包含范围

- 更新 `README.md`。
- 新增 `README.zh-CN.md`。
- 将 `LICENSE` 从 MIT 替换为 Apache License 2.0。
- 更新 `.codex-plugin/plugin.json` 的版本、许可证、仓库和主页元数据。
- 新增 `.gitignore`，忽略 Python 缓存和 Mac 常见本地文件。
- 更新交付文档中的公开发布记录。
- 验证插件、提交本地 Git、创建公开 GitHub 仓库并推送 `main`。
- 为公开仓库设置简洁描述和主题标签。
- 按本地插件更新流程刷新安装缓存。

### 范围外

- 不创建 GitHub Release、Tag、GitHub Actions 或自动发布流程。
- 不启用 Issues、Discussions、Pages 等额外仓库功能配置。
- 不修改插件工作流逻辑和状态机行为。
- 不提交凭据、令牌、本机缓存或绝对路径。
- 不强制推送，不覆盖已有远程仓库内容。

## 四、技术方案

### 4.1 双语文档

采用两个独立 README，避免单文件过长：

```text
README.md         # English, links to 中文
README.zh-CN.md   # 中文，链接到 English
```

两份文档保持相同章节结构和命令，README 中的 GitHub 安装方式使用：

```bash
codex plugin marketplace add axing100/project-workflow
codex plugin add project-workflow@project-workflow-local
```

同时保留克隆或解压后的本地路径安装方式。

### 4.2 开源协议

将根目录 `LICENSE` 替换为 Apache License 2.0 官方完整文本，并将插件 manifest 的 `license` 从 `MIT` 改为 `Apache-2.0`。本项目没有第三方源码归属声明，因此本次不创建 `NOTICE`；后续若引入要求保留 NOTICE 的内容，再补充该文件。

### 4.3 插件元数据与版本

将插件版本更新为 `0.2.0`，并补充：

```json
{
  "homepage": "https://github.com/axing100/project-workflow",
  "repository": "https://github.com/axing100/project-workflow",
  "license": "Apache-2.0"
}
```

公开提交保持干净的 `0.2.0`。在本机重新安装时使用 `plugin-creator` 的 cachebuster 脚本生成临时本地版本，安装完成后将源码 manifest 恢复为已提交的 `0.2.0`，避免把本机 cachebuster 发布到 GitHub。

### 4.4 GitHub 发布

目标固定为：

- Owner：`axing100`
- Repository：`project-workflow`
- Visibility：Public
- Default branch：`main`
- Push destination：`origin/main`
- Push range：本次经过验证的初始提交

创建前检查同名仓库：

- 若不存在，创建公开仓库并设置 `origin`。
- 若存在且为空或确认属于本项目，核对后继续。
- 若存在其他内容，不覆盖、不强推，停止并请求用户决定。

建议仓库描述：

`Approval-gated project planning and execution workflow plugin for Codex.`

建议主题：`codex`、`codex-plugin`、`project-management`、`workflow`、`ai-agent`。

### 4.5 认证与安全

本机 `gh` 当前账户为 `axing100`，但令牌无效。执行阶段需通过 `gh auth login -h github.com` 重新认证。认证由 GitHub CLI 安全流程处理，不将令牌输出或写入仓库。

提交前检查：

- 无私钥、API Key、Token 或密码文本。
- README 和插件归档中无开发者本机绝对路径。
- Git 只包含预期文件，无 `.DS_Store`、`__pycache__`、`.pyc`。

## 五、兼容性、风险与回滚

### 兼容性

- Apache-2.0 是标准 SPDX 标识，适合插件 manifest 和 GitHub 许可证识别。
- GitHub marketplace 源使用仓库根目录现有 `.agents/plugins/marketplace.json`。
- 不改变三个技能名称与触发策略，现有使用方式保持兼容。

### 主要风险

- GitHub 登录过期会阻塞创建仓库和推送。
- 同名远程仓库可能已存在，存在覆盖风险。
- 本地插件缓存可能继续使用旧版本，需要 cachebuster 和重新安装。
- 文档双语版本可能漂移，通过相同章节结构降低风险。

### 回滚

- 推送前可在本地修改或重做初始提交，不影响远程。
- 推送后若仅需修正文档，使用新的正常提交，不重写公开历史。
- 本机插件更新失败时，已安装的 `0.1.0` 缓存仍可保留；不删除旧缓存。
- 许可证一旦公开发布，不通过历史重写撤销已授予的版本许可；后续版本可依法调整许可证，但已发布版本仍受原许可约束。

## 六、授权边界

用户已明确要求上传到自己的 GitHub 并允许公开。计划确认后，本任务授权范围为：

- 创建公开仓库 `axing100/project-workflow`；
- 创建包含本项目全部经过验证文件的初始提交；
- 将该提交推送到 `origin/main`；
- 不授权推送到其他仓库、其他分支或执行强制推送。

