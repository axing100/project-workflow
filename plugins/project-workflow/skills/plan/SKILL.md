---
name: plan
description: Create or revise durable repository-backed project specifications and implementation plans, then stop for explicit user approval. Use only when routed by the Project Workflow index skill or when the user explicitly invokes this focused skill. Do not implement production code, run implementation steps, or continue into execution in the same turn.
---

# Project Workflow Plan

## Non-Negotiable Gate

This skill is planning-only. Do not modify production code, implement tasks, commit, push, deploy, or invoke the execute skill in this turn. After presenting the plan confirmation request, end the turn immediately.

Read [workflow-protocol.md](../../references/workflow-protocol.md), [execution-checklists.md](../../references/execution-checklists.md), and [multi-agent-orchestration.md](../../references/multi-agent-orchestration.md) completely before writing the plan.

## Inspect

1. Read applicable `AGENTS.md` files and repository conventions.
2. Inspect repository architecture, contracts, tests, Git branch, and working-tree state before making technical claims.
3. Preserve all pre-existing user changes.
4. Ask only questions required to remove material ambiguity; otherwise state concise assumptions and proceed with planning.

## Create Durable Records

Reuse repository conventions. Otherwise create:

- `docs/design/NNN-需求名称设计.md`
- `docs/plan/NNN-需求名称实施计划.md`
- `docs/delivery/NNN-需求名称交付报告.md` only during delivery

The design must include goal, scope, functional and relevant non-functional requirements, technical solution, boundaries, tradeoffs, assumptions, compatibility, security, observability, deployment, and rollback considerations.

The plan must contain YAML frontmatter following the shared protocol and set:

```yaml
workflow: project-workflow/v1
plan_id: stable-project-plan-id
revision: 1
phase: AWAITING_CONFIRMATION
approved_revision:
approved_at:
confirmation_record:
```

Use the bundled state helper to initialize or normalize the frontmatter:

```bash
python3 <plugin-root>/scripts/workflow_state.py init <plan-path> --plan-id <plan-id>
```

For a revision, increment `revision`, clear all approval fields, and return `phase` to `AWAITING_CONFIRMATION`.

## Choose Execution Mode

Choose and persist one execution mode before asking for approval:

- `SINGLE_AGENT`: use when the user requests it, fewer than two tasks are safely agent-eligible, write scopes overlap, requirements are unsettled, or coordination cost exceeds the likely benefit.
- `AUTO_MULTI_AGENT`: the default multi-agent mode when at least two dependency-ready tasks have disjoint literal write scopes and parallel execution has a material benefit.
- `MANUAL_MULTI_AGENT`: use only when the user explicitly specifies agent assignments or asks to control the topology.

Add these plan frontmatter fields:

```yaml
execution_mode: AUTO_MULTI_AGENT
max_workers: 3
agent_topology: SHARED_WORKSPACE
progress_reporting: COMPACT
orchestration_state: .codex/project-workflow/<plan-id>/orchestration.json
```

Choose a conservative `max_workers`; the coordinator also consumes a runtime collaboration slot. In `SINGLE_AGENT`, set `max_workers: 1`, omit `orchestration_state`, and use `agent_topology: coordinator-only`. Treat legacy plans without these fields as `SINGLE_AGENT`.

Default `progress_reporting` to `COMPACT`. Use `DETAILED` only when the user explicitly asks for debug-level workflow output. In compact mode, use user-facing task labels and plain-language phases; do not show raw enum values, runtime agent IDs, canonical `/root/...` task names, plugin cache paths, or state-helper commands.

## Plan Tasks

Break implementation into dependency-aware, commit-sized tasks. For every task record:

- status `[ ]`, `[~]`, `[x]`, or `[!]`;
- goal, scope, exclusions, prerequisites, risks;
- observable acceptance criteria;
- exact validation commands where known;
- dependencies (`Depends-On`) and a literal repository-relative `Write-Scope` without globs;
- `Agent-Eligible`, `Parallel-Group`, and `Planned-Owner` metadata where applicable;
- evidence placeholder.

Keep canonical workflow documents, shared manifests, migrations, generated lockfiles, broad integration edits, and Git operations coordinator-owned unless their ownership is isolated beyond doubt.

For `AUTO_MULTI_AGENT` and `MANUAL_MULTI_AGENT`, create the plugin-owned companion orchestration JSON described by the shared protocol at `.codex/project-workflow/<plan-id>/orchestration.json`. Include every plan task, set `max_attempts: 2` unless risk requires a lower value, and validate it before requesting approval. Create and update this state only through `orchestration_state.py`; never use a normal file-edit operation for it, link it, or present it as a document the user needs to review:

```bash
python3 <plugin-root>/scripts/orchestration_state.py init <state-path> --plan <plan-path> \
  --task '{"id":"T01","display_name":"user-facing task name","depends_on":[],"write_scope":["literal/path"],"agent_eligible":true}'
python3 <plugin-root>/scripts/orchestration_state.py validate <state-path> --plan <plan-path>
```

Do not create an orchestration JSON for `SINGLE_AGENT`.

Copy applicable quality checklist items into the plan so execution does not depend on this plugin remaining installed.

Record commit and push authorization separately. Both default to not authorized.

## Confirmation Boundary

The initial request cannot approve a plan that has not yet been created. Expressions such as "直接完成", "一口气做完", "go ahead", or "finish it" are not approval of a newly generated plan.

Summarize the parallel tasks, worker cap, coordinator-owned tasks, and fallback behavior in plain language. Do not expose configuration enum names or the internal state path. Approval of this plan authorizes only the recorded in-scope native-agent delegation; it does not authorize commit, push, deployment, destructive actions, or scope expansion.

End with links to the durable design and plan and this intent:

`计划已制定完毕，请确认。确认后将按计划执行；子智能体会显示在 Codex 原生界面中，主会话只汇报开始、异常和最终结果。`

Then end the current turn immediately. Do not call implementation, build, test, deployment, or execution tools after that confirmation request.
