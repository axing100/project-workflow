# Project Workflow GitHub 公开发布与双语文档交付报告

## 交付结果

- 公开仓库：https://github.com/axing100/project-workflow
- 默认分支：`main`
- 初始发布提交：`e819269704a1da09dfdf732f0216f34b3bbdc0de`
- 公开版本：`0.2.0`
- 开源协议：Apache License 2.0
- 中文介绍：`README.zh-CN.md`
- 英文介绍：`README.md`

## 交付内容

- 提供中英文双语的用途、技能分工、确认状态流、安装、更新、卸载、限制和贡献说明。
- 将许可证由 MIT 切换为完整 Apache License 2.0 文本。
- 插件 manifest 更新为 `0.2.0`，补充公开仓库、主页和许可证元数据。
- 公开仓库创建为 Public，默认分支为 `main`。
- 本机插件已通过临时 cachebuster 重新安装；源码 manifest 已恢复为干净的 `0.2.0`。

## 验证证据

- `python3 -m unittest discover -s plugins/project-workflow/tests -v`：7/7 通过。
- index、plan、execute 三个技能的 `quick_validate.py`：全部通过。
- `validate_plugin.py plugins/project-workflow`：通过。
- manifest JSON 解析：通过。
- 凭据扫描：未发现 GitHub token、私钥、密码或 secret。
- 生成物扫描：未发现 `.DS_Store`、`__pycache__` 或 `*.pyc`。
- 初始发布后，本地与远程 `main` 均指向 `e819269704a1da09dfdf732f0216f34b3bbdc0de`。
- GitHub API 验证：`isPrivate=false`，默认分支为 `main`。
- 本机安装：`project-workflow@project-workflow-local` 为 `installed=true`、`enabled=true`，缓存版本为 `0.2.0+codex.20260820054922`。
- 源码 manifest：保持 `0.2.0`，临时 cachebuster 不进入公开源码。

## 安装方式

```bash
codex plugin marketplace add axing100/project-workflow
codex plugin add project-workflow@project-workflow-local
```

安装或更新后需要新建 Codex 任务，使技能清单重新加载。

## 回滚方式

- 公开源码回滚：从 Git 历史恢复所需版本并创建普通回滚提交；不得强制改写公开 `main`。
- 本机插件回滚：切换本地 marketplace 源到所需提交，重新执行插件安装，然后新建 Codex 任务。
- 旧的单体技能仍保存在 `<user-home>/.codex/skills-disabled/project-planner-executor-20260820`，未被删除。

## 范围说明

本次只修改和发布独立目录 `<user-home>/IdeaProjects/project-workflow`。业务项目 `<user-home>/IdeaProjects/fgpro-license-platform` 内没有新增插件文件。
