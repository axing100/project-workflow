# Project Workflow for Codex

[English](README.md) | [简体中文](README.zh-CN.md)

Project Workflow is an approval-gated, active multi-agent Codex plugin for complex software projects. It separates planning from implementation, persists project and scheduling state in the repository, and prevents a newly generated plan from silently continuing into code changes.

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

## Execution Modes and Native Agents

- `SINGLE_AGENT`: coordinator-only serial execution for small task sets, overlapping write scopes, or low coordination value.
- `AUTO_MULTI_AGENT`: the default multi-agent mode; actively creates native Codex agents when at least two safe, non-conflicting tasks are ready.
- `MANUAL_MULTI_AGENT`: used only when the user explicitly specifies assignments or topology.

Planning records the task DAG, literal write scopes, worker cap, and fallback behavior, and creates a companion JSON in multi-agent modes. Approving the plan authorizes native-agent delegation only for the recorded scope, without repeated per-task approval. Commit, push, deployment, destructive actions, and other elevated operations remain separately authorized.

Workers use native collaboration inside the current Codex task, so they can appear in the app's agent UI. If the runtime lacks that capability or has no free slots, the plugin records the reason and safely falls back to coordinator execution. It never simulates agents with background shells, direct model APIs, or separate user-owned tasks.

## Requirements

- Codex Desktop or CLI with plugin support
- Python 3 for the workflow state helper
- Git, when installing from GitHub or contributing

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

## Workflow State Helper

The workflow helpers are located in `plugins/project-workflow/scripts/`.

```bash
python3 plugins/project-workflow/scripts/workflow_state.py init <plan.md> --plan-id <id>
python3 plugins/project-workflow/scripts/workflow_state.py approve <plan.md> --confirmation "<user message>"
python3 plugins/project-workflow/scripts/workflow_state.py check-execute <plan.md>
python3 plugins/project-workflow/scripts/workflow_state.py transition <plan.md> IN_PROGRESS
python3 plugins/project-workflow/scripts/orchestration_state.py validate <state.json> --plan <plan.md>
python3 plugins/project-workflow/scripts/orchestration_state.py ready <state.json> --plan <plan.md> --agent-only
python3 plugins/project-workflow/scripts/orchestration_state.py inspect <state.json> --plan <plan.md>
```

The helper strengthens consistency, but it is not an authorization or security boundary and cannot cryptographically prove that natural-language approval is genuine.

## Update

Refresh the marketplace and reinstall the plugin:

```bash
codex plugin marketplace upgrade project-workflow-local
codex plugin add project-workflow@project-workflow-local
```

Start a new Codex task after updating.

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
- Parallelism is bounded by the plan cap, ready-task count, and native Codex collaboration slots; conflicting write scopes are never scheduled together.
- The plugin can only schedule native agents actually exposed by the current Codex runtime. It cannot add unavailable product capabilities or UI.
- The plugin cannot prevent a higher-priority instruction or a deliberately modified state file from bypassing its behavioral rules.

## License

Licensed under the [Apache License 2.0](LICENSE).
