#!/usr/bin/env python3
"""Manage durable multi-agent task scheduling state for Project Workflow."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

from workflow_state import WorkflowError, parse_document, require_common


SCHEMA = "project-workflow/orchestration/v1"
VALID_MODES = {"AUTO_MULTI_AGENT", "SINGLE_AGENT", "MANUAL_MULTI_AGENT"}
VALID_TOPOLOGIES = {"SHARED_WORKSPACE", "ISOLATED_WORKTREE", "REMOTE_AGENT"}
VALID_TASK_STATES = {"PENDING", "ASSIGNED", "COMPLETED", "BLOCKED"}
ROOT_FIELDS = (
    "schema",
    "plan_id",
    "revision",
    "execution_mode",
    "max_workers",
    "topology",
    "tasks",
)
TASK_FIELDS = (
    "id",
    "status",
    "depends_on",
    "write_scope",
    "agent_eligible",
    "owner",
    "started_at",
    "attempts",
    "evidence",
    "block_reason",
)


class OrchestrationError(ValueError):
    """Report invalid scheduler state or an unsafe task transition."""


def now_utc() -> str:
    """Return a stable UTC timestamp without fractional seconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def load_state(path: Path) -> Dict[str, Any]:
    """Load a scheduler state document from JSON."""
    if not path.is_file():
        raise OrchestrationError(f"orchestration state does not exist: {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise OrchestrationError(f"invalid orchestration JSON: {exc}") from exc
    if not isinstance(state, dict):
        raise OrchestrationError("orchestration state root must be an object")
    return state


def write_state(path: Path, state: Dict[str, Any]) -> None:
    """Atomically write normalized scheduler state."""
    state["updated_at"] = now_utc()
    content = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def require_string(value: Any, field: str, allow_empty: bool = False) -> str:
    """Validate and return a string field."""
    if not isinstance(value, str):
        raise OrchestrationError(f"{field} must be a string")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise OrchestrationError(f"{field} must not be empty")
    return normalized


def normalize_scope(scope: str, field: str) -> str:
    """Normalize a repository-relative literal write scope."""
    normalized = require_string(scope, field).replace("\\", "/").rstrip("/")
    if normalized.startswith("/") or normalized == ".." or normalized.startswith("../"):
        raise OrchestrationError(f"{field} must be repository-relative: {scope}")
    if "/../" in f"/{normalized}/" or normalized.startswith("./"):
        raise OrchestrationError(f"{field} must not contain relative traversal: {scope}")
    if any(character in normalized for character in "*?[]{}"):
        raise OrchestrationError(f"{field} must be a literal path, not a glob: {scope}")
    return normalized


def scopes_overlap(left: Iterable[str], right: Iterable[str]) -> bool:
    """Return whether two sets of literal repository scopes overlap."""
    for left_scope in left:
        for right_scope in right:
            if (
                left_scope == right_scope
                or left_scope.startswith(f"{right_scope}/")
                or right_scope.startswith(f"{left_scope}/")
            ):
                return True
    return False


def validate_task(task: Any, index: int) -> Dict[str, Any]:
    """Validate and normalize one task record in place."""
    if not isinstance(task, dict):
        raise OrchestrationError(f"tasks[{index}] must be an object")
    missing = [field for field in TASK_FIELDS if field not in task]
    if missing:
        raise OrchestrationError(f"tasks[{index}] missing fields: {', '.join(missing)}")

    task_id = require_string(task["id"], f"tasks[{index}].id")
    if not task_id.startswith("T") or not task_id[1:].isdigit():
        raise OrchestrationError(f"invalid task id: {task_id}")
    status = require_string(task["status"], f"tasks[{index}].status")
    if status not in VALID_TASK_STATES:
        raise OrchestrationError(f"invalid task status for {task_id}: {status}")

    dependencies = task["depends_on"]
    if not isinstance(dependencies, list) or not all(isinstance(item, str) for item in dependencies):
        raise OrchestrationError(f"depends_on for {task_id} must be a string list")
    if len(set(dependencies)) != len(dependencies) or task_id in dependencies:
        raise OrchestrationError(f"invalid or duplicate dependencies for {task_id}")

    raw_scopes = task["write_scope"]
    if not isinstance(raw_scopes, list) or not all(isinstance(item, str) for item in raw_scopes):
        raise OrchestrationError(f"write_scope for {task_id} must be a string list")
    scopes = [normalize_scope(item, f"{task_id}.write_scope") for item in raw_scopes]
    if len(set(scopes)) != len(scopes):
        raise OrchestrationError(f"duplicate write scopes for {task_id}")
    if not isinstance(task["agent_eligible"], bool):
        raise OrchestrationError(f"agent_eligible for {task_id} must be boolean")
    if task["agent_eligible"] and not scopes:
        raise OrchestrationError(f"agent-eligible task {task_id} requires a write scope")

    owner = require_string(task["owner"], f"{task_id}.owner", allow_empty=True)
    started_at = require_string(task["started_at"], f"{task_id}.started_at", allow_empty=True)
    if not isinstance(task["attempts"], int) or task["attempts"] < 0:
        raise OrchestrationError(f"attempts for {task_id} must be a non-negative integer")
    evidence = task["evidence"]
    if not isinstance(evidence, list) or not all(isinstance(item, str) and item.strip() for item in evidence):
        raise OrchestrationError(f"evidence for {task_id} must be a non-empty string list")
    block_reason = require_string(task["block_reason"], f"{task_id}.block_reason", allow_empty=True)

    if status == "ASSIGNED" and (not owner or not started_at):
        raise OrchestrationError(f"assigned task {task_id} requires owner and started_at")
    if status == "PENDING" and (owner or started_at or block_reason):
        raise OrchestrationError(f"pending task {task_id} must not retain assignment or block fields")
    if status == "COMPLETED" and not evidence:
        raise OrchestrationError(f"completed task {task_id} requires evidence")
    if status == "BLOCKED" and not block_reason:
        raise OrchestrationError(f"blocked task {task_id} requires block_reason")

    task["id"] = task_id
    task["depends_on"] = dependencies
    task["write_scope"] = scopes
    task["owner"] = owner
    task["started_at"] = started_at
    task["block_reason"] = block_reason
    task.setdefault("parallel_group", "")
    task.setdefault("planned_owner", "")
    task.setdefault("branch_or_worktree", "")
    task.setdefault("assignment_kind", "")
    task["planned_owner"] = require_string(
        task["planned_owner"], f"{task_id}.planned_owner", allow_empty=True
    )
    assignment_kind = require_string(
        task["assignment_kind"], f"{task_id}.assignment_kind", allow_empty=True
    )
    if assignment_kind not in {"", "WORKER", "COORDINATOR"}:
        raise OrchestrationError(f"invalid assignment_kind for {task_id}: {assignment_kind}")
    task["assignment_kind"] = assignment_kind
    if status == "ASSIGNED" and not assignment_kind:
        raise OrchestrationError(f"assigned task {task_id} requires assignment_kind")
    if status == "PENDING" and assignment_kind:
        raise OrchestrationError(f"pending task {task_id} must not retain assignment_kind")
    return task


def detect_cycle(tasks: Dict[str, Dict[str, Any]]) -> None:
    """Reject dependency cycles with depth-first traversal."""
    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise OrchestrationError(f"dependency cycle detected at {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in tasks[task_id]["depends_on"]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in tasks:
        visit(task_id)


def validate_state(state: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Validate scheduler schema and return tasks indexed by ID."""
    missing = [field for field in ROOT_FIELDS if field not in state]
    if missing:
        raise OrchestrationError(f"missing root fields: {', '.join(missing)}")
    if state["schema"] != SCHEMA:
        raise OrchestrationError(f"unsupported orchestration schema: {state['schema']}")
    require_string(state["plan_id"], "plan_id")
    if not isinstance(state["revision"], int) or state["revision"] < 1:
        raise OrchestrationError("revision must be a positive integer")
    mode = require_string(state["execution_mode"], "execution_mode")
    if mode not in VALID_MODES:
        raise OrchestrationError(f"invalid execution_mode: {mode}")
    if not isinstance(state["max_workers"], int) or state["max_workers"] < 1:
        raise OrchestrationError("max_workers must be a positive integer")
    state.setdefault("max_attempts", 2)
    if not isinstance(state["max_attempts"], int) or state["max_attempts"] < 1:
        raise OrchestrationError("max_attempts must be a positive integer")
    topology = require_string(state["topology"], "topology")
    if topology not in VALID_TOPOLOGIES:
        raise OrchestrationError(f"invalid topology: {topology}")
    if not isinstance(state["tasks"], list) or not state["tasks"]:
        raise OrchestrationError("tasks must be a non-empty list")
    if "events" in state and not isinstance(state["events"], list):
        raise OrchestrationError("events must be a list")
    state.setdefault("events", [])

    tasks: Dict[str, Dict[str, Any]] = {}
    for index, raw_task in enumerate(state["tasks"]):
        task = validate_task(raw_task, index)
        if task["id"] in tasks:
            raise OrchestrationError(f"duplicate task id: {task['id']}")
        tasks[task["id"]] = task
    for task in tasks.values():
        unknown = [item for item in task["depends_on"] if item not in tasks]
        if unknown:
            raise OrchestrationError(f"unknown dependencies for {task['id']}: {', '.join(unknown)}")
    detect_cycle(tasks)

    if mode == "MANUAL_MULTI_AGENT":
        for task in tasks.values():
            if task["agent_eligible"] and not task["planned_owner"]:
                raise OrchestrationError(
                    f"manual agent-eligible task {task['id']} requires planned_owner"
                )

    assigned = [task for task in tasks.values() if task["status"] == "ASSIGNED"]
    assigned_workers = [task for task in assigned if task["assignment_kind"] == "WORKER"]
    if len(assigned_workers) > state["max_workers"]:
        raise OrchestrationError("assigned worker count exceeds max_workers")
    owners: Set[str] = set()
    for index, task in enumerate(assigned):
        if task["owner"] in owners:
            raise OrchestrationError(f"owner has multiple active tasks: {task['owner']}")
        owners.add(task["owner"])
        for other in assigned[index + 1 :]:
            if scopes_overlap(task["write_scope"], other["write_scope"]):
                raise OrchestrationError(
                    f"assigned write scopes overlap: {task['id']} and {other['id']}"
                )
    return tasks


def validate_plan(state: Dict[str, Any], plan: Path, require_approval: bool) -> None:
    """Validate plan linkage and optionally its execution approval."""
    metadata, _, _ = parse_document(plan)
    revision, phase = require_common(metadata)
    if state["plan_id"] != metadata["plan_id"]:
        raise OrchestrationError("orchestration plan_id does not match plan")
    if state["revision"] != revision:
        raise OrchestrationError("orchestration revision does not match plan")
    for state_field, plan_field in (
        ("execution_mode", "execution_mode"),
        ("max_workers", "max_workers"),
        ("topology", "agent_topology"),
    ):
        if plan_field in metadata and metadata[plan_field] != state[state_field]:
            raise OrchestrationError(f"orchestration {state_field} does not match plan")
    if require_approval:
        if phase not in {"APPROVED", "IN_PROGRESS"}:
            raise OrchestrationError(f"orchestration requires approved plan, found {phase}")
        if metadata["approved_revision"] != revision:
            raise OrchestrationError("approved_revision does not match plan revision")
        if not str(metadata["approved_at"]).strip() or not str(metadata["confirmation_record"]).strip():
            raise OrchestrationError("plan approval record is incomplete")


def append_event(state: Dict[str, Any], action: str, task: Dict[str, Any], detail: str) -> None:
    """Append a bounded audit event to scheduler state."""
    state["events"].append(
        {
            "at": now_utc(),
            "action": action,
            "task_id": task["id"],
            "owner": task["owner"],
            "detail": detail,
        }
    )


def require_task(tasks: Dict[str, Dict[str, Any]], task_id: str) -> Dict[str, Any]:
    """Return a task by ID or fail clearly."""
    if task_id not in tasks:
        raise OrchestrationError(f"unknown task: {task_id}")
    return tasks[task_id]


def dependencies_complete(task: Dict[str, Any], tasks: Dict[str, Dict[str, Any]]) -> bool:
    """Return whether every task dependency is completed."""
    return all(tasks[item]["status"] == "COMPLETED" for item in task["depends_on"])


def command_inspect(args: argparse.Namespace) -> None:
    """Print normalized scheduler state."""
    state = load_state(args.state)
    validate_state(state)
    print(json.dumps(state, ensure_ascii=False, indent=2))


def command_validate(args: argparse.Namespace) -> None:
    """Validate scheduler state and plan linkage."""
    state = load_state(args.state)
    tasks = validate_state(state)
    validate_plan(state, args.plan, require_approval=args.require_approval)
    print(f"valid orchestration state for {state['plan_id']} with {len(tasks)} tasks")


def command_ready(args: argparse.Namespace) -> None:
    """Print a maximal safe wave of dependency-ready tasks as JSON."""
    state = load_state(args.state)
    tasks = validate_state(state)
    validate_plan(state, args.plan, require_approval=True)
    active_scopes = [
        scope
        for task in tasks.values()
        if task["status"] == "ASSIGNED"
        for scope in task["write_scope"]
    ]
    selected: List[Dict[str, Any]] = []
    selected_scopes: List[str] = []
    available = max(0, state["max_workers"] - sum(
        1
        for task in tasks.values()
        if task["status"] == "ASSIGNED" and task["assignment_kind"] == "WORKER"
    ))
    for task in state["tasks"]:
        if len(selected) >= available:
            break
        if task["status"] != "PENDING" or not dependencies_complete(task, tasks):
            continue
        if args.agent_only and not task["agent_eligible"]:
            continue
        if scopes_overlap(task["write_scope"], active_scopes + selected_scopes):
            continue
        selected.append(task)
        selected_scopes.extend(task["write_scope"])
    print(json.dumps(selected, ensure_ascii=False, indent=2))


def command_assign(args: argparse.Namespace) -> None:
    """Assign one ready task to a worker."""
    state = load_state(args.state)
    tasks = validate_state(state)
    validate_plan(state, args.plan, require_approval=True)
    task = require_task(tasks, args.task_id)
    owner = require_string(args.owner, "owner")
    coordinator_assignment = args.coordinator
    if state["execution_mode"] == "SINGLE_AGENT" and not coordinator_assignment:
        raise OrchestrationError("SINGLE_AGENT mode does not permit worker assignment")
    if task["status"] != "PENDING":
        raise OrchestrationError(f"task {task['id']} is not pending")
    if not coordinator_assignment and not task["agent_eligible"]:
        raise OrchestrationError(f"task {task['id']} is not agent-eligible")
    if task["attempts"] >= state["max_attempts"]:
        raise OrchestrationError(f"task {task['id']} reached max_attempts")
    if not coordinator_assignment and state["execution_mode"] == "MANUAL_MULTI_AGENT":
        if not task["planned_owner"] or task["planned_owner"] != owner:
            raise OrchestrationError(
                f"manual assignment for {task['id']} must use planned_owner {task['planned_owner']}"
            )
    if not dependencies_complete(task, tasks):
        raise OrchestrationError(f"task {task['id']} has incomplete dependencies")
    assigned = [item for item in tasks.values() if item["status"] == "ASSIGNED"]
    assigned_workers = [item for item in assigned if item["assignment_kind"] == "WORKER"]
    if not coordinator_assignment and len(assigned_workers) >= state["max_workers"]:
        raise OrchestrationError("max_workers reached")
    if any(item["owner"] == owner for item in assigned):
        raise OrchestrationError(f"owner already has an active task: {owner}")
    for active in assigned:
        if scopes_overlap(task["write_scope"], active["write_scope"]):
            raise OrchestrationError(
                f"write scope conflicts with assigned task {active['id']}"
            )
    task.update(
        {
            "status": "ASSIGNED",
            "owner": owner,
            "assignment_kind": "COORDINATOR" if coordinator_assignment else "WORKER",
            "started_at": now_utc(),
            "attempts": task["attempts"] + 1,
            "block_reason": "",
        }
    )
    append_event(state, "assign", task, "worker assignment persisted")
    write_state(args.state, state)
    print(f"assigned {task['id']} to {owner} as {task['assignment_kind']}")


def command_complete(args: argparse.Namespace) -> None:
    """Complete an assigned task with coordinator-accepted evidence."""
    evidence = require_string(args.evidence, "evidence")
    state = load_state(args.state)
    tasks = validate_state(state)
    validate_plan(state, args.plan, require_approval=True)
    task = require_task(tasks, args.task_id)
    if task["status"] != "ASSIGNED":
        raise OrchestrationError(f"task {task['id']} is not assigned")
    task["status"] = "COMPLETED"
    task["evidence"].append(evidence)
    task["block_reason"] = ""
    append_event(state, "complete", task, evidence)
    write_state(args.state, state)
    print(f"completed {task['id']}")


def command_release(args: argparse.Namespace) -> None:
    """Release an assigned or resolved blocked task back to pending."""
    reason = require_string(args.reason, "reason")
    state = load_state(args.state)
    tasks = validate_state(state)
    validate_plan(state, args.plan, require_approval=True)
    task = require_task(tasks, args.task_id)
    if task["status"] not in {"ASSIGNED", "BLOCKED"}:
        raise OrchestrationError(f"task {task['id']} cannot be released from {task['status']}")
    previous_owner = task["owner"]
    task.update(
        {
            "status": "PENDING",
            "owner": "",
            "assignment_kind": "",
            "started_at": "",
            "block_reason": "",
        }
    )
    append_event(state, "release", task, f"{reason}; previous owner={previous_owner}")
    write_state(args.state, state)
    print(f"released {task['id']}")


def command_block(args: argparse.Namespace) -> None:
    """Block a pending or assigned task with a concrete reason."""
    reason = require_string(args.reason, "reason")
    state = load_state(args.state)
    tasks = validate_state(state)
    validate_plan(state, args.plan, require_approval=True)
    task = require_task(tasks, args.task_id)
    if task["status"] not in {"PENDING", "ASSIGNED"}:
        raise OrchestrationError(f"task {task['id']} cannot be blocked from {task['status']}")
    task["status"] = "BLOCKED"
    task["block_reason"] = reason
    append_event(state, "block", task, reason)
    write_state(args.state, state)
    print(f"blocked {task['id']}")


def add_plan_argument(parser: argparse.ArgumentParser) -> None:
    """Add the canonical plan argument to a command parser."""
    parser.add_argument("--plan", type=Path, required=True)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="print normalized state")
    inspect_parser.add_argument("state", type=Path)
    inspect_parser.set_defaults(handler=command_inspect)

    validate_parser = subparsers.add_parser("validate", help="validate state and plan linkage")
    validate_parser.add_argument("state", type=Path)
    add_plan_argument(validate_parser)
    validate_parser.add_argument("--require-approval", action="store_true")
    validate_parser.set_defaults(handler=command_validate)

    ready_parser = subparsers.add_parser("ready", help="print a safe ready-task wave")
    ready_parser.add_argument("state", type=Path)
    add_plan_argument(ready_parser)
    ready_parser.add_argument("--agent-only", action="store_true")
    ready_parser.set_defaults(handler=command_ready)

    assign_parser = subparsers.add_parser("assign", help="assign a ready task")
    assign_parser.add_argument("state", type=Path)
    assign_parser.add_argument("task_id")
    assign_parser.add_argument("--owner", required=True)
    assign_parser.add_argument("--coordinator", action="store_true")
    add_plan_argument(assign_parser)
    assign_parser.set_defaults(handler=command_assign)

    complete_parser = subparsers.add_parser("complete", help="complete an assigned task")
    complete_parser.add_argument("state", type=Path)
    complete_parser.add_argument("task_id")
    complete_parser.add_argument("--evidence", required=True)
    add_plan_argument(complete_parser)
    complete_parser.set_defaults(handler=command_complete)

    release_parser = subparsers.add_parser("release", help="release a task to pending")
    release_parser.add_argument("state", type=Path)
    release_parser.add_argument("task_id")
    release_parser.add_argument("--reason", required=True)
    add_plan_argument(release_parser)
    release_parser.set_defaults(handler=command_release)

    block_parser = subparsers.add_parser("block", help="block a task")
    block_parser.add_argument("state", type=Path)
    block_parser.add_argument("task_id")
    block_parser.add_argument("--reason", required=True)
    add_plan_argument(block_parser)
    block_parser.set_defaults(handler=command_block)
    return parser


def main() -> int:
    """Run the orchestration state command."""
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except (OSError, WorkflowError, OrchestrationError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
