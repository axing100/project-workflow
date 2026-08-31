---
name: execute
description: Validate and execute a durable software project plan that the user has explicitly approved, then test, review, and deliver it. Use only when routed by the Project Workflow index skill after approval or when the user explicitly invokes this focused skill for an already approved plan. Do not create a new plan and silently approve it in the same turn.
---

# Project Workflow Execute

## Entry Gate

Read [workflow-protocol.md](../../references/workflow-protocol.md) and [execution-checklists.md](../../references/execution-checklists.md) completely before any implementation action.

At the beginning and after compaction, restart, handoff, or interruption:

1. Re-read applicable `AGENTS.md`, the durable design, and the durable plan.
2. Run Doctor against the plan and reconcile the current version-control resolution, evidence state, and recorded task state. Inspect Git status only when the approved `resolved_vcs_mode` is `GIT`; in `NONE`, do not run Git commands.
   Inspect and refresh the generated task view through `task_state.py inspect` and
   `task_state.py render`; never hand-edit its controlled Markdown blocks.
3. If the current user message explicitly approves an `AWAITING_CONFIRMATION` plan, atomically record that exact approval and enter execution with:

   ```bash
   python3 <plugin-root>/scripts/workflow_state.py start-execution <plan-path> --confirmation <exact-user-message> --repo <repo-root>
   ```

4. Never call `start-execution` based only on the initial implementation request, an assistant-authored message, an inferred preference, or a generic request that does not clearly approve the persisted plan. The command must fail without partially changing approval fields or phase when any check fails.
   Lifecycle mutations hold a stable plan lock. When ownership may be stale or concurrent, pass the inspected `--expected-revision`, `--expected-phase`, and `--expected-sha256`; a conflict requires reconciliation and must not be blindly retried.
5. When resuming an already `APPROVED` plan, retain its recorded approval and use the same composite command with the exact persisted confirmation text:

   ```bash
   python3 <plugin-root>/scripts/workflow_state.py start-execution <plan-path> --confirmation <persisted-confirmation-record> --repo <repo-root>
   ```

6. When the plan is already `IN_PROGRESS` or `BLOCKED`, resume through the canonical gate without replaying approval:

   ```bash
   python3 <plugin-root>/scripts/workflow_state.py resume <plan-path> --repo <repo-root>
   ```

   `BLOCKED` resumes only after approval, revision, version-control, and rollback checks pass. Do not use the low-level `transition` command to bypass this gate.
7. Stop when validation fails. Do not repair a missing approval by approving the plan yourself. Never begin implementation before the durable phase is `IN_PROGRESS`.
8. Treat a missing `workflow_profile` as `FULL`. Enforce the approved profile's acceptance obligations before scheduling work.
9. Resolve the user-facing experience contract at entry and after every restart, compaction,
   handoff, revision, or resume:

   ```bash
   python3 <plugin-root>/scripts/workflow_state.py experience <plan-path>
   ```

10. When a native current-task title capability such as `set_thread_title` is available, set it
    to the resolved `conversation_title`. Repeat only when the resolved title changed. Title sync
    failure is non-blocking; do not use computer control, shell UI automation, or a separate task
    to rename the conversation.
11. Treat a historical plan without `vcs_mode` as `AUTO`. Require the current resolution to match the persisted `resolved_vcs_mode`; if Git availability or worktree membership changed, stop before new writes and require the environment to be restored or the plan to be revised and re-approved. Never silently change from Git evidence to file-system evidence, or vice versa.
12. In `NONE`, the canonical `start-execution` command creates and approval-binds the immutable internal file-system baseline before it enters `IN_PROGRESS`; do not run a separate raw snapshot create in the normal path. Use the bound baseline for final comparison and write-scope validation. The baseline records change evidence, not recoverable file contents. In `FULL`, require non-empty `rollback_strategy` and `rollback_evidence` plus `rollback_verification: "VERIFIED"`; stop unless Doctor verifies the equivalent rollback source. Apply the same blocker to data migration, security remediation, and potential data-loss work at every profile.

Run the read-only entry check before a lifecycle transition or resume:

```bash
python3 <plugin-root>/scripts/project_workflow_doctor.py --repo <repo-root> --plan <plan-path> --json
```

The lifecycle helper owns the normal `NONE` baseline. Use `create-baseline` only for an approved recovery path; replacement requires the exact existing canonical digest:

```bash
python3 <plugin-root>/scripts/workflow_state.py create-baseline <plan-path> --repo <repo-root> --replace-if-sha256 <existing-baseline-sha256>
```

Use the lower-level snapshot helper only for explicit diagnostics or contract inspection in `NONE`:

```bash
python3 <plugin-root>/scripts/filesystem_snapshot.py create --repo <repo-root> --output .codex/project-workflow/<plan-id>/filesystem-baseline.json --exclude <declared-cache>
python3 <plugin-root>/scripts/filesystem_snapshot.py compare --repo <repo-root> --baseline .codex/project-workflow/<plan-id>/filesystem-baseline.json --write-scope <literal-path>
```

Repeat `--write-scope` and `--exclude` as needed. Exclusions are persisted in the baseline. Raw `create` is create-only; an existing output is rejected unless an explicit `--replace-if-sha256` recovery CAS matches. It prints a compact summary by default; use `--json-details` only for explicit full-manifest output. Out-of-scope changes make `compare` fail; `--report-only` is an explicit diagnostic override. Relative baseline/output paths resolve under the repository root. Use `--scope` only when the approved plan deliberately limits the evidence surface, and `--output` on comparison when durable machine-readable final evidence is required.

## Select Execution Path

Read [multi-agent-orchestration.md](../../references/multi-agent-orchestration.md) completely before selecting the path.

- Treat legacy plans without `execution_mode` as `SINGLE_AGENT`.
- Execute `SINGLE_AGENT` plans serially as the coordinator.
- For `AUTO_MULTI_AGENT` or `MANUAL_MULTI_AGENT`, require the companion orchestration state to validate against the approved plan ID and revision. A missing, invalid, cyclic, or revision-mismatched state is a blocker, not permission to improvise delegation.
- Use only native Codex collaboration agents so workers appear in the current task's agent UI. Do not simulate agents with subprocesses, direct model APIs, background shells, or user-owned tasks.
- Native agent chips and their icons are rendered by Codex. The plugin supplies task names and prompts only; it does not reference or configure image assets for those icons.
- If native collaboration tools or runtime slots are unavailable, record the reason and continue coordinator-owned work serially when safe. Do not silently change the persisted execution mode.
- Follow the persisted `progress_reporting` mode. Default legacy plans to `COMPACT`; use `DETAILED` only when the user explicitly requested debug-level workflow output.
- In `NONE`, use only the shared workspace. Never create a branch or worktree, and never run commit, push, status, diff, or other Git commands. If safe parallel execution depends on worktree isolation, run the affected tasks serially without changing the approved execution mode.

## Compact Progress Experience

In `COMPACT` mode, let the Codex native agent UI carry per-worker lifecycle state:

- Before a wave, send one short message naming the user-facing tasks being started. Do not separately announce every successful spawn or handoff.
- While work continues, provide only occasional aggregate progress required to keep the user oriented. Report retries, fallback, blockers, scope changes, or other actionable exceptions immediately.
- Never allow active execution to remain user-silent longer than the resolved
  `progress_heartbeat_minutes` (five minutes for legacy plans). A stricter runtime update interval
  wins. Bound native waits, command yields, and polling to return before the next heartbeat is due.
- A heartbeat must name the current business phase, completed/total task count, active business
  task labels, and next checkpoint. Include a blocker only when one exists. Do not send a hollow
  “still working” message, duplicate unchanged worker-chip state, or reset the timer with internal
  tool output that the user cannot see.
- Immediate wave starts, material phase changes, retry/fallback notices, blockers, and final
  delivery reset the heartbeat timer. Once a genuine external blocker has been reported and the
  turn is waiting for user input, active-execution heartbeats stop until execution resumes.
- Coalesce fast state changes and describe only the current state; never publish commentary that is already stale relative to the native agent UI.
- Use business task labels such as `后端接口` rather than runtime identities. Do not expose raw workflow enums, task IDs unless needed for disambiguation, canonical `/root/...` names, runtime agent IDs, internal JSON paths, plugin cache paths, or helper commands.
- At completion, lead with the delivered behavior and primary files, then validation. Put design, plan, state, and delivery records in a secondary `过程记录` group only when useful; never list internal orchestration JSON.
- Suppress successful automatic path recovery, corrected internal helper invocations, transient probes, and non-blocking Doctor advice from commentary. Preserve them in task evidence and summarize only material recurring diagnostics at delivery.

In `DETAILED` mode, lifecycle and diagnostic details may be expanded, but native runtime IDs and internal state remain omitted unless the user specifically requests them.

## Execute

For each dependency-ready task in `SINGLE_AGENT` mode or coordinator fallback:

1. Start implementation with `task_state.py start-implementation`; in single-agent mode the helper permits exactly one implementation task in progress.
2. Implement the smallest change satisfying the task.
3. Add or update tests proportional to behavior and risk.
4. Run narrow checks first, then affected-module regression.
5. Diagnose, fix, and rerun failures until acceptance criteria pass or a genuine blocker remains.
6. Record paths, commands, results, deviations, authorization evidence, and mode-appropriate change evidence: Git status/diff for `GIT`, or the file-system comparison and write-scope result for `NONE`.
7. Record implementation completion with evidence, then start verification and record `PASSED`, `PARTIAL`, `FAILED`, `BLOCKED`, or `NOT_APPLICABLE` independently. Implementation completion never implies verification success.
8. Continue without routine approval requests.

Use state transitions instead of editing status text:

```bash
python3 <plugin-root>/scripts/task_state.py start-implementation <plan-path> <task-id> --repo <repo-root>
python3 <plugin-root>/scripts/task_state.py complete-implementation <plan-path> <task-id> --repo <repo-root> --evidence <evidence>
python3 <plugin-root>/scripts/task_state.py start-verification <plan-path> <task-id> --repo <repo-root>
python3 <plugin-root>/scripts/task_state.py pass-verification <plan-path> <task-id> --repo <repo-root> --evidence <evidence>
```

Use `partial-verification`, `fail-verification`, `block-verification`, or
`skip-verification` when those outcomes are accurate. Pass `--expected-version` whenever another
writer may have advanced task state. The final lifecycle command rejects every implementation
state other than `COMPLETED` and every verification state other than `PASSED` or
`NOT_APPLICABLE`.

Run planned `DISCOVERY` validation while new tests or selectors are still being created. Use an `EXACT` selector only after confirming it exists; if a planned selector is stale, recover internally to discovery, record the correction as evidence, and report it only when it changes scope or blocks acceptance.

Apply acceptance depth by profile:

- `LIGHT`: primary path, applicable invalid input, and affected regression.
- `STANDARD`: LIGHT plus selected boundary-matrix dimensions, integration or contract checks where unit tests are insufficient, and coordinator read-only acceptance.
- `FULL`: STANDARD plus adversarial failure and recovery, required migration-state coverage, rollback evidence, and an independent contract verifier isolated from implementation reasoning.

When a companion state exists, claim coordinator work before editing and complete it with evidence afterward:

```bash
python3 <plugin-root>/scripts/orchestration_state.py assign <state-path> <task-id> --plan <plan-path> --repo <repo-root> --owner coordinator --coordinator --expected-version <state-version>
python3 <plugin-root>/scripts/orchestration_state.py complete <state-path> <task-id> --plan <plan-path> --repo <repo-root> --evidence <evidence> --expected-version <state-version>
```

## Active Multi-Agent Scheduler

An approved `AUTO_MULTI_AGENT` or `MANUAL_MULTI_AGENT` plan is the delegation instruction for its recorded tasks. Do not ask for another routine approval.

Run this coordinator loop until every task is completed or a genuine blocker is recorded:

1. Reconcile the plan, orchestration state, mode-appropriate change evidence, and live native-agent roster.
2. Query ready worker tasks with `orchestration_state.py ready <state-path> --plan <plan-path> --agent-only`.
3. In `AUTO_MULTI_AGENT`, spawn workers only when the persisted benefit policy reports at least 20% critical-path savings after coordination cost and safe candidates have disjoint write scopes. Normally require at least two ready candidates; an isolated `CONTRACT_VERIFIER` is the only single-ready-task exception. Otherwise execute as coordinator. In `MANUAL_MULTI_AGENT`, honor `Planned-Owner` even when only one worker task is ready.
4. Cap workers by ready-task count, plan `max_workers`, and available native collaboration slots.
5. Announce the worker wave once with user-facing task labels. Use deterministic native task names internally.
6. Persist `assign` to reserve each worker slot as `WORKER_PENDING`, then immediately call the native Codex spawn capability. A reservation is not a running worker and must not be reported as one.
7. On successful spawn, persist `activate` with the exact runtime agent ID and canonical task name returned by Codex. Only this transition creates `assignment_kind=WORKER`; rely on the native agent UI rather than duplicating a per-worker start message in compact mode.
8. If spawning fails, persist `release --spawn-failed`, announce the reason and serial fallback, and never fabricate a worker identity or completion record. Releasing an activated Worker requires its exact runtime agent ID and durable `--stopped-evidence`; a pending reservation uses only `--spawn-failed`.
9. Give each worker a bounded prompt containing task ID, goal, prerequisites, exact write scope, exclusions, acceptance criteria, validation commands, relevant conventions, and the required handoff format. A contract verifier receives only original requirements, public contracts, and acceptance criteria, never implementation discussion or self-review conclusions.
10. Monitor with native list/wait capabilities using waits bounded by the resolved heartbeat
    deadline. On a heartbeat timeout, report one aggregate business update before waiting again.
    Verify each handoff against the runtime agent ID, diff, scope, tests, and acceptance criteria;
    do not announce routine handoff arrival in compact mode and never trust a completion claim alone.
11. Allow one focused correction when useful. Otherwise release and reassign, take over as coordinator, or mark the task blocked. Do not exceed `max_attempts`; announce retries and ownership changes.
12. Persist worker `complete` only with the same runtime agent ID recorded by `activate`, update the durable plan, then schedule the next ready wave without exposing raw phase transitions in compact mode.
13. Interrupt a worker immediately for out-of-scope writes, scope conflict, prohibited Git activity in `NONE`, destructive behavior, or a material change requiring re-planning.

Use this two-phase runtime binding sequence for every native worker:

```bash
python3 <plugin-root>/scripts/orchestration_state.py assign <state-path> <task-id> --plan <plan-path> --repo <repo-root> --owner <task-name> --expected-version <state-version>
# Call native spawn_agent here and capture its returned agent ID and canonical task name.
python3 <plugin-root>/scripts/orchestration_state.py activate <state-path> <task-id> --plan <plan-path> --repo <repo-root> --runtime-agent-id <agent-id> --runtime-task-name <canonical-task-name> --expected-version <state-version>
python3 <plugin-root>/scripts/orchestration_state.py complete <state-path> <task-id> --plan <plan-path> --repo <repo-root> --runtime-agent-id <agent-id> --evidence <evidence> --expected-version <state-version>
```

All orchestration mutations accept `--expected-version <state_version>` for compare-and-swap updates. Read the current `state_version` with `inspect`; a mismatch fails without writing. Do not retry a stale mutation until state and live workers have been reconciled.

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
3. create or update the delivery report with changed behavior, paths, tests, deployment, rollback, skipped checks, and residual risks. In `NONE`, include the deterministic added/modified/deleted comparison, write-scope result, exclusions, and an explicit statement that hashes do not provide Git-level rollback;
4. validate final orchestration consistency with `orchestration_state.py validate <state-path> --plan <plan-path> --repo <repo-root> --final`; do not reuse the execution-only `--require-approval` gate after completion;
5. after final orchestration validation and acceptance evidence agree with repository state, atomically complete the plan with the repository context. The lifecycle helper holds the plan lock, revalidates the complete companion state under its lock, records the accepted `state_version`, and in current `NONE` plans recomputes the persisted baseline against companion task scopes or `filesystem_write_scopes`; validation failure leaves the plan unchanged:

   ```bash
   python3 <plugin-root>/scripts/workflow_state.py complete <plan-path> --repo <repo-root>
   ```

6. do not commit or push unless each permission is explicitly authorized and recorded separately. Because `NONE` prohibits all Git operations, revise and re-approve the plan to `GIT` before acting on any later commit or push authorization.
