---
name: index
description: Use an approval-gated, repository-persisted workflow with optional active native-agent scheduling only when the user explicitly invokes Project Workflow, approves or resumes an existing Project Workflow plan, or requests a materially complex software change involving architecture, migrations, multiple modules or services, staged rollout, compatibility, rollback, security-sensitive behavior, or long-running coordinated implementation. Do not use for routine localized edits, small bug fixes, ordinary CRUD, mechanical refactors, documentation, tests, formatting, or requests that merely involve several steps or ask for a lightweight plan.
---

# Project Workflow Router

## Admission Gate

Accept this workflow when any condition is true:

1. The user explicitly invokes Project Workflow by name, invokes `$project-workflow:index`, or asks for its durable approval-gated workflow.
2. The user approves, revises, or resumes an existing persisted Project Workflow plan.
3. The task has at least one hard trigger:
   - architecture or public contract change;
   - database, data, infrastructure, or deployment migration;
   - security, authorization, payment, privacy, or data-loss risk;
   - staged rollout, compatibility, backfill, or rollback requirements.
4. The task has at least two complexity signals:
   - spans multiple modules, services, or repositories;
   - requires meaningful design tradeoffs or coordination across boundaries;
   - has multiple independently verifiable deliverables;
   - is likely to span multiple tasks, sessions, or handoffs;
   - requires durable audit, acceptance, recovery, or delivery records.

Do not accept merely because a task has several implementation steps or the user requests a lightweight plan. When none of the conditions applies, continue with the normal lightweight engineering workflow without creating workflow documents or state. When uncertain, default to not using this workflow; do not ask the user whether a routine task is complex solely to decide whether to activate it.

## Accepted Workflow Ownership

Only after the admission gate accepts the task, own project planning, approval, phase transitions, native-agent scheduling, execution coordination, and delivery state. Allow other skills to provide specialized capabilities, but do not let them skip approval, change the active phase, start implementation early, or independently create a competing agent topology.

Read [workflow-protocol.md](../../references/workflow-protocol.md) before routing. Load exactly one focused skill for the current turn. Do not perform the focused skill's work in this router.

## Select Workflow Profile

Every newly created plan must persist one workflow profile. The approval gate applies to all profiles.

- `LIGHT`: the user explicitly invoked Project Workflow for a localized, low-risk change. Use one consolidated plan, coordinator-only execution by default, basic regression, and a concise delivery summary. Do not use LIGHT for a hard admission trigger.
- `STANDARD`: use for multi-module or independently verifiable work without migration, security, compatibility, or data-loss risk. Require a separate design and plan, applicable boundary coverage, and native workers only when the expected critical-path benefit exceeds coordination cost.
- `FULL`: use for every hard admission trigger, long-running coordinated work, or any material uncertainty about safety. Require adversarial boundaries, recovery and rollback evidence, an independent contract verifier, and a migration state matrix whenever persisted state evolves.

Treat a historical plan without `workflow_profile` as `FULL`. Do not silently weaken an existing plan. A profile change after approval is material re-planning and requires a new revision and renewed confirmation.

## Route

1. Route to [plan](../plan/SKILL.md) when:
   - no durable plan exists;
   - the plan is `DRAFT` or `AWAITING_CONFIRMATION` and the user requests changes;
   - a material requirement or architecture change invalidates an approved plan;
   - the user asks for a specification, design, implementation plan, or re-plan.
2. Route to [execute](../execute/SKILL.md) only when:
   - the current user message explicitly approves a named or clearly identified persisted plan; or
   - a persisted plan already contains a valid approval record and the user asks to resume or continue it.

## Explicit Skip

Project Workflow never skips its confirmation gate. If the user explicitly declines Project Workflow planning or asks to skip that gate, exit this workflow and handle the request under the normal applicable workflow; do not continue under Project Workflow semantics. Phrases such as "implement this", "finish everything", "go ahead", or "do it in one pass" do not pre-approve a plan that does not exist yet.

## Isolation

- Load either `plan` or `execute`, never both in one turn.
- Do not invoke another general planning or project-execution skill after this workflow owns the task.
- Follow higher-priority runtime instructions and explicit user skill choices. Record any resulting workflow deviation in the durable plan.
