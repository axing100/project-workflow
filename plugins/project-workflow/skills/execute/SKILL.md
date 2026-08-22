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

## Select Execution Path

Read [multi-agent-orchestration.md](../../references/multi-agent-orchestration.md) completely before selecting the path.

- Treat legacy plans without `execution_mode` as `SINGLE_AGENT`.
- Execute `SINGLE_AGENT` plans serially as the coordinator.
- For `AUTO_MULTI_AGENT` or `MANUAL_MULTI_AGENT`, require the companion orchestration state to validate against the approved plan ID and revision. A missing, invalid, cyclic, or revision-mismatched state is a blocker, not permission to improvise delegation.
- Use only native Codex collaboration agents so workers appear in the current task's agent UI. Do not simulate agents with subprocesses, direct model APIs, background shells, or user-owned tasks.
- If native collaboration tools or runtime slots are unavailable, record the reason and continue coordinator-owned work serially when safe. Do not silently change the persisted execution mode.
- Follow the persisted `progress_reporting` mode. Default legacy plans to `COMPACT`; use `DETAILED` only when the user explicitly requested debug-level workflow output.

## Compact Progress Experience

In `COMPACT` mode, let the Codex native agent UI carry per-worker lifecycle state:

- Before a wave, send one short message naming the user-facing tasks being started. Do not separately announce every successful spawn or handoff.
- While work continues, provide only occasional aggregate progress required to keep the user oriented. Report retries, fallback, blockers, scope changes, or other actionable exceptions immediately.
- Coalesce fast state changes and describe only the current state; never publish commentary that is already stale relative to the native agent UI.
- Use business task labels such as `后端接口` rather than runtime identities. Do not expose raw workflow enums, task IDs unless needed for disambiguation, canonical `/root/...` names, runtime agent IDs, internal JSON paths, plugin cache paths, or helper commands.
- At completion, lead with the delivered behavior and primary files, then validation. Put design, plan, state, and delivery records in a secondary `过程记录` group only when useful; never list internal orchestration JSON.

In `DETAILED` mode, lifecycle and diagnostic details may be expanded, but native runtime IDs and internal state remain omitted unless the user specifically requests them.

## Execute

For each dependency-ready task in `SINGLE_AGENT` mode or coordinator fallback:

1. Mark exactly one task `[~]` in single-agent mode.
2. Implement the smallest change satisfying the task.
3. Add or update tests proportional to behavior and risk.
4. Run narrow checks first, then affected-module regression.
5. Diagnose, fix, and rerun failures until acceptance criteria pass or a genuine blocker remains.
6. Record paths, commands, results, deviations, and authorization evidence.
7. Mark `[x]` only when acceptance criteria and Definition of Done pass.
8. Continue without routine approval requests.

When a companion state exists, claim coordinator work before editing and complete it with evidence afterward:

```bash
python3 <plugin-root>/scripts/orchestration_state.py assign <state-path> <task-id> --plan <plan-path> --owner coordinator --coordinator
python3 <plugin-root>/scripts/orchestration_state.py complete <state-path> <task-id> --plan <plan-path> --evidence <evidence>
```

## Active Multi-Agent Scheduler

An approved `AUTO_MULTI_AGENT` or `MANUAL_MULTI_AGENT` plan is the delegation instruction for its recorded tasks. Do not ask for another routine approval.

Run this coordinator loop until every task is completed or a genuine blocker is recorded:

1. Reconcile the plan, orchestration state, Git diff, and live native-agent roster.
2. Query ready worker tasks with `orchestration_state.py ready <state-path> --plan <plan-path> --agent-only`.
3. In `AUTO_MULTI_AGENT`, spawn workers only when at least two safe candidates can run concurrently; otherwise execute the task as coordinator. In `MANUAL_MULTI_AGENT`, honor `Planned-Owner` even when only one worker task is ready.
4. Cap workers by ready-task count, plan `max_workers`, and available native collaboration slots.
5. Announce the worker wave once with user-facing task labels. Use deterministic native task names internally.
6. Persist `assign` to reserve each worker slot as `WORKER_PENDING`, then immediately call the native Codex spawn capability. A reservation is not a running worker and must not be reported as one.
7. On successful spawn, persist `activate` with the exact runtime agent ID and canonical task name returned by Codex. Only this transition creates `assignment_kind=WORKER`; rely on the native agent UI rather than duplicating a per-worker start message in compact mode.
8. If spawning fails, persist `release --spawn-failed`, announce the reason and serial fallback, and never fabricate a worker identity or completion record.
9. Give each worker a bounded prompt containing task ID, goal, prerequisites, exact write scope, exclusions, acceptance criteria, validation commands, relevant conventions, and the required handoff format.
10. Monitor with native list/wait capabilities. Verify each handoff against the runtime agent ID, diff, scope, tests, and acceptance criteria; do not announce routine handoff arrival in compact mode and never trust a completion claim alone.
11. Allow one focused correction when useful. Otherwise release and reassign, take over as coordinator, or mark the task blocked. Do not exceed `max_attempts`; announce retries and ownership changes.
12. Persist worker `complete` only with the same runtime agent ID recorded by `activate`, update the durable plan, then schedule the next ready wave without exposing raw phase transitions in compact mode.
13. Interrupt a worker immediately for out-of-scope writes, scope conflict, destructive behavior, or a material change requiring re-planning.

Use this two-phase runtime binding sequence for every native worker:

```bash
python3 <plugin-root>/scripts/orchestration_state.py assign <state-path> <task-id> --plan <plan-path> --owner <task-name>
# Call native spawn_agent here and capture its returned agent ID and canonical task name.
python3 <plugin-root>/scripts/orchestration_state.py activate <state-path> <task-id> --plan <plan-path> --runtime-agent-id <agent-id> --runtime-task-name <canonical-task-name>
python3 <plugin-root>/scripts/orchestration_state.py complete <state-path> <task-id> --plan <plan-path> --runtime-agent-id <agent-id> --evidence <evidence>
```

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
5. validate final orchestration consistency with `orchestration_state.py validate <state-path> --plan <plan-path> --final`; do not reuse the execution-only `--require-approval` gate after completion;
6. do not commit or push unless each permission is explicitly authorized and recorded separately.
