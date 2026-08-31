# Execution Checklists

Use these as mandatory quality gates for non-trivial work. Copy applicable items into the repository plan and mark them with evidence. Mark non-applicable items as `N/A` with a reason; do not silently omit them.

## Task Record Template

```markdown
### TNN Task title

- Implementation status: generated from internal task state
- Verification status: generated from internal task state
- Owner: agent or person; omit only for single-agent work
- Depends-On: task IDs or `none`
- Write-Scope: exact non-overlapping paths or areas
- Agent-Eligible: true / false
- Parallel-Group: optional wave hint
- Planned-Owner: required for agent-eligible MANUAL mode tasks
- Assignment-Kind: `WORKER_PENDING`, runtime-bound `WORKER`, or `COORDINATOR`; empty before assignment
- Runtime-Agent: native agent ID and canonical task name; required only for runtime-bound Workers
- Workflow-Profile: `LIGHT`, `STANDARD`, or `FULL`; historical omission means `FULL`
- Estimated-Minutes: required for agent-eligible automatic scheduling
- Coordination-Minutes: required for agent-eligible automatic scheduling
- Critical-Path: true / false
- Role: optional; use `CONTRACT_VERIFIER` for independent black-box validation
- Independent-Verification: true / false
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

- [ ] Doctor ran before technical planning; blocking findings are resolved and non-blocking findings are recorded as evidence.
- [ ] `workflow_profile` is explicit for a new plan; historical omission is treated as `FULL` without weakening the plan.
- [ ] Goal, scope, out-of-scope items, assumptions, and success criteria are explicit.
- [ ] Existing architecture, contracts, conventions, mode-appropriate change state, and baseline tests were inspected.
- [ ] `vcs_mode` and `resolved_vcs_mode` are explicit for a new plan; historical omission is treated as `AUTO` without rewriting the plan.
- [ ] The selected evidence model is explicit: Git status/diff for `GIT`, deterministic file-system baseline/comparison for `NONE`.
- [ ] `NONE` plans exclude all Git commands and disclose that file hashes identify changes but do not restore content.
- [ ] `FULL` with `NONE` records non-empty `rollback_strategy` and `rollback_evidence` plus `rollback_verification: "VERIFIED"`; migration, security, and data-loss risks block without verified rollback capability.
- [ ] Security, data migration, compatibility, performance, observability, and rollback were considered where relevant.
- [ ] Tasks are commit-sized, dependencies are explicit, and expected write scopes are identified.
- [ ] Every task has observable acceptance criteria and exact validation commands where known.
- [ ] Future or not-yet-discovered tests use `DISCOVERY`; `EXACT` selectors refer only to targets proven to exist.
- [ ] Historical failures and environmental limitations are recorded separately from expected new results.
- [ ] Commit and push authorization states are recorded separately; both default to not authorized.
- [ ] Design and plan cross-link each other and the user confirmation is recorded.
- [ ] Execution mode, topology, worker limit, delegation authorization, and fallback behavior are explicit.
- [ ] `conversation_title` matches the current business task and the heartbeat interval is an integer from 1 to 60 minutes, default 5.
- [ ] Multi-agent tasks have machine-readable dependencies, write scopes, eligibility, and matching internal companion state under `.codex/project-workflow/`.
- [ ] Automatic multi-agent tasks record estimates, coordination cost, critical-path membership, and at least 20% expected savings; Worker count defaults to no more than two.
- [ ] FULL plans include an isolated contract-verifier task; persisted-state changes also include a migration state matrix.

## Per-Task Development

- [ ] Re-read the confirmed design, task scope, applicable `AGENTS.md`, and repository conventions.
- [ ] Confirm prerequisites; in current `NONE`, verify canonical `start-execution` created and approval-bound the immutable baseline before editing.
- [ ] Re-resolve version-control capability and stop on drift from the approved resolution.
- [ ] New plans persist string `rollback_required`; FULL+NONE and every `rollback_required: "true"` path have all three verified rollback fields before execution or resume.
- [ ] Keep changes within task scope; document necessary deviations before expanding scope.
- [ ] Preserve user changes and avoid unrelated formatting or refactoring.
- [ ] Follow project naming, documentation, API, validation, persistence, cache, locking, scheduling, and dependency conventions.
- [ ] Handle inputs, outputs, errors, boundaries, nullability, authorization, and sensitive data as applicable.
- [ ] Consider transactionality, idempotency, concurrency, compatibility, migration, and rollback where applicable.
- [ ] Add comments only for non-obvious behavior or domain decisions.
- [ ] Review the diff for correctness, accidental changes, secrets, generated artifacts, and maintainability.
- [ ] Do not commit or push unless the plan records the corresponding explicit authorization and scope.
- [ ] In `NONE`, do not run Git commands or create branches/worktrees; serialize work that requires worktree isolation.
- [ ] Review the mode-appropriate change evidence; in `NONE`, verify added/modified/deleted paths and literal write-scope compliance from the final file-system comparison.
- [ ] In `NONE`, persist declared exclusions, verify mode changes, and treat out-of-scope comparison as failure unless an explicit report-only diagnostic was requested.
- [ ] Current `SINGLE_AGENT + NONE` plans persist `filesystem_write_scopes`; ordinary baseline creation is create-only, recovery replacement requires the prior digest, and final completion recomputes and binds the comparison rather than trusting a stale report.
- [ ] Workers never edit canonical plan, orchestration state, delivery records, or coordinator-only paths.
- [ ] A native Worker is not reported as started until Codex returns and persists its runtime agent ID and canonical task name.
- [ ] Blocked active Workers retain slot/scope ownership; pending release uses `--spawn-failed`, while active release matches runtime identity and records stopped evidence.
- [ ] Concurrent orchestration mutations use `state_version`/`--expected-version` and reconcile CAS mismatches before retry.
- [ ] Lifecycle mutations hold the stable plan lock; concurrent callers use revision/phase/SHA-256 CAS when stale ownership is possible.
- [ ] Final completion validates every companion task under the scheduler lock and binds the accepted `state_version`; Doctor reuses the same final validator.
- [ ] Compact progress uses one aggregate wave-start message, native worker UI, actionable exception messages, and one final synthesis without raw runtime identities or phase enums.
- [ ] Active execution never exceeds its user-visible heartbeat interval; every heartbeat includes phase, completed/total count, active business labels, and next checkpoint.
- [ ] Native title synchronization uses the current plan title when available and degrades without UI automation when unavailable.
- [ ] Detailed lifecycle output appears only when the user explicitly requested workflow debugging.

## Per-Task Test and Acceptance

- [ ] Add or update tests proportional to behavior and risk.
- [ ] Cover the primary success path and applicable boundary, invalid-input, failure, authorization, and regression paths.
- [ ] Add integration, contract, UI, migration, concurrency, security, or performance checks when unit tests cannot prove the acceptance criteria.
- [ ] Run the narrowest relevant checks first, then the affected module suite.
- [ ] Run compile, static analysis, formatting, type checking, packaging, or build checks used by the repository.
- [ ] Compare failures with the recorded baseline; do not label a new failure as pre-existing without evidence.
- [ ] Record commands, environment, pass/fail counts, skipped checks, and reasons.
- [ ] Re-run failed checks after fixes and retain the final result.

### Boundary Matrix (`STANDARD` / `FULL`)

Select relevant rows and record evidence. Mark an irrelevant row `N/A` with a reason rather than silently omitting it.

- [ ] Type/nullability: null or missing values, booleans accepted as integers, unsupported scalar and container types.
- [ ] Numeric limits: negative, zero, normal upper bound, very large integer, arithmetic or serialization overflow.
- [ ] Collections/identity: empty, duplicate, unknown, large collections, stable ordering, idempotent identity reuse.
- [ ] Time: naive timestamp, non-UTC offset, clock rollback, expiry boundary, duration or timestamp overflow.
- [ ] Retry/atomicity: idempotent retry, failure retry, partial success, crash between writes, duplicate delivery.
- [ ] Error surface: raw internal exception leakage, stable public error, malformed persisted data, recovery failure.
- [ ] Concurrency/recovery: competing writers, lease ownership, stale or missing lease, restart and orphan recovery.

### Migration State Matrix (`FULL` when persisted state evolves)

- [ ] Every old state maps to an explicit new state or documented rejection/quarantine outcome.
- [ ] Active `RUNNING` work defines behavior for valid, missing, expired, and malformed lease metadata.
- [ ] Orphaned work has a bounded recovery owner and cannot remain permanently unclaimable.
- [ ] Unknown or future states fail safely without silent data loss.
- [ ] Repeated migration is idempotent; crash re-entry cannot duplicate effects.
- [ ] Rollback behavior and the point of no return are explicit and tested where feasible.

### Independent Contract Verification (`FULL`)

- [ ] A `CONTRACT_VERIFIER` receives only original requirements, public contracts, and acceptance criteria.
- [ ] Its write scope is limited to independent tests or reports and does not overlap production implementation.
- [ ] It prioritizes black-box boundaries, migration/recovery, and failure cases over implementation-shaped happy paths.
- [ ] Findings return to the implementation owner for repair, then the verifier re-runs acceptance.

## Definition of Done

- [ ] Acceptance criteria are satisfied with recorded evidence.
- [ ] Applicable tests and affected-module regression pass, or an explicit blocker is recorded.
- [ ] No known correctness, security, data-loss, or compatibility defect remains in scope.
- [ ] Documentation, configuration examples, migrations, and rollback notes are updated where required.
- [ ] Changed paths and the selected change-evidence state match the task record; no unrelated or generated artifacts were added.
- [ ] Task deviations and follow-ups are documented, and the task status reflects reality.

## Final Delivery

- [ ] Every task has `COMPLETED` implementation plus `PASSED` or `NOT_APPLICABLE` verification, with evidence.
- [ ] Full regression or the closest feasible substitute was run and recorded.
- [ ] Integration across tasks and agents was reviewed and tested.
- [ ] Runtime workers, companion state, task evidence, and final Git or file-system evidence were reconciled.
- [ ] Every newly completed Worker has `runtime_verification=VERIFIED`; historical `UNAVAILABLE` records are disclosed rather than reconstructed.
- [ ] Final review covers correctness, regression, security, performance, operability, and maintainability.
- [ ] Delivery documentation lists behavior changes, files, tests, configuration, migrations, deployment order, rollback, and skipped checks.
- [ ] Design, plan, delivery report, selected change-evidence state, and actual implementation agree.
- [ ] No unauthorized commit or push occurred; when not authorized, provide a recommended commit message instead.
- [ ] The final response links the durable documents and reports blockers or residual risks without hiding them.
- [ ] Successfully recovered internal paths, helper corrections, and transient probes remain in evidence; only actionable or recurring diagnostics appear in user-facing output.
