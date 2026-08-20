---
name: plan
description: Create or revise durable repository-backed project specifications and implementation plans, then stop for explicit user approval. Use only when routed by the Project Workflow index skill or when the user explicitly invokes this focused skill. Do not implement production code, run implementation steps, or continue into execution in the same turn.
---

# Project Workflow Plan

## Non-Negotiable Gate

This skill is planning-only. Do not modify production code, implement tasks, commit, push, deploy, or invoke the execute skill in this turn. After presenting the plan confirmation request, end the turn immediately.

Read [workflow-protocol.md](../../references/workflow-protocol.md) and [execution-checklists.md](../../references/execution-checklists.md) completely before writing the plan.

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

## Plan Tasks

Break implementation into dependency-aware, commit-sized tasks. For every task record:

- status `[ ]`, `[~]`, `[x]`, or `[!]`;
- goal, scope, exclusions, prerequisites, risks;
- observable acceptance criteria;
- exact validation commands where known;
- owner only when multi-agent execution is explicitly allowed;
- evidence placeholder.

Copy applicable quality checklist items into the plan so execution does not depend on this plugin remaining installed.

Record commit and push authorization separately. Both default to not authorized.

## Confirmation Boundary

The initial request cannot approve a plan that has not yet been created. Expressions such as "直接完成", "一口气做完", "go ahead", or "finish it" are not approval of a newly generated plan.

End with links to the durable design and plan and this intent:

`计划已制定完毕，请确认。确认后我将开始严格执行，执行过程中不会每步打扰您，仅在遇到阻塞或完成所有任务时汇报。`

Then end the current turn immediately. Do not call implementation, build, test, deployment, or execution tools after that confirmation request.
