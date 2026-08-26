# Workflow Protocol

## Contents

- Ownership and precedence
- State record
- Allowed transitions
- Approval semantics
- Workflow profiles
- Version-control and change-evidence contract
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
workflow_profile: STANDARD
approved_revision:
approved_at:
confirmation_record:
conversation_title: "业务任务名称"
progress_heartbeat_minutes: 5
vcs_mode: AUTO
resolved_vcs_mode: GIT
rollback_required: "false"
---
```

Required fields are `workflow`, `plan_id`, `revision`, `phase`, `approved_revision`, `approved_at`, and `confirmation_record`.

New plans also persist a concise business-facing `conversation_title` and
`progress_heartbeat_minutes` between 1 and 60, defaulting to 5. Historical plans derive the title
from their first level-one heading or plan ID and use the same five-minute default. Resolve the
normalized values through `workflow_state.py experience PLAN`; these fields affect presentation,
not approval validity.

New plans must also record `workflow_profile`. Supported values are `LIGHT`, `STANDARD`, and `FULL`. Historical plans without this field remain valid and are interpreted as `FULL`; do not mutate them only to materialize the default.

New plans must record `vcs_mode` as `AUTO`, `GIT`, or `NONE` and persist the detected `resolved_vcs_mode` as `GIT` or `NONE` before confirmation. Historical plans without `vcs_mode` remain valid and are interpreted as `AUTO`; do not rewrite them merely to add the field.

New plans also persist `rollback_required` as the string `"true"` or `"false"`. Historical plans without it retain profile-based compatibility behavior and are not rewritten merely to add the field.

## Version-Control and Change-Evidence Contract

- `AUTO` resolves to `GIT` only when Git is executable and the repository root belongs to a valid Git worktree; otherwise it resolves to `NONE` without error.
- `GIT` requires both capabilities. Missing Git or an invalid worktree is a blocker.
- `NONE` prohibits every Git command, including status, diff, branch, worktree, commit, tag, and push, even inside a Git repository.

Planning persists the resolved mode. Doctor and the execution entry point resolve it again after approval, restart, compaction, handoff, or resume. A changed resolution is environment drift: stop new scheduling and writes, inspect any existing worker scope with the approved evidence model, and require environment restoration or a revised, re-approved plan. Never silently replace one evidence model with another.

`GIT` uses Git status and diff as its primary change evidence. In `NONE`, canonical `start-execution` creates an immutable, approval-bound internal baseline at `.codex/project-workflow/<plan-id>/filesystem-baseline.json` before entering `IN_PROGRESS`, then completion compares relative path, size, mode, and SHA-256 metadata for added, modified, and deleted files. A baseline cannot be overwritten by an ordinary create; explicit recovery requires compare-and-swap against its existing canonical digest. The comparison validates literal task write scopes, excludes `.git/`, plugin internal state, and declared caches or temporary products, and must not follow symbolic links outside the workspace. It stores no file contents and is not a backup or rollback point.

`LIGHT` and `STANDARD` may use `NONE`; `STANDARD` requires baseline/final comparison evidence and disclosure that Git-level rollback is unavailable. New plans persist `rollback_required` as the string `"true"` or `"false"`; historical plans may omit it. A current serial NONE plan persists `filesystem_write_scopes` as a JSON list, while a companion state supplies the task-scope union for multi-agent completion. The lifecycle completion gate recomputes the baseline comparison and binds its digest and change counts. `FULL` with `NONE`, or any profile with `rollback_required: "true"`, requires an equivalent rollback source. Rollback capability requires all three plan fields: a non-empty `rollback_strategy`, non-empty `rollback_evidence`, and `rollback_verification: "VERIFIED"`. The plan and delivery evidence must identify the recovery source, restoration procedure, and validation result.

Plans may add these orchestration fields:

```yaml
execution_mode: "AUTO_MULTI_AGENT"
max_workers: 3
agent_topology: "SHARED_WORKSPACE"
progress_reporting: "COMPACT"
parallelism_policy: "BENEFIT_GATED"
orchestration_state: ".codex/project-workflow/stable-project-plan-id/orchestration.json"
```

Supported execution modes are:

- `AUTO_MULTI_AGENT`: the coordinator may proactively create native runtime workers after plan approval;
- `SINGLE_AGENT`: keep all implementation in the coordinator;
- `MANUAL_MULTI_AGENT`: delegate only tasks whose worker assignments are explicitly recorded in the approved plan.

New plans store `orchestration_state` under `.codex/project-workflow/<plan-id>/orchestration.json`. The file is plugin-owned internal recovery state, not a user-facing plan artifact and not something the user must review or edit. Existing plans that reference an external historical state remain readable for inspection and migration diagnostics, but no mutation is permitted until the state is moved under the internal repository root and the revised plan is approved.

New plans default `progress_reporting` to `COMPACT`, where native agent UI carries worker status and the main task reports aggregate start, actionable exceptions, and completion. `DETAILED` is opt-in for debugging. Legacy plans without this field default to `COMPACT`.

When the runtime exposes a native current-task title capability, synchronize it to
`conversation_title` after planning and again when resuming a revision whose title changed. A
missing or failed title capability is non-blocking and must not be replaced with UI automation.
During active execution, do not allow user-visible silence to exceed the resolved heartbeat
interval. Use a stricter runtime update requirement when one exists.

Plans without orchestration fields remain compatible and default to `SINGLE_AGENT`. `max_workers` counts workers only; the coordinator also consumes a runtime slot. The companion state file uses `project-workflow/orchestration/v1` and must match the plan ID and revision before delegation.

New automatic multi-agent plans use `BENEFIT_GATED` scheduling, estimate implementation and coordination time, and require at least 20% expected critical-path savings after coordination cost. Default to no more than two Workers. A disjoint independent contract verifier may run as the only ready Worker because its benefit is quality isolation rather than elapsed-time savings.

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

Approval of a plan that explicitly records `AUTO_MULTI_AGENT` or `MANUAL_MULTI_AGENT` authorizes native subagent delegation only for the approved task scopes. It does not authorize commits, pushes, deployments, destructive actions, purchases, credential sharing, or production access. Record those permissions separately.

Use `workflow_state.py start-execution PLAN --confirmation TEXT --repo REPO` as the canonical new-plan entry command. It holds a stable plan lock across the complete read-modify-write, atomically records approval, validates the approved revision and transition legality, and for current `NONE` plans creates or idempotently reuses the baseline bound to that exact approval before entering `IN_PROGRESS`. A conflicting baseline rejects the start without changing the plan or baseline. Lifecycle mutations may also use `--expected-revision`, `--expected-phase`, and `--expected-sha256` for explicit compare-and-swap. Retain lower-level approval, baseline recovery, validation, and positional transition commands only for historical compatibility and recovery. After final acceptance, validate companion orchestration state with `--final`, then use `workflow_state.py complete PLAN --repo REPO`.

Use `workflow_state.py resume PLAN --repo REPO` for an already `IN_PROGRESS` or `BLOCKED` plan. It revalidates approval, revision, version-control resolution, and rollback requirements; `IN_PROGRESS` is an idempotent no-write success, and only this command may restore `BLOCKED` to `IN_PROGRESS`. The low-level transition command must reject that bypass.

## Workflow Profiles

The confirmation gate is identical for all profiles:

- `LIGHT`: consolidated design and plan are allowed, execution defaults to the coordinator, and acceptance covers the primary path, applicable invalid input, and affected regression.
- `STANDARD`: use separate design and plan records, applicable boundary-matrix checks, integration or contract validation where needed, and benefit-gated native workers.
- `FULL`: includes STANDARD plus adversarial failure and recovery, rollback evidence, an independent contract verifier, and a migration state matrix whenever persisted state evolves.

Choose the stricter profile when triggers overlap. Lowering or otherwise changing an approved profile is a material plan revision requiring renewed confirmation.

Validation commands have an explicit stability class. `DISCOVERY` selects a directory or file pattern and is required while future tests do not yet exist. `EXACT` selects a known class or case and is allowed only after the target has been discovered or successfully executed. A stale exact selector is an internal recoverable diagnostic unless it changes scope or blocks acceptance.

## Skill Isolation

- `index` is the only implicitly invokable skill.
- `plan` and `execute` set `policy.allow_implicit_invocation: false` and are loaded only by routing or explicit invocation.
- Load one focused skill per turn.
- Planning turns never load or invoke execution.
- Execution turns may use specialized skills only within the approved task scope.
- Do not combine this workflow with another general project planning or plan-execution skill unless the user explicitly selects the alternative.

## Recovery and Change Control

After any restart, compaction, or handoff, rebuild state from repository documents and the approved change-evidence model rather than memory alone.

Planning begins with `project_workflow_doctor.py --repo REPO [--vcs-mode AUTO|GIT|NONE] [--json]`. Without a plan, Doctor defaults the requested mode to `AUTO`; with a plan, it validates the persisted request and resolution instead of accepting an override. Block only on a blocking result. Uniquely resolved package paths, corrected helper probes, and non-blocking advice stay in durable evidence and are not narrated individually in compact progress. Never persist a host-specific plugin cache-version path in public documentation.

For a multi-agent plan, also reconcile the companion orchestration state with the runtime agent list and workspace evidence. Every persisted mutation increments `state_version`; use `--expected-version` when coordinating concurrent writers and reconcile instead of blindly retrying on a mismatch. An activated Worker continues to hold its slot and write scope while blocked and may be released only with the matching runtime identity plus durable stopped evidence. A pending reservation may be released only as a spawn failure. In `NONE`, use only `SHARED_WORKSPACE` with disjoint write scopes; `SINGLE_AGENT` also records `SHARED_WORKSPACE`, while its execution mode remains coordinator-only. Serialize any tasks that require branch or worktree isolation. Never recreate a worker for a task that already has accepted completion evidence.

For a material change:

1. increment `revision`;
2. update the design and plan with impact analysis;
3. clear `approved_revision`, `approved_at`, and `confirmation_record`;
4. set `phase=AWAITING_CONFIRMATION`;
5. request renewed approval and stop.

For a genuine external blocker, use `BLOCKED` and record impact, attempted alternatives, and the exact input or state change required.
