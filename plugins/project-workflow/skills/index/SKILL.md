---
name: index
description: Route complex or multi-step software project work through a durable plan, explicit user approval, and confirmed execution. Use for broad engineering changes, architecture work, migrations, cross-module work, long-running implementation, requests to create or revise an implementation plan, approval of a persisted plan, or resuming an interrupted planned project. Do not use for trivial localized edits that do not justify durable project records.
---

# Project Workflow Router

## Critical Ownership

Own project planning, approval, phase transitions, execution coordination, and delivery state once this workflow starts. Allow other skills to provide specialized capabilities, but do not let them skip approval, change the active phase, or start implementation early.

Read [workflow-protocol.md](../../references/workflow-protocol.md) before routing. Load exactly one focused skill for the current turn. Do not perform the focused skill's work in this router.

## Route

1. Route to [plan](../plan/SKILL.md) when:
   - no durable plan exists;
   - the plan is `DRAFT` or `AWAITING_CONFIRMATION` and the user requests changes;
   - a material requirement or architecture change invalidates an approved plan;
   - the user asks for a specification, design, implementation plan, or re-plan.
2. Route to [execute](../execute/SKILL.md) only when:
   - the current user message explicitly approves a named or clearly identified persisted plan; or
   - a persisted plan already contains a valid approval record and the user asks to resume or continue it.
3. Keep the normal lightweight engineering workflow for a trivial, localized change. State the reason briefly. Do not use this exception for cross-module, migration, security-sensitive, architecture, or long-running work.

## Explicit Skip

Treat planning as skipped only when the user explicitly says to skip planning or skip the confirmation gate. Phrases such as "implement this", "finish everything", "go ahead", or "do it in one pass" do not pre-approve a plan that does not exist yet.

## Isolation

- Load either `plan` or `execute`, never both in one turn.
- Do not invoke another general planning or project-execution skill after this workflow owns the task.
- Follow higher-priority runtime instructions and explicit user skill choices. Record any resulting workflow deviation in the durable plan.
