---
name: plan
description: Create or revise durable repository-backed project specifications and implementation plans, then stop for explicit user approval. Use only when routed by the Project Workflow index skill or when the user explicitly invokes this focused skill. Do not implement production code, run implementation steps, or continue into execution in the same turn.
---

# Project Workflow Plan

## Non-Negotiable Gate

This skill is planning-only. Do not modify production code, implement tasks, commit, push, deploy, or invoke the execute skill in this turn. After presenting the plan confirmation request, end the turn immediately.

Read [workflow-protocol.md](../../references/workflow-protocol.md), [execution-checklists.md](../../references/execution-checklists.md), and [multi-agent-orchestration.md](../../references/multi-agent-orchestration.md) completely before writing the plan.

## Inspect

1. Read applicable `AGENTS.md` files and repository conventions.
2. Run the bundled Doctor before technical planning:

   ```bash
   python3 <plugin-root>/scripts/project_workflow_doctor.py --repo <repo-root> --vcs-mode AUTO --json
   ```

   Replace `AUTO` when the user or repository policy explicitly requires `GIT` or `NONE`. Resolve `<plugin-root>` from the currently loaded skill package; never persist a local cache-version path in public documents. A uniquely recoverable stale package path is an internal recovery detail. Stop only for a blocking Doctor result. Record non-blocking findings in the plan evidence without narrating each recovery step to the user.
3. Inspect repository architecture, contracts, tests, and the resolved version-control evidence surface before making technical claims. Inspect Git branch and working-tree state only when the resolved mode is `GIT`.
4. Preserve all pre-existing user changes.
5. Ask only questions required to remove material ambiguity; otherwise state concise assumptions and proceed with planning.

## Select Workflow Profile

Persist exactly one profile in new plan frontmatter:

```yaml
workflow_profile: STANDARD
```

- `LIGHT`: explicit Project Workflow use for a localized, low-risk change. Keep approval, but allow the design to be a clearly labeled section in the plan. Default to `SINGLE_AGENT`; require primary-path, invalid-input, and affected regression checks.
- `STANDARD`: multi-module or independently verifiable work without migration, security, compatibility, or data-loss risk. Create separate design and plan records, apply the relevant boundary matrix, and delegate only when parallel benefit is material.
- `FULL`: architecture, persisted-state migration, compatibility, security, privacy, payment, data-loss, staged rollout, or long-running coordination. Include adversarial failure and recovery coverage, rollback evidence, and an independent contract-verifier task. If persisted state evolves, include a migration state matrix.

When more than one profile fits, choose the stricter profile. Historical plans without `workflow_profile` are `FULL`; never edit them merely to add the default. Changing an approved profile requires revision and re-approval.

## Select Version-Control Mode

Persist the user's requested mode and the environment resolution in every new plan:

```yaml
vcs_mode: AUTO
resolved_vcs_mode: GIT
rollback_required: "false"
```

- `AUTO`: resolve to `GIT` only when Git is executable and the repository root is in a valid Git worktree; otherwise resolve to `NONE` without treating the absence of Git as an error.
- `GIT`: require an executable Git and a valid Git worktree. A failed explicit requirement is a planning blocker.
- `NONE`: do not run Git commands even when the repository root is inside a Git worktree.

Use `AUTO` unless the user or repository policy explicitly chooses `GIT` or `NONE`. Read historical plans without `vcs_mode` as `AUTO`, but do not rewrite them solely to materialize the default. Persist `resolved_vcs_mode` before requesting confirmation so execution can detect environment drift instead of silently switching evidence models.

For `NONE`, plan file-system baseline and final comparison evidence that records relative paths, sizes, modes, and SHA-256 hashes without file contents. State explicitly that this evidence identifies added, modified, and deleted files but is not a backup or rollback point. Persist `rollback_required` as the string `"true"` for migration, security remediation, or potential data-loss work and `"false"` otherwise. A current `SINGLE_AGENT + NONE` plan also persists a normalized JSON list `filesystem_write_scopes`; multi-agent completion derives the same union from companion tasks. `STANDARD` requires baseline evidence and a disclosure that Git-level rollback is unavailable. `FULL` with `NONE`, or any profile with `rollback_required: "true"`, requires a verified equivalent rollback source, recovery steps, and validation evidence. Rollback capability requires non-empty `rollback_strategy` and `rollback_evidence` fields plus `rollback_verification: "VERIFIED"`; partial or different values are not proof.

## Create Durable Records

Reuse repository conventions. Otherwise, for `STANDARD` and `FULL`, create:

- `docs/design/NNN-需求名称设计.md`
- `docs/plan/NNN-需求名称实施计划.md`
- `docs/delivery/NNN-需求名称交付报告.md` only during delivery

For `LIGHT`, create the plan and later delivery record, but the design may be a self-contained `Design` section inside the plan instead of a separate file.

The design must include goal, scope, functional and relevant non-functional requirements, technical solution, boundaries, tradeoffs, assumptions, compatibility, security, observability, deployment, and rollback considerations.

The plan must contain YAML frontmatter following the shared protocol and set:

```yaml
workflow: project-workflow/v1
plan_id: stable-project-plan-id
revision: 1
phase: AWAITING_CONFIRMATION
approved_revision:
approved_at:
confirmation_record:
workflow_profile: STANDARD
conversation_title: "简短业务任务名称"
progress_heartbeat_minutes: 5
vcs_mode: AUTO
resolved_vcs_mode: GIT
```

Use the bundled state helper to initialize or normalize the frontmatter:

```bash
python3 <plugin-root>/scripts/workflow_state.py init <plan-path> --plan-id <plan-id> --repo <repo-root> --vcs-mode AUTO
```

Replace `AUTO` only when the user or repository policy explicitly requires `GIT` or `NONE`.

Choose `conversation_title` from the current business request rather than an earlier task in the
same conversation. Keep it concise and omit runtime identities, workflow enums, and generic verbs
such as “处理任务”. Default `progress_heartbeat_minutes` to 5 unless a stricter runtime rule
applies. After initialization, resolve both values with:

```bash
python3 <plugin-root>/scripts/workflow_state.py experience <plan-path>
```

When the runtime exposes a native current-task title tool, set the title to the resolved value
before requesting plan confirmation. Treat an unavailable or failed title tool as non-blocking;
do not use computer control or UI automation as a substitute.

For a revision, increment `revision`, clear all approval fields, and return `phase` to `AWAITING_CONFIRMATION`.

## Choose Execution Mode

Choose and persist one execution mode before asking for approval:

- `SINGLE_AGENT`: use when the user requests it, fewer than two tasks are safely agent-eligible, write scopes overlap, requirements are unsettled, or coordination cost exceeds the likely benefit.
- `AUTO_MULTI_AGENT`: the default multi-agent mode when at least two dependency-ready tasks have disjoint literal write scopes and parallel execution has a material benefit.
- `MANUAL_MULTI_AGENT`: use only when the user explicitly specifies agent assignments or asks to control the topology.

Add these plan frontmatter fields:

```yaml
execution_mode: AUTO_MULTI_AGENT
max_workers: 2
agent_topology: SHARED_WORKSPACE
progress_reporting: COMPACT
progress_heartbeat_minutes: 5
parallelism_policy: BENEFIT_GATED
orchestration_state: .codex/project-workflow/<plan-id>/orchestration.json
```

Choose a conservative `max_workers`; the coordinator also consumes a runtime collaboration slot. In `SINGLE_AGENT`, set `max_workers: 1`, omit `orchestration_state`, and still use `agent_topology: SHARED_WORKSPACE`; execution mode, not a second topology vocabulary, guarantees coordinator-only execution. Read historical `coordinator-only` values without rewriting them, but normalize the next approved revision to `SHARED_WORKSPACE`. Treat legacy plans without these fields as `SINGLE_AGENT`.

For `AUTO_MULTI_AGENT`, estimate implementation time and coordination time for each agent-eligible task, identify critical-path tasks, and require at least 20% expected critical-path savings after coordination cost. Default to at most two Workers unless inspected runtime capacity and the task graph justify a different explicit limit. Independent contract verification is a quality-isolation exception: it may be delegated when it is the only ready Worker task, provided its write scope does not overlap the implementation it verifies.

Default `progress_reporting` to `COMPACT`. Use `DETAILED` only when the user explicitly asks for debug-level workflow output. In compact mode, use user-facing task labels and plain-language phases; do not show raw enum values, runtime agent IDs, canonical `/root/...` task names, plugin cache paths, or state-helper commands. Localize user-facing workflow values to the current conversation language. When a stable enum is useful for traceability, show it only as a secondary parenthetical after a plain-language explanation, never as the sole explanation.

Choose exactly one persisted task-display language: `zh-CN` for a Chinese conversation and
`en-US` otherwise. Only these two locales are supported. Unsupported or ambiguous language values
fall back to `en-US`. Keep this choice in internal task state, reuse it across resume and render,
and never translate user-authored task titles or free-form plan text.

## Plan Tasks

Break implementation into dependency-aware, commit-sized tasks. For every task record:

- goal, scope, exclusions, prerequisites, risks, and stable task ID;
- observable acceptance criteria;
- exact validation commands where known;
- dependencies (`Depends-On`) and a literal repository-relative `Write-Scope` without globs;
- `Agent-Eligible`, `Parallel-Group`, and `Planned-Owner` metadata where applicable;
- evidence placeholder.

For agent-eligible tasks also record `Estimated-Minutes`, `Coordination-Minutes`, and `Critical-Path`. Mark independent verification with `Role: CONTRACT_VERIFIER` and `Independent-Verification: true`. Give that verifier only the original requirements, public contracts, and acceptance criteria; do not include implementation discussions or Worker self-validation conclusions.

Classify every planned validation command:

- `DISCOVERY`: directory, filename pattern, or test discovery that remains valid before future tests exist. Use this during planning for files or test symbols that will be created later.
- `EXACT`: a precise class, method, or selector. Use only when the target already exists and the selector has been discovered or executed successfully.

Never invent a future exact test selector. Execution may tighten a `DISCOVERY` command to `EXACT` only after confirming the target exists.

Keep canonical workflow documents, shared manifests, migrations, generated lockfiles, broad integration edits, and permitted Git operations coordinator-owned unless their ownership is isolated beyond doubt. In `NONE`, do not plan branch, worktree, commit, push, or any other Git operation.

For `AUTO_MULTI_AGENT` and `MANUAL_MULTI_AGENT`, create the plugin-owned companion orchestration JSON described by the shared protocol at `.codex/project-workflow/<plan-id>/orchestration.json`. Include every plan task, set `max_attempts: 2` unless risk requires a lower value, and validate it before requesting approval. Create and update this state only through `orchestration_state.py`; never use a normal file-edit operation for it, link it, or present it as a document the user needs to review:

```bash
python3 <plugin-root>/scripts/orchestration_state.py init <state-path> --plan <plan-path> --repo <repo-root> \
  --task '{"id":"T01","display_name":"user-facing task name","depends_on":[],"write_scope":["literal/path"],"agent_eligible":true}'
python3 <plugin-root>/scripts/orchestration_state.py validate <state-path> --plan <plan-path> --repo <repo-root>
```

Do not create an orchestration JSON for `SINGLE_AGENT`.

Copy applicable quality checklist items into the plan so execution does not depend on this plugin remaining installed.

After every task heading and dependency record exists, initialize the internal task state and
render its localized, controlled status blocks before requesting confirmation:

```bash
python3 <plugin-root>/scripts/task_state.py migrate <plan-path> --repo <repo-root> --display-language <zh-CN-or-en-US>
python3 <plugin-root>/scripts/task_state.py inspect <plan-path> --repo <repo-root>
```

The internal JSON is the only source of truth for task progress. The Markdown summary and per-task
status blocks are generated views. Never hand-edit their marker blocks or infer state by parsing
localized text, icons, acceptance checkboxes, or evidence prose. Historical `[ ]`, `[~]`, `[x]`,
`[!]`, and `[-]` markers are migrated conservatively by the helper.

For `STANDARD` and `FULL`, select applicable rows from the boundary matrix in the checklist and explicitly mark irrelevant dimensions `N/A` with a reason. For a `FULL` plan that changes persisted state, enumerate old-to-new mappings for every state, including active or orphaned running work, missing and expired leases, unknown states, repeated migration, rollback, and crash re-entry. A generic statement such as "migration is compatible" is not a migration state matrix.

Record commit and push authorization separately. Both default to not authorized.

## Confirmation Boundary

The initial request cannot approve a plan that has not yet been created. Expressions such as "直接完成", "一口气做完", "go ahead", or "finish it" are not approval of a newly generated plan.

Summarize the version-control evidence and rollback posture, parallel tasks, worker cap, coordinator-owned tasks, and fallback behavior in plain language. When the resolved mode is `NONE`, state that agents share one workspace, may only use disjoint write scopes, and tasks requiring worktree isolation will run serially. Do not expose the internal state path. Approval of this plan authorizes only the recorded in-scope native-agent delegation; it does not authorize commit, push, deployment, destructive actions, or scope expansion.

End with links to the durable design and plan. In the user's current conversation language,
state that the plan is ready and awaiting confirmation; after confirmation, execution will follow
the approved plan; native agents will appear in the Codex UI; and the main task will report the
start, actionable exceptions, long-running phase heartbeats, and the final result. Preserve this
meaning without reproducing fixed wording verbatim. Phrase the approval request with the natural-language
feature title and localized revision wording. Machine identifiers such as `plan_id` and `revision` may
appear separately for traceability, but must not be presented as text the user has to copy to approve.

Then end the current turn immediately. Do not call implementation, build, test, deployment, or execution tools after that confirmation request.
