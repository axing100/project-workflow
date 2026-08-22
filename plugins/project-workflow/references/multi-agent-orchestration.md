# Multi-Agent Orchestration

Use these rules for multiple Codex instances, subagents, or other coding agents. Runtime safety, permission, and user-authorization rules always take precedence.

## Execution Modes

- `AUTO_MULTI_AGENT`: after approval, proactively use native runtime collaboration tools when at least two dependency-ready tasks can progress safely. Do not wait for an additional delegation request.
- `SINGLE_AGENT`: never create workers for this plan.
- `MANUAL_MULTI_AGENT`: create only the workers and assignments explicitly named in the approved plan.

Use native Codex subagent or collaboration tools so the host can expose its normal agent UI and lifecycle. Do not simulate native workers with shell processes, direct API calls, background scripts, or user-owned threads. If native tools are unavailable, record the limitation, tell the user that the affected task is falling back to coordinator execution, and fall back to `SINGLE_AGENT`.

## Activation and Topology

1. Use multiple agents only when the approved execution mode permits them and at least two tasks are independent enough to progress concurrently. Approval of an `AUTO_MULTI_AGENT` plan is the delegation authorization for its recorded scopes.
2. Identify the execution topology before delegation:
   - Shared workspace: agents see the same files immediately.
   - Isolated branch or worktree: each agent produces a diff, patch, or explicitly authorized commit for later integration.
   - Remote or external agent: exchange patches, commits, or structured handoffs.
3. Record the topology, coordinator, workers, task owners, write scopes, branches or worktrees, and integration order in the plan.
4. Keep sequential work when tasks share files, depend on unsettled interfaces, require the same mutable environment, or would cost more to coordinate than to execute.

## Durable Task State

Use a companion `project-workflow/orchestration/v1` JSON document for multi-agent plans. Store new state at `.codex/project-workflow/<plan-id>/orchestration.json`; it is internal plugin state rather than a user-facing plan artifact. Create and mutate it only through the bundled helper so it does not appear as a normal edited deliverable. Existing plan-linked state paths remain readable. Every task records:

- `id`, `status`, `depends_on`, `write_scope`, and `agent_eligible`;
- `owner`, `assignment_kind`, `started_at`, `attempts`, `evidence`, and `block_reason`;
- `runtime_agent_id`, `runtime_task_name`, `spawn_status`, `spawned_at`, `finished_at`, and `runtime_verification`;
- optional `parallel_group`, `planned_owner`, and `branch_or_worktree`.
- `display_name`, a short user-facing task label distinct from internal runtime identity.

`MANUAL_MULTI_AGENT` tasks are agent-eligible only when `planned_owner` is non-empty. The runtime assignment must match it. The default `max_attempts` is 2 unless the approved plan records a smaller positive limit.

Valid task states are `PENDING`, `ASSIGNED`, `COMPLETED`, and `BLOCKED`. Legal transitions are:

```text
PENDING -> ASSIGNED
PENDING -> BLOCKED
ASSIGNED -> PENDING     (release)
ASSIGNED -> COMPLETED
ASSIGNED -> BLOCKED
BLOCKED -> PENDING      (release after resolution)
```

Use the bundled orchestration helper for validation and every state change. The Markdown plan remains the human-readable canonical plan; the companion JSON is the deterministic scheduler state and must use the same task IDs and revision.

Use `assignment_kind=WORKER_PENDING` only for a reserved slot awaiting native spawn, `assignment_kind=WORKER` only after the native runtime returns an agent ID and canonical task name, and `assignment_kind=COORDINATOR` for serial coordinator work. Pending and active workers consume `max_workers`; coordinator assignments do not, but their write scopes still conflict with active workers. A worker cannot complete unless its handoff matches the bound runtime agent ID. Historical completed Worker records without runtime identity remain readable only as `runtime_verification=UNAVAILABLE`; never invent IDs for them.

## Scheduler Loop

1. Validate plan approval and companion state.
2. Reconcile existing workers and partial working-tree changes after any interruption.
3. Query dependency-ready tasks from the state helper.
4. Exclude tasks that are not agent-eligible, touch coordinator-only paths, or overlap an active write scope.
5. Compute worker count as the minimum of the approved `max_workers`, available runtime worker slots, and safe ready tasks.
6. In compact mode, announce the wave once using `display_name` labels; do not expose internal worker names or scopes unless they affect the user.
7. Persist a `WORKER_PENDING` reservation, call the native spawn capability, then bind its returned agent ID and canonical task name with `activate` before treating it as a Worker.
8. If creation fails, release with `--spawn-failed`, announce the failure and fallback, and do not record a fake Worker.
9. Let the native agent UI expose each successful worker start; do not duplicate per-worker start commentary in compact mode.
10. Wait for worker handoffs while continuing only non-conflicting coordinator work; verify routine handoffs silently in compact mode.
11. Inspect the runtime identity, handoff, diff, tests, and actual write scope before recording completion with the same agent ID.
12. Announce retries, ownership changes, fallback, and blockers. Translate phase changes into plain-language aggregate progress only when they materially help the user, then advance until all tasks are completed or a genuine blocker remains.

Do not create workers merely to fill capacity. Prefer serial execution when only one task is ready or coordination cost exceeds likely parallel benefit.

## User-Facing Progress

Default to `COMPACT`. The main task should normally contain one wave-start message, actionable exception messages when needed, occasional aggregate progress for long-running work, and one final synthesis. Native agent chips are the primary per-worker status surface.

Do not expose raw workflow enums, canonical task paths such as `/root/...`, runtime agent IDs, plugin cache paths, internal JSON paths, or state-helper commands. Do not narrate transient states that may become stale before the message renders. Use `DETAILED` only when the user explicitly asks for workflow debugging.

## Branch and Worktree Naming

1. Follow explicit user instructions and repository naming conventions first.
2. Name branches and worktrees after the business task, not the tool, model, vendor, or worker identity. Do not add prefixes or segments such as `codex`, `claude`, `copilot`, or `agent-1` unless the user or repository explicitly requires them.
3. When no convention exists, use:
   - Branch: `<type>/<task-id>-<short-kebab-slug>`
   - Worktree directory: `<task-id>-<short-kebab-slug>`
4. Choose `<type>` from the repository's established categories; otherwise use `feature`, `fix`, `refactor`, `docs`, `test`, or the neutral fallback `task`.
5. Use the plan task or subtask ID for parallel uniqueness instead of an Agent name. Examples: `feature/007-entitlement-edit`, `fix/T12-token-refresh`, and worktrees `007-entitlement-edit`, `T12-token-refresh`.
6. Keep names concise, filesystem-safe, stable for the task lifetime, and free of credentials, personal data, timestamps without purpose, or implementation details likely to change.
7. If a runtime forces a vendor-prefixed generated name and exposes no naming control, record that limitation before creation and prefer a user-created worktree or another supported execution topology when available.

## Coordinator Responsibilities

- Own the confirmed design, canonical plan, architecture decisions, task graph, and final delivery report.
- Give each worker the task ID, goal, scope, exclusions, prerequisite state, acceptance criteria, validation commands, and links to applicable repository documents.
- Assign one owner per task and one owner per writable file or tightly coupled area at a time.
- Keep credentials, destructive operations, production actions, approvals, integration, and final regression under coordinator control unless explicitly authorized otherwise.
- Keep commit and push authorization under coordinator control. Workers must not infer either permission from task assignment.
- Reconcile worker reports with Git and test evidence before changing canonical task status.
- Do not allow workers to silently change confirmed architecture or scope.
- Persist assignments before spawning workers and persist accepted evidence before treating a task as complete.
- Keep canonical plans, companion state, delivery reports, Git operations, shared manifests, migrations, and central configuration coordinator-owned unless a narrower single-owner exception is recorded.

## Parallel Safety

- Run only dependency-ready tasks in the same execution wave.
- Prevent overlapping write scopes. Shared read-only inspection is allowed.
- In a shared workspace, workers must not perform competing Git operations or edit canonical plan and delivery documents; the coordinator updates them.
- In isolated worktrees or branches, use focused diffs or patches by default. Use focused commits only when the user explicitly authorized commits, and integrate work in dependency order.
- Reserve shared schemas, generated contracts, dependency manifests, migrations, and central configuration for a single owner or a sequential integration task.
- Stop and re-plan when an agent discovers an interface or architecture change that invalidates another active task.

## Progress Model

- Single-agent mode permits exactly one `[~]` task.
- Multi-agent mode permits at most one `[~]` task per active worker.
- Every active task records `Owner`, `Started`, `Write scope`, and optional `Branch/Worktree`.
- Every native Worker records the runtime agent ID and canonical task name returned by Codex. A reservation without them is `WORKER_PENDING`, never `WORKER`.
- A worker completion report does not make a task `[x]`; the coordinator marks completion only after acceptance evidence and integration checks pass.
- Use `[!]` only for a genuine blocker and include impact, attempts, owner, and required resolution.

The default retry policy is one clarification or correction sent to the original worker. If the corrected handoff is still insufficient, release the task and either reassign it once, let the coordinator take it over, or mark it blocked. Never loop retries without a fixed stopping condition.

## Worker Handoff Contract

Require every worker to return:

```markdown
- Task: TNN
- Status: completed / blocked / needs-integration
- Changed paths: exact list
- Behavior: concise summary
- Validation: commands and results
- Commit or patch: patch/diff by default; commit identifier only when explicitly authorized
- Deviations: scope or design differences
- Risks and follow-ups: remaining concerns
```

Reject incomplete handoffs when evidence is insufficient to integrate safely.

## Integration and Verification

1. Inspect each handoff and diff before integration.
2. Resolve conflicts according to the confirmed design, not whichever change landed first.
3. Apply or merge isolated work according to the recorded authorization: patch/diff by default, commit only when authorized.
4. Run task-level checks after integration when isolated work was applied or merged.
5. Run contract and integration checks across boundaries changed by different agents.
6. Run the final regression suite only after all accepted work is integrated.
7. Record integration order, conflict resolutions, commands, results, and residual risks in the canonical plan and delivery report.

Do not report the project complete merely because every worker returned. Completion requires integrated behavior, final checklist completion, and coordinator verification.

## Interruption, Failure, and Re-Planning

- Worker creation failure: release with a `spawn_failed` event, tell the user why, and continue with fewer workers or serial execution.
- Missing worker after restart: inspect its write scope, then release or accept partial work explicitly.
- Overlapping or unexpected writes: stop affected workers and resolve ownership before continuing.
- Shared environment contention: serialize the affected wave.
- Incomplete handoff: request one correction, then apply the bounded retry policy.
- Material requirement, interface, data, security, or architecture change: interrupt affected workers, increment the plan revision, clear approval, regenerate orchestration state, request approval, and stop.
