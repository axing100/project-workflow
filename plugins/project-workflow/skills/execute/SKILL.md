---
name: execute
description: Validate and execute a durable software project plan that the user has explicitly approved, then test, review, and deliver it. Use only when routed by the Project Workflow index skill after approval or when the user explicitly invokes this focused skill for an already approved plan. Do not create a new plan and silently approve it in the same turn.
---

# Project Workflow Execute

## Entry Gate

Read [workflow-protocol.md](../../references/workflow-protocol.md) and [execution-checklists.md](../../references/execution-checklists.md) completely before any implementation action.

At the beginning and after compaction, restart, handoff, or interruption:

1. Re-read applicable `AGENTS.md`, the durable design, and the durable plan.
2. Inspect Git status and reconcile it with recorded task state.
3. If the current user message explicitly approves an `AWAITING_CONFIRMATION` plan, record that exact approval message with:

   ```bash
   python3 <plugin-root>/scripts/workflow_state.py approve <plan-path> --confirmation <exact-user-message>
   ```

4. Never call `approve` based only on the initial implementation request, an assistant-authored message, an inferred preference, or a generic request that does not clearly approve the persisted plan.
5. Before the first production-code write, run:

   ```bash
   python3 <plugin-root>/scripts/workflow_state.py check-execute <plan-path>
   ```

6. Stop when validation fails. Do not repair a missing approval by approving the plan yourself.
7. Transition the validated plan to `IN_PROGRESS` before implementation.

## Execute

For each dependency-ready task:

1. Mark exactly one task `[~]` in single-agent mode.
2. Implement the smallest change satisfying the task.
3. Add or update tests proportional to behavior and risk.
4. Run narrow checks first, then affected-module regression.
5. Diagnose, fix, and rerun failures until acceptance criteria pass or a genuine blocker remains.
6. Record paths, commands, results, deviations, and authorization evidence.
7. Mark `[x]` only when acceptance criteria and Definition of Done pass.
8. Continue without routine approval requests.

Read [multi-agent-orchestration.md](../../references/multi-agent-orchestration.md) before delegation. Use multiple agents only when the user explicitly requests them or active runtime instructions permit them.

## Re-Approval

When a material requirement, scope, interface, data model, migration, security posture, or architecture change invalidates the approved plan:

1. stop affected implementation;
2. increment `revision` and revise the durable design and plan;
3. clear approval fields and transition to `AWAITING_CONFIRMATION`;
4. explain impact and request approval;
5. end the current turn immediately.

Do not continue affected work until the revised plan is explicitly approved.

## Delivery

After all tasks finish:

1. run full regression or the closest feasible substitute;
2. review correctness, regression, security, performance, operability, and maintainability;
3. create or update the delivery report with changed behavior, paths, tests, deployment, rollback, skipped checks, and residual risks;
4. transition the plan to `COMPLETED` only after delivery evidence agrees with repository state;
5. do not commit or push unless each permission is explicitly authorized and recorded separately.
