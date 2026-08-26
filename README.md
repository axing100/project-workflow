# Project Workflow for Codex

[English](README.md) | [简体中文](README.zh-CN.md)

Project Workflow is an approval-gated workflow for complex software engineering tasks. It creates a reviewable design and implementation plan, waits for explicit approval, then executes the approved scope either coordinator-first or with native Codex agents when parallel work is safe and beneficial. It records validation, recovery, and delivery evidence while supporting both Git and non-Git repositories.

Routine small edits, formatting, and simple CRUD changes usually do not need this plugin.

## Why Project Workflow

Long-running engineering tasks often mix requirements, architecture, implementation, testing, and delivery in one continuous agent turn. A textual instruction such as “wait for approval” can be treated as an intermediate step instead of a real boundary.

Project Workflow makes that boundary explicit:

1. inspect the repository and write durable design and plan documents;
2. stop the current turn and wait for explicit user approval;
3. validate the recorded approval and plan revision;
4. execute serially or actively create, schedule, and verify native Codex agents according to the approved mode;
5. return to approval whenever a material change invalidates the plan.

## Skills

| Skill | Responsibility | Implicit invocation |
| --- | --- | --- |
| `project-workflow:index` | Own the lifecycle and route one phase at a time | Yes |
| `project-workflow:plan` | Create or revise design and implementation plans, then stop | No |
| `project-workflow:execute` | Validate and execute an approved plan | No |

Only the router is implicitly available. The focused planning and execution skills must be routed by the plugin or invoked explicitly, reducing conflicts with similar project-management skills.

## Approval Lifecycle

```text
DRAFT
  -> AWAITING_CONFIRMATION
  -> APPROVED
  -> IN_PROGRESS
  -> COMPLETED

APPROVED / IN_PROGRESS
  -> AWAITING_CONFIRMATION  (material change)
```

The bundled `workflow_state.py` helper validates required fields, revisions, approval records, and legal transitions. It uses only the Python standard library.

## Workflow Profiles

Every new plan records one of three profiles. All profiles retain the same approval boundary: planning stops before implementation and execution starts only after the user confirms the current revision.

| Profile | Intended use | Default execution and validation |
| --- | --- | --- |
| `LIGHT` | An explicitly requested workflow for a localized, low-risk change | Consolidated design and plan allowed; coordinator-only by default; primary path, applicable invalid input, and affected regression checks |
| `STANDARD` | Multi-module or independently verifiable work without migration, security, compatibility, or data-loss risk | Separate design and plan; applicable boundary checks; native Workers only when parallelism has material benefit |
| `FULL` | Architecture, persisted-state migration, compatibility, security, privacy, payment, data-loss, staged rollout, or long-running coordination | `STANDARD` plus adversarial recovery, rollback evidence, an isolated contract verifier, and a migration-state matrix whenever persisted state evolves |

When more than one profile fits, the stricter profile wins. Historical plans without `workflow_profile` remain valid and are interpreted as `FULL`, so an upgrade never silently weakens their acceptance requirements.

## Git-Optional Operation

Git is not required to run Project Workflow. Every new plan records a requested and resolved version-control mode:

| Mode | Behavior |
| --- | --- |
| `AUTO` | Uses `GIT` when Git is available and the project is a valid worktree; otherwise resolves cleanly to `NONE` |
| `GIT` | Requires Git and a valid worktree; Doctor blocks when either capability is missing |
| `NONE` | Runs no Git command, even inside a Git repository |

The resolved mode is persisted before approval and checked again at execution, resume, and delivery. A changed resolution is treated as environment drift and blocks further work until the environment is restored or the plan is revised and re-approved.

In `NONE`, the plugin creates an internal file-system baseline and reports deterministic added, modified, and deleted paths using relative paths, file sizes, modes, and SHA-256 hashes. Descriptor-relative reads and writes reject symlink races and unsupported FIFO, socket, or device entries instead of reporting false-clean evidence; directory mode changes are included. It does not store file contents or describe the manifest as a backup. `STANDARD` delivery discloses that Git-level rollback is unavailable. `FULL` requires a verified equivalent rollback source represented by non-empty `rollback_strategy` and `rollback_evidence` fields plus `rollback_verification: "VERIFIED"`; migration, security-remediation, and potential-data-loss work also block without verified rollback capability.

Multi-agent `NONE` execution uses one shared workspace and disjoint literal write scopes. Branches, worktrees, commits, tags, pushes, and all other Git operations are prohibited. Work that needs worktree isolation automatically runs serially.

## Execution Modes and Native Agents

- `SINGLE_AGENT`: coordinator-only serial execution for small task sets, overlapping write scopes, or low coordination value.
- `AUTO_MULTI_AGENT`: benefit-gated multi-agent execution; actively creates native Codex agents only when safe, non-conflicting work is expected to shorten the critical path by at least 20% after coordination cost.
- `MANUAL_MULTI_AGENT`: used only when the user explicitly specifies assignments or topology.

Planning records the task DAG, literal write scopes, estimates, coordination cost, critical-path membership, worker cap, and fallback behavior. New automatic plans default to at most two native Workers. An isolated contract verifier is the only single-ready-task exception because its benefit is independent quality review rather than elapsed-time reduction. Multi-agent modes keep plugin-owned recovery state at `.codex/project-workflow/<plan-id>/orchestration.json`; it is not a plan document that users need to review or edit. Approving the plan authorizes native-agent delegation only for the recorded scope, without repeated per-task approval. Commit, push, deployment, destructive actions, and other elevated operations remain separately authorized.

Workers use native collaboration inside the current Codex task, so they can appear in the app's agent UI. Agent chips and icons are rendered by Codex; the plugin supplies names and prompts but does not reference or configure icon image assets. The plugin reserves a task first and marks it as a Worker only after native spawn returns an agent ID; completion must match that same ID. If the runtime lacks that capability or has no free slots, the plugin records and reports the reason before safely falling back to coordinator execution. It never simulates agents with background shells, direct model APIs, separate user-owned tasks, or JSON-only worker claims.

Execution defaults to compact progress: phase changes, one aggregate wave-start message, native Codex agent UI for per-worker status, actionable retry/fallback or blocker messages, long-running heartbeats, and one final synthesis. New plans default to a meaningful aggregate update at least every five minutes of user-visible silence, including the business phase, completion count, active work, and next checkpoint; stricter runtime update rules win. The active Codex runtime enforces this conversational wait contract; the plugin does not add a background daemon. When Codex Desktop exposes a native title capability, the workflow also synchronizes the conversation title to the current plan's business name and safely degrades in CLI or unsupported runtimes. Successfully recovered path lookup, helper probes, and routine handoffs remain internal instead of adding conversational noise. Debug-level lifecycle output is opt-in.

## Requirements

- Codex Desktop or CLI with plugin support
- Python 3 for the workflow state helper
- Git only when cloning from GitHub or contributing; archive installation and workflow execution support environments without Git

Before planning, the workflow runs a quiet read-only Doctor preflight. It checks the plugin manifest and helpers, Python capabilities, repository state paths, and optional plan/orchestration revision compatibility. Doctor does not guess native-agent capacity: that field is reported as `UNKNOWN`, while actual slots come from the Codex runtime. Only blocking findings stop planning. An explicit external plugin root is statically inspected but treated as untrusted and never executed.

## Install from GitHub

Add this repository as a Codex marketplace and install the plugin:

```bash
codex plugin marketplace add axing100/project-workflow
codex plugin add project-workflow@project-workflow-local
```

Start a new Codex task after installation so the skills are loaded.

## Install from a Local Clone or Archive

```bash
git clone https://github.com/axing100/project-workflow.git
codex plugin marketplace add <path-to-project-workflow>
codex plugin add project-workflow@project-workflow-local
```

For an archive, extract it to a stable directory and use that directory in `marketplace add`.

## Usage

Start a complex project with a prompt such as:

```text
Use Project Workflow to design and implement this cross-module migration.
```

The planning phase writes repository-backed design and implementation-plan documents, then ends the turn. Review those files and approve the specific plan in a later message:

```text
I approve the linked plan. Start execution.
```

Phrases in the initial request such as “go ahead,” “finish everything,” or “do it in one pass” do not pre-approve a plan that does not yet exist.

The router chooses `LIGHT`, `STANDARD`, or `FULL` from the inspected scope and risks. You may request a stricter profile, but an approved profile cannot be weakened without revising the plan and asking for confirmation again.

## Doctor Preflight

Run the same read-only preflight directly when troubleshooting:

```bash
python3 plugins/project-workflow/scripts/project_workflow_doctor.py --repo <repository-root>
python3 plugins/project-workflow/scripts/project_workflow_doctor.py --repo <repository-root> --vcs-mode NONE --json
python3 plugins/project-workflow/scripts/project_workflow_doctor.py --repo <repository-root> --plan <plan-path> --orchestration <state-path> --json
```

The default output is a one-line human-readable result. `--json` emits stable machine-readable fields, including `version_control.requested`, `resolved`, `git_available`, `git_worktree`, `rollback_capable`, and `status`. Without a plan, `--vcs-mode` defaults to `AUTO`; with a plan, Doctor validates its recorded request and resolution. Plan and orchestration paths are interpreted relative to the repository root. A uniquely recoverable local plugin location is resolved quietly; host-specific cache paths are not part of the public contract.

## Workflow State Helper

The workflow helpers are located in `plugins/project-workflow/scripts/`.

```bash
python3 plugins/project-workflow/scripts/workflow_state.py init <plan.md> --plan-id <id> --repo <repository-root> --vcs-mode AUTO
python3 plugins/project-workflow/scripts/workflow_state.py experience <plan.md>
python3 plugins/project-workflow/scripts/workflow_state.py start-execution <plan.md> --repo <repository-root> --confirmation "<user-confirmation>"
python3 plugins/project-workflow/scripts/workflow_state.py resume <plan.md> --repo <repository-root>
python3 plugins/project-workflow/scripts/workflow_state.py complete <plan.md> --repo <repository-root>
python3 plugins/project-workflow/scripts/orchestration_state.py validate <state.json> --plan <plan.md> --repo <repository-root> --final
python3 plugins/project-workflow/scripts/orchestration_state.py ready <state.json> --plan <plan.md> --repo <repository-root> --agent-only
python3 plugins/project-workflow/scripts/orchestration_state.py assign <state.json> <task-id> --plan <plan.md> --repo <repository-root> --owner <task-name> --expected-version <state-version>
python3 plugins/project-workflow/scripts/orchestration_state.py activate <state.json> <task-id> --plan <plan.md> --repo <repository-root> --runtime-agent-id <agent-id> --runtime-task-name <canonical-task-name> --expected-version <state-version>
python3 plugins/project-workflow/scripts/orchestration_state.py complete <state.json> <task-id> --plan <plan.md> --repo <repository-root> --runtime-agent-id <agent-id> --evidence <evidence> --expected-version <state-version>
python3 plugins/project-workflow/scripts/orchestration_state.py inspect <state.json> --repo <repository-root>
```

`experience` returns the current business conversation title and heartbeat interval; historical plans derive their title from the first level-one heading or plan ID and default to five minutes. Lifecycle mutations hold a stable plan lock. `start-execution` atomically records the confirmation, validates the approved revision, and for current `NONE` plans creates and approval-binds an immutable baseline before entering `IN_PROGRESS`; optional `--expected-revision`, `--expected-phase`, and `--expected-sha256` values provide explicit compare-and-swap. `resume` is a no-write success for an executing plan and is the only gated route from `BLOCKED` back to execution. `complete` holds the scheduler lock, revalidates every companion task, binds the accepted `state_version`, and for current `NONE` plans recomputes and binds the baseline comparison using companion task scopes or the serial plan's `filesystem_write_scopes`; failed validation leaves the plan unchanged, and Doctor reuses the same final validator. Lower-level commands remain for historical compatibility, but cannot bypass resume. Orchestration mutations increment `state_version` and accept `--expected-version`; releasing an activated Worker requires its runtime identity and `--stopped-evidence`, while a pending reservation uses `--spawn-failed`.

The helpers strengthen consistency, but they are not authorization or security boundaries and cannot cryptographically prove that natural-language approval is genuine.

For `NONE`, canonical `start-execution` creates the internal baseline automatically. The following low-level commands are for diagnostics; ordinary `create` is create-only, and recovery replacement requires `--replace-if-sha256` with the current canonical digest:

```bash
python3 plugins/project-workflow/scripts/filesystem_snapshot.py create --repo <repository-root> --output .codex/project-workflow/<plan-id>/filesystem-baseline.json --exclude <declared-cache>
python3 plugins/project-workflow/scripts/filesystem_snapshot.py compare --repo <repository-root> --baseline .codex/project-workflow/<plan-id>/filesystem-baseline.json --write-scope <allowed-path>
```

Plan-aware recovery uses:

```bash
python3 plugins/project-workflow/scripts/workflow_state.py create-baseline <plan.md> --repo <repository-root> --replace-if-sha256 <existing-baseline-sha256>
```

Repeat `--write-scope` and `--exclude` as needed. Create prints a summary by default (`--json-details` exposes the full manifest); compare fails on out-of-scope changes unless the diagnostic `--report-only` option is explicit. Relative evidence paths resolve under the repository root. The result is change and scope evidence, not recoverable backup content.

## Risk-Driven Acceptance

`STANDARD` and `FULL` plans select relevant boundaries rather than applying a fixed checklist mechanically: null/type confusion, numeric limits and overflow, duplicates and unknown values, clock and timezone behavior, idempotent retries, atomicity, concurrency, raw exception leakage, and recovery paths. A `FULL` persisted-state change additionally maps every old state—including running work, missing or expired leases, and unknown states—to an explicit migration or isolation outcome.

The independent contract verifier receives the original request, public contract, and acceptance criteria, but not implementation discussion or Worker self-review. It writes black-box tests or findings in a disjoint scope and returns failures to the implementation owner for correction.

## Update

Refresh the marketplace and reinstall the plugin:

```bash
codex plugin marketplace upgrade project-workflow-local
codex plugin add project-workflow@project-workflow-local
```

Start a new Codex task after updating.

During local development, do not commit a `+codex.<cache-token>` suffix in the repository manifest.
Keep `plugins/project-workflow/.codex-plugin/plugin.json` at the release version and use the
isolated installer instead:

```bash
python3 scripts/install_local_plugin.py
```

The script adds `<release-version>+codex.<UTC-microseconds>-<random-nonce>` only to a disposable staging copy,
installs from that copy, and removes it afterward. It does not modify the source manifest or
marketplace file. During installation it temporarily switches the local marketplace and restores
the original path after either success or failure, leaving the persisted configuration unchanged.
Start a new Codex task after the installation.

## Compatibility and Rollback

Version 0.4 keeps the previous low-level lifecycle commands and accepts v0.3 plans and orchestration state. Missing new optional scheduling fields do not require a migration, a missing `workflow_profile` is treated as `FULL`, and a missing `vcs_mode` is read as `AUTO` without rewriting the historical plan.

The source rollback baseline is release `v0.3.0`. Restore or reinstall its archive, or use the corresponding Git tag when developing from a clone. The plugin never resets, commits, tags, pushes, deploys, or overwrites user changes automatically. A local reinstall uses the normal marketplace/cachebuster flow and still requires explicit authorization when it changes the active Codex installation.

## Uninstall

```bash
codex plugin remove project-workflow
codex plugin marketplace remove project-workflow-local
```

Remove the marketplace only when no other required plugin uses it.

## Share and Contribute

You can share the GitHub URL or distribute an archive of the entire repository. The `.agents/plugins/marketplace.json` file uses a relative plugin path, so cloned and extracted copies remain installable.

Before contributing, run:

```bash
python3 -m unittest discover -s tests -v
python3 -m unittest discover -s plugins/project-workflow/tests -v
python3 <skill-creator-path>/scripts/quick_validate.py plugins/project-workflow/skills/index
python3 <skill-creator-path>/scripts/quick_validate.py plugins/project-workflow/skills/plan
python3 <skill-creator-path>/scripts/quick_validate.py plugins/project-workflow/skills/execute
python3 <plugin-creator-path>/scripts/validate_plugin.py plugins/project-workflow
```

## Security and Limitations

- System, developer, repository, and explicit user instructions retain their normal precedence.
- Specialized skills may assist within the approved scope, but they must not change workflow phase or skip approval.
- Commit, push, deployment, and destructive-operation permissions are recorded separately and never inferred from plan approval.
- Automatic parallelism must pass the 20% critical-path benefit threshold and is bounded by the plan cap, ready-task count, and native Codex collaboration slots. New plans default to at most two Workers; conflicting write scopes are never scheduled together.
- The plugin can only schedule native agents actually exposed by the current Codex runtime. It cannot add unavailable product capabilities or UI.
- The plugin cannot prevent a higher-priority instruction or a deliberately modified state file from bypassing its behavioral rules.

## License

Licensed under the [Apache License 2.0](LICENSE).
