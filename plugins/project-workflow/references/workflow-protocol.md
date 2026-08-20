# Workflow Protocol

## Contents

- Ownership and precedence
- State record
- Allowed transitions
- Approval semantics
- Skill isolation
- Recovery and change control

## Ownership and Precedence

After Project Workflow accepts a task, it owns planning, approval, lifecycle transitions, execution coordination, and delivery state for that task. Specialized skills may assist with a bounded format, domain, test surface, or tool, but they must not:

- start implementation while the plan awaits confirmation;
- approve or revise the plan;
- change workflow phase;
- replace the canonical design or plan;
- infer commit, push, deployment, or destructive-operation permission.

System, developer, repository, and explicit user instructions retain their normal precedence. Record any conflict or required deviation in the plan.

## State Record

Store workflow state in YAML frontmatter at the start of the durable plan:

```yaml
---
workflow: project-workflow/v1
plan_id: stable-project-plan-id
revision: 1
phase: AWAITING_CONFIRMATION
approved_revision:
approved_at:
confirmation_record:
---
```

Required fields are `workflow`, `plan_id`, `revision`, `phase`, `approved_revision`, `approved_at`, and `confirmation_record`.

Valid phases are:

- `DRAFT`
- `AWAITING_CONFIRMATION`
- `APPROVED`
- `IN_PROGRESS`
- `BLOCKED`
- `COMPLETED`

## Allowed Transitions

```text
DRAFT -> AWAITING_CONFIRMATION
AWAITING_CONFIRMATION -> APPROVED
APPROVED -> IN_PROGRESS
IN_PROGRESS -> COMPLETED
APPROVED -> AWAITING_CONFIRMATION
IN_PROGRESS -> AWAITING_CONFIRMATION
APPROVED -> BLOCKED
IN_PROGRESS -> BLOCKED
BLOCKED -> IN_PROGRESS
BLOCKED -> AWAITING_CONFIRMATION
```

Do not transition directly from `AWAITING_CONFIRMATION` to `IN_PROGRESS` or `COMPLETED`.

## Approval Semantics

Approval is valid only when a user message explicitly approves an already persisted and identifiable plan. A message may approve by plan link, plan ID, unique feature name, or unambiguous conversational reference.

These do not approve a newly created plan:

- the initial request to implement a feature;
- "do everything", "go ahead", or "finish in one pass" before the plan exists;
- an assistant statement that the user probably agrees;
- prior approval of an older revision;
- approval of a materially different scope.

On valid approval, set `phase=APPROVED`, copy `revision` into `approved_revision`, record an ISO-8601 time, and preserve the exact user message in `confirmation_record`.

## Skill Isolation

- `index` is the only implicitly invokable skill.
- `plan` and `execute` set `policy.allow_implicit_invocation: false` and are loaded only by routing or explicit invocation.
- Load one focused skill per turn.
- Planning turns never load or invoke execution.
- Execution turns may use specialized skills only within the approved task scope.
- Do not combine this workflow with another general project planning or plan-execution skill unless the user explicitly selects the alternative.

## Recovery and Change Control

After any restart, compaction, or handoff, rebuild state from repository documents and Git rather than memory alone.

For a material change:

1. increment `revision`;
2. update the design and plan with impact analysis;
3. clear `approved_revision`, `approved_at`, and `confirmation_record`;
4. set `phase=AWAITING_CONFIRMATION`;
5. request renewed approval and stop.

For a genuine external blocker, use `BLOCKED` and record impact, attempted alternatives, and the exact input or state change required.
