# Execution Checklists

Use these as mandatory quality gates for non-trivial work. Copy applicable items into the repository plan and mark them with evidence. Mark non-applicable items as `N/A` with a reason; do not silently omit them.

## Task Record Template

```markdown
### TNN Task title

- Status: [ ] / [~] / [x] / [!]
- Owner: agent or person; omit only for single-agent work
- Depends-On: task IDs or `none`
- Write-Scope: exact non-overlapping paths or areas
- Agent-Eligible: true / false
- Parallel-Group: optional wave hint
- Planned-Owner: required for agent-eligible MANUAL mode tasks
- Assignment-Kind: runtime `WORKER` or `COORDINATOR`; empty before assignment
- Goal: expected behavior and reason
- Scope: expected modules and paths
- Out of scope: explicit exclusions
- Prerequisites: task IDs or external conditions
- Risks: compatibility, security, data, operations
- Acceptance criteria:
  - [ ] Observable criterion
- Validation:
  - [ ] `exact command` — expected result
- Evidence: changed paths, results, optional authorized commit or patch, deviations
```

## Plan Readiness

- [ ] Goal, scope, out-of-scope items, assumptions, and success criteria are explicit.
- [ ] Existing architecture, contracts, conventions, Git state, and baseline tests were inspected.
- [ ] Security, data migration, compatibility, performance, observability, and rollback were considered where relevant.
- [ ] Tasks are commit-sized, dependencies are explicit, and expected write scopes are identified.
- [ ] Every task has observable acceptance criteria and exact validation commands where known.
- [ ] Historical failures and environmental limitations are recorded separately from expected new results.
- [ ] Commit and push authorization states are recorded separately; both default to not authorized.
- [ ] Design and plan cross-link each other and the user confirmation is recorded.
- [ ] Execution mode, topology, worker limit, delegation authorization, and fallback behavior are explicit.
- [ ] Multi-agent tasks have machine-readable dependencies, write scopes, eligibility, and matching companion state.

## Per-Task Development

- [ ] Re-read the confirmed design, task scope, applicable `AGENTS.md`, and repository conventions.
- [ ] Confirm prerequisites and baseline state before editing.
- [ ] Keep changes within task scope; document necessary deviations before expanding scope.
- [ ] Preserve user changes and avoid unrelated formatting or refactoring.
- [ ] Follow project naming, documentation, API, validation, persistence, cache, locking, scheduling, and dependency conventions.
- [ ] Handle inputs, outputs, errors, boundaries, nullability, authorization, and sensitive data as applicable.
- [ ] Consider transactionality, idempotency, concurrency, compatibility, migration, and rollback where applicable.
- [ ] Add comments only for non-obvious behavior or domain decisions.
- [ ] Review the diff for correctness, accidental changes, secrets, generated artifacts, and maintainability.
- [ ] Do not commit or push unless the plan records the corresponding explicit authorization and scope.
- [ ] Workers never edit canonical plan, orchestration state, delivery records, or coordinator-only paths.

## Per-Task Test and Acceptance

- [ ] Add or update tests proportional to behavior and risk.
- [ ] Cover the primary success path and applicable boundary, invalid-input, failure, authorization, and regression paths.
- [ ] Add integration, contract, UI, migration, concurrency, security, or performance checks when unit tests cannot prove the acceptance criteria.
- [ ] Run the narrowest relevant checks first, then the affected module suite.
- [ ] Run compile, static analysis, formatting, type checking, packaging, or build checks used by the repository.
- [ ] Compare failures with the recorded baseline; do not label a new failure as pre-existing without evidence.
- [ ] Record commands, environment, pass/fail counts, skipped checks, and reasons.
- [ ] Re-run failed checks after fixes and retain the final result.

## Definition of Done

- [ ] Acceptance criteria are satisfied with recorded evidence.
- [ ] Applicable tests and affected-module regression pass, or an explicit blocker is recorded.
- [ ] No known correctness, security, data-loss, or compatibility defect remains in scope.
- [ ] Documentation, configuration examples, migrations, and rollback notes are updated where required.
- [ ] Changed paths and Git state match the task record; no unrelated or generated artifacts were added.
- [ ] Task deviations and follow-ups are documented, and the task status reflects reality.

## Final Delivery

- [ ] All tasks have a terminal state and no unexplained `[~]` item remains.
- [ ] Full regression or the closest feasible substitute was run and recorded.
- [ ] Integration across tasks and agents was reviewed and tested.
- [ ] Runtime workers, companion state, task evidence, and final Git state were reconciled.
- [ ] Final review covers correctness, regression, security, performance, operability, and maintainability.
- [ ] Delivery documentation lists behavior changes, files, tests, configuration, migrations, deployment order, rollback, and skipped checks.
- [ ] Design, plan, delivery report, Git state, and actual implementation agree.
- [ ] No unauthorized commit or push occurred; when not authorized, provide a recommended commit message instead.
- [ ] The final response links the durable documents and reports blockers or residual risks without hiding them.
