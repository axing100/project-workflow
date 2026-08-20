# Multi-Agent Orchestration

Use these rules for multiple Codex instances, subagents, or other coding agents. Runtime safety, permission, and user-authorization rules always take precedence.

## Activation and Topology

1. Use multiple agents only when requested or permitted and when at least two tasks are independent enough to progress concurrently.
2. Identify the execution topology before delegation:
   - Shared workspace: agents see the same files immediately.
   - Isolated branch or worktree: each agent produces a diff, patch, or explicitly authorized commit for later integration.
   - Remote or external agent: exchange patches, commits, or structured handoffs.
3. Record the topology, coordinator, workers, task owners, write scopes, branches or worktrees, and integration order in the plan.
4. Keep sequential work when tasks share files, depend on unsettled interfaces, require the same mutable environment, or would cost more to coordinate than to execute.

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
- A worker completion report does not make a task `[x]`; the coordinator marks completion only after acceptance evidence and integration checks pass.
- Use `[!]` only for a genuine blocker and include impact, attempts, owner, and required resolution.

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
