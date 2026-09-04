#!/usr/bin/env python3
"""Manage structured task progress and localized plan views."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from orchestration_state import (
    InternalStateAccess,
    OrchestrationError,
    locked_state,
)
from workflow_state import WorkflowError, locked_plan, parse_document, write_document
from platform_io import configure_stdio


SCHEMA = "project-workflow/task-state/v1"
IMPLEMENTATION_STATES = {"NOT_STARTED", "IN_PROGRESS", "COMPLETED", "BLOCKED"}
VERIFICATION_STATES = {
    "NOT_STARTED",
    "IN_PROGRESS",
    "PARTIAL",
    "PASSED",
    "FAILED",
    "BLOCKED",
    "NOT_APPLICABLE",
}
SUPPORTED_LANGUAGES = {"zh-CN", "en-US"}
SUMMARY_START = "<!-- project-workflow:summary:start -->"
SUMMARY_END = "<!-- project-workflow:summary:end -->"
TASK_START = "<!-- project-workflow:task-status {task_id}:start -->"
TASK_END = "<!-- project-workflow:task-status {task_id}:end -->"
TASK_HEADING = re.compile(r"(?m)^##\s+(T[0-9]+)\b[^\n]*$")
LEGACY_STATUS = re.compile(r"(?m)^-\s*(?:状态|Status)\s*[:：]\s*\[([ xX~!\-])\]\s*\n?")
MUTATION_COMMANDS = {
    "migrate",
    "start-implementation",
    "complete-implementation",
    "block-implementation",
    "start-verification",
    "partial-verification",
    "pass-verification",
    "fail-verification",
    "block-verification",
    "skip-verification",
}


class TaskStateError(ValueError):
    """Report invalid task state or unsafe progress changes."""


def normalize_language(language: object) -> str:
    """Return one supported display language, falling back to English."""
    return language if isinstance(language, str) and language in SUPPORTED_LANGUAGES else "en-US"


def load_locale(language: str) -> Dict[str, Any]:
    """Load a complete bundled localization resource."""
    path = Path(__file__).resolve().parents[1] / "locales" / f"{normalize_language(language)}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TaskStateError(f"invalid localization resource: {path.name}") from exc
    if not isinstance(value, dict):
        raise TaskStateError(f"localization root must be an object: {path.name}")
    return value


def task_state_path(repo: Path, plan_id: str) -> Path:
    """Return the repository-owned task state path."""
    if not plan_id or not re.fullmatch(r"[A-Za-z0-9._-]+", plan_id):
        raise TaskStateError("plan_id must use letters, numbers, dot, underscore, or hyphen")
    return repo / ".codex/project-workflow" / plan_id / "state.json"


def parse_dependencies(section: str) -> List[str]:
    """Read compact dependency IDs from one legacy task section."""
    match = re.search(r"(?m)^-\s*(?:Depends-On|依赖)\s*[:：]\s*(.+?)\s*$", section)
    if not match or match.group(1).strip().lower() in {"无", "none", "n/a", "-"}:
        return []
    return re.findall(r"\bT[0-9]+\b", match.group(1))


def legacy_states(marker: str) -> Tuple[str, str]:
    """Conservatively map one v0.4 marker to the dual state model."""
    if marker in {"x", "X"}:
        return "COMPLETED", "PASSED"
    if marker == "~":
        return "IN_PROGRESS", "NOT_STARTED"
    if marker == "!":
        return "BLOCKED", "BLOCKED"
    if marker == "-":
        return "COMPLETED", "NOT_APPLICABLE"
    return "NOT_STARTED", "NOT_STARTED"


def tasks_from_plan(body: str) -> List[Dict[str, Any]]:
    """Build ordered task records from plan headings and legacy markers."""
    matches = list(TASK_HEADING.finditer(body))
    if not matches:
        raise TaskStateError("plan must contain at least one task heading such as ## T01")
    tasks: List[Dict[str, Any]] = []
    seen = set()
    for index, match in enumerate(matches):
        task_id = match.group(1)
        if task_id in seen:
            raise TaskStateError(f"duplicate task heading: {task_id}")
        seen.add(task_id)
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        section = body[match.end():end]
        status = LEGACY_STATUS.search(section)
        implementation, verification = legacy_states(status.group(1) if status else " ")
        tasks.append(
            {
                "id": task_id,
                "depends_on": parse_dependencies(section),
                "implementation_status": implementation,
                "verification_status": verification,
                "implementation_evidence": ["Migrated from legacy [x]"] if implementation == "COMPLETED" else [],
                "verification_evidence": ["Migrated from legacy [x]"] if verification == "PASSED" else [],
                "implementation_block_reason": "Migrated legacy blocker" if implementation == "BLOCKED" else "",
                "verification_block_reason": "Migrated legacy blocker" if verification == "BLOCKED" else "",
                "note": "",
            }
        )
    known = {task["id"] for task in tasks}
    for task in tasks:
        unknown = set(task["depends_on"]) - known
        if unknown:
            raise TaskStateError(f"unknown dependencies for {task['id']}: {', '.join(sorted(unknown))}")
    return tasks


def validate_state(state: object) -> Dict[str, Any]:
    """Validate persisted task state without coercing malformed values."""
    if not isinstance(state, dict):
        raise TaskStateError("task state root must be an object")
    if state.get("schema") != SCHEMA:
        raise TaskStateError(f"unsupported task state schema: {state.get('schema')}")
    version = state.get("state_version")
    if isinstance(version, bool) or not isinstance(version, int) or version < 1:
        raise TaskStateError("state_version must be a positive integer")
    revision = state.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise TaskStateError("revision must be a positive integer")
    if state.get("execution_mode") not in {"SINGLE_AGENT", "AUTO_MULTI_AGENT", "MANUAL_MULTI_AGENT"}:
        raise TaskStateError("unsupported execution_mode")
    state["display_language"] = normalize_language(state.get("display_language"))
    tasks = state.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise TaskStateError("tasks must be a non-empty array")
    known = set()
    active = 0
    for task in tasks:
        if not isinstance(task, dict) or not re.fullmatch(r"T[0-9]+", str(task.get("id", ""))):
            raise TaskStateError("every task must have a valid T-number id")
        if task["id"] in known:
            raise TaskStateError(f"duplicate task id: {task['id']}")
        known.add(task["id"])
        if task.get("implementation_status") not in IMPLEMENTATION_STATES:
            raise TaskStateError(f"unsupported implementation status for {task['id']}")
        if task.get("verification_status") not in VERIFICATION_STATES:
            raise TaskStateError(f"unsupported verification status for {task['id']}")
        for field in ("depends_on", "implementation_evidence", "verification_evidence"):
            if not isinstance(task.get(field), list) or not all(isinstance(item, str) for item in task[field]):
                raise TaskStateError(f"{field} must be a string array for {task['id']}")
        for field in ("implementation_block_reason", "verification_block_reason", "note"):
            if not isinstance(task.get(field), str):
                raise TaskStateError(f"{field} must be a string for {task['id']}")
        if task["implementation_status"] == "COMPLETED" and not task["implementation_evidence"]:
            raise TaskStateError(f"completed implementation requires evidence for {task['id']}")
        if task["implementation_status"] == "BLOCKED" and not task["implementation_block_reason"].strip():
            raise TaskStateError(f"blocked implementation requires a reason for {task['id']}")
        if task["verification_status"] in {"PARTIAL", "PASSED", "FAILED", "NOT_APPLICABLE"} and not task["verification_evidence"]:
            raise TaskStateError(f"verification result requires evidence for {task['id']}")
        if task["verification_status"] == "BLOCKED" and not task["verification_block_reason"].strip():
            raise TaskStateError(f"blocked verification requires a reason for {task['id']}")
        if task["verification_status"] in {"IN_PROGRESS", "PARTIAL", "PASSED", "FAILED", "NOT_APPLICABLE"} and task["implementation_status"] != "COMPLETED":
            raise TaskStateError(f"verification requires completed implementation for {task['id']}")
        active += task["implementation_status"] == "IN_PROGRESS"
    for task in tasks:
        if set(task["depends_on"]) - known:
            raise TaskStateError(f"unknown dependency for {task['id']}")
    graph = {task["id"]: task["depends_on"] for task in tasks}
    visiting = set()
    visited = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise TaskStateError("task dependencies must not contain a cycle")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in graph[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id)
    if state["execution_mode"] == "SINGLE_AGENT" and active > 1:
        raise TaskStateError("SINGLE_AGENT permits at most one implementation task in progress")
    return state


def load_state(path: Path, repo: Path) -> Dict[str, Any]:
    """Load validated state through descriptor-anchored repository I/O."""
    with InternalStateAccess(path, repo, create_parents=False) as access:
        return validate_state(access.load())


def state_exists(path: Path, repo: Path) -> bool:
    """Check state existence through descriptor-anchored repository I/O."""
    with InternalStateAccess(path, repo, create_parents=True) as access:
        return access.exists()


def validate_for_plan(plan: Path, repo: Path, final: bool = False) -> int:
    """Validate task-state linkage and optionally require final completion."""
    metadata, _, _ = parse_document(plan)
    plan_id = metadata.get("plan_id")
    revision = metadata.get("revision")
    if not isinstance(plan_id, str) or not plan_id:
        raise TaskStateError("plan frontmatter must contain plan_id")
    path = task_state_path(repo, plan_id)
    if not state_exists(path, repo):
        raise TaskStateError("v0.5 plan requires internal task state")
    with locked_state(path, repo=repo):
        state = load_state(path, repo)
        if state["plan_id"] != plan_id or state["revision"] != revision:
            raise TaskStateError("task state does not match plan identity or revision")
        incomplete = [
            task["id"]
            for task in state["tasks"]
            if task["implementation_status"] != "COMPLETED"
        ]
        unverified = [
            task["id"]
            for task in state["tasks"]
            if task["verification_status"] not in {"PASSED", "NOT_APPLICABLE"}
        ]
        if final and incomplete:
            raise TaskStateError("implementation is incomplete: " + ", ".join(incomplete))
        if final and unverified:
            raise TaskStateError("verification is incomplete: " + ", ".join(unverified))
        return state["state_version"]


def validate_final_for_plan(plan: Path, repo: Path) -> int:
    """Require every task to be implemented and acceptably verified."""
    return validate_for_plan(plan, repo, final=True)


def write_state(path: Path, repo: Path, state: Dict[str, Any]) -> None:
    """Validate and atomically persist state through the internal state directory."""
    validate_state(state)
    with InternalStateAccess(path, repo, create_parents=True) as access:
        access.write(json.dumps(state, ensure_ascii=False, indent=2) + "\n")


def replace_block(content: str, start: str, end: str, block: str, insertion: int) -> str:
    """Replace one controlled block or insert it at a known location."""
    pattern = re.compile(
        re.escape(start) + r".*?" + re.escape(end) + r"[^\S\r\n]*\n*",
        re.DOTALL,
    )
    matches = list(pattern.finditer(content))
    if len(matches) > 1:
        raise TaskStateError(f"duplicate controlled block: {start}")
    if matches:
        return content[:matches[0].start()] + block + content[matches[0].end():]
    return content[:insertion] + block + content[insertion:]


def summary_block(state: Dict[str, Any], locale: Dict[str, Any]) -> str:
    """Render deterministic aggregate progress from structured state."""
    tasks = state["tasks"]
    implementation = sum(task["implementation_status"] == "COMPLETED" for task in tasks)
    verification = sum(task["verification_status"] in {"PASSED", "NOT_APPLICABLE"} for task in tasks)
    return (
        f"{SUMMARY_START}\n"
        f"> **{locale['summary_title']}** · {locale['summary_implementation']} {implementation}/{len(tasks)} · "
        f"{locale['summary_verification']} {verification}/{len(tasks)}\n"
        f"{SUMMARY_END}\n\n"
    )


def task_block(task: Dict[str, Any], locale: Dict[str, Any]) -> str:
    """Render one localized task status block with stable icons."""
    lines = [
        TASK_START.format(task_id=task["id"]),
        f"- {locale['implementation_label']}：{locale['implementation'][task['implementation_status']]}",
        f"- {locale['verification_label']}：{locale['verification'][task['verification_status']]}",
    ]
    evidence = task["implementation_evidence"] + task["verification_evidence"]
    if evidence:
        lines.append(f"- {locale['evidence_label']}：" + "；".join(evidence))
    reasons = [reason for reason in (task["implementation_block_reason"], task["verification_block_reason"]) if reason]
    if reasons:
        lines.append(f"- {locale['reason_label']}：" + "；".join(dict.fromkeys(reasons)))
    lines.extend((TASK_END.format(task_id=task["id"]), ""))
    return "\n".join(lines) + "\n"


def render_body(body: str, state: Dict[str, Any]) -> str:
    """Render summary and task blocks without altering free-form prose."""
    locale = load_locale(state["display_language"])
    rendered = body
    heading = re.search(r"(?m)^#\s+.+$", rendered)
    if not heading:
        raise TaskStateError("plan must contain a level-one heading")
    insertion = heading.end()
    if rendered[insertion:insertion + 2] == "\n\n":
        insertion += 2
    else:
        insertion += 1
    rendered = replace_block(rendered, SUMMARY_START, SUMMARY_END, summary_block(state, locale), insertion)
    for task in state["tasks"]:
        heading_match = re.search(rf"(?m)^##\s+{re.escape(task['id'])}\b[^\n]*$", rendered)
        if not heading_match:
            raise TaskStateError(f"task heading missing from plan: {task['id']}")
        section_end_match = re.search(r"(?m)^##\s+T[0-9]+\b", rendered[heading_match.end():])
        section_end = heading_match.end() + section_end_match.start() if section_end_match else len(rendered)
        section = rendered[heading_match.end():section_end]
        section = LEGACY_STATUS.sub("", section, count=1)
        rendered = rendered[:heading_match.end()] + section + rendered[section_end:]
        insertion = heading_match.end() + (2 if rendered[heading_match.end():heading_match.end() + 2] == "\n\n" else 1)
        rendered = replace_block(
            rendered,
            TASK_START.format(task_id=task["id"]),
            TASK_END.format(task_id=task["id"]),
            task_block(task, locale),
            insertion,
        )
    return rendered


def write_plan_body(plan: Path, metadata: Dict[str, object], order: List[str], body: str) -> None:
    """Atomically replace a plan while preserving its existing mode."""
    write_document(plan, metadata, order, body)


def plan_context(args: argparse.Namespace) -> Tuple[Path, Dict[str, object], List[str], str, Path]:
    """Resolve and validate one repository-owned plan and its state path."""
    repo = args.repo.expanduser().resolve()
    plan = args.plan.expanduser()
    plan = (repo / plan).resolve() if not plan.is_absolute() else plan.resolve()
    try:
        plan.relative_to(repo)
    except ValueError as exc:
        raise TaskStateError("plan must be inside repository") from exc
    metadata, order, body = parse_document(plan)
    plan_id = metadata.get("plan_id")
    revision = metadata.get("revision")
    if not isinstance(plan_id, str) or not plan_id:
        raise TaskStateError("plan frontmatter must contain plan_id")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        raise TaskStateError("plan frontmatter must contain a positive revision")
    return plan, metadata, order, body, task_state_path(repo, plan_id)


def command_migrate(args: argparse.Namespace) -> None:
    """Create or reuse structured state and render the plan idempotently."""
    plan, metadata, order, body, path = plan_context(args)
    created = False
    existed = state_exists(path, args.repo)
    if existed:
        state = load_state(path, args.repo)
        if state["plan_id"] != metadata["plan_id"] or state["revision"] != metadata["revision"]:
            raise TaskStateError("task state does not match plan identity or revision")
    else:
        state = {
            "schema": SCHEMA,
            "plan_id": metadata["plan_id"],
            "revision": metadata["revision"],
            "display_language": normalize_language(args.display_language),
            "execution_mode": metadata.get("execution_mode", "SINGLE_AGENT"),
            "state_version": 1,
            "tasks": tasks_from_plan(body),
        }
        validate_state(state)
    rendered = render_body(body, state)
    if not existed:
        write_state(path, args.repo, state)
        created = True
    try:
        if rendered != body:
            write_plan_body(plan, metadata, order, rendered)
    except Exception:
        if created:
            with InternalStateAccess(path, args.repo, create_parents=False) as access:
                try:
                    access.unlink()
                except FileNotFoundError:
                    pass
        raise
    print(json.dumps(state, ensure_ascii=False, indent=2))


def get_task(state: Dict[str, Any], task_id: str) -> Dict[str, Any]:
    """Return one known task."""
    for task in state["tasks"]:
        if task["id"] == task_id:
            return task
    raise TaskStateError(f"unknown task: {task_id}")


def require_evidence(args: argparse.Namespace) -> List[str]:
    """Require at least one non-empty evidence item."""
    evidence = [item.strip() for item in args.evidence if item.strip()]
    if not evidence:
        raise TaskStateError("at least one --evidence value is required")
    return evidence


def command_update(args: argparse.Namespace) -> None:
    """Apply one legal state transition and refresh the localized view."""
    plan, metadata, order, body, path = plan_context(args)
    state = load_state(path, args.repo)
    if args.expected_version is not None and state["state_version"] != args.expected_version:
        raise TaskStateError(
            f"state version conflict: expected {args.expected_version}, found {state['state_version']}"
        )
    task = get_task(state, args.task_id)
    command = args.command
    if command == "start-implementation":
        if task["implementation_status"] not in {"NOT_STARTED", "BLOCKED"}:
            raise TaskStateError("implementation can start only from NOT_STARTED or BLOCKED")
        completed = {item["id"] for item in state["tasks"] if item["implementation_status"] == "COMPLETED"}
        if set(task["depends_on"]) - completed:
            raise TaskStateError("all dependencies must be implemented before starting")
        if state["execution_mode"] == "SINGLE_AGENT" and any(
            item["implementation_status"] == "IN_PROGRESS" and item["id"] != task["id"] for item in state["tasks"]
        ):
            raise TaskStateError("SINGLE_AGENT already has an implementation task in progress")
        task["implementation_status"] = "IN_PROGRESS"
        task["implementation_block_reason"] = ""
    elif command == "complete-implementation":
        if task["implementation_status"] != "IN_PROGRESS":
            raise TaskStateError("implementation can complete only from IN_PROGRESS")
        task["implementation_status"] = "COMPLETED"
        task["implementation_evidence"].extend(require_evidence(args))
    elif command == "block-implementation":
        if task["implementation_status"] not in {"NOT_STARTED", "IN_PROGRESS"} or not args.reason.strip():
            raise TaskStateError("implementation blocker requires an active/pending task and --reason")
        task["implementation_status"] = "BLOCKED"
        task["implementation_block_reason"] = args.reason.strip()
    elif command == "start-verification":
        if task["implementation_status"] != "COMPLETED":
            raise TaskStateError("verification requires completed implementation")
        if task["verification_status"] not in {"NOT_STARTED", "PARTIAL", "FAILED", "BLOCKED"}:
            raise TaskStateError("verification cannot start from its current state")
        task["verification_status"] = "IN_PROGRESS"
        task["verification_block_reason"] = ""
    elif command in {"partial-verification", "pass-verification", "fail-verification", "skip-verification"}:
        if task["implementation_status"] != "COMPLETED":
            raise TaskStateError("verification result requires completed implementation")
        if command != "skip-verification" and task["verification_status"] != "IN_PROGRESS":
            raise TaskStateError("verification result requires IN_PROGRESS")
        target = {
            "partial-verification": "PARTIAL",
            "pass-verification": "PASSED",
            "fail-verification": "FAILED",
            "skip-verification": "NOT_APPLICABLE",
        }[command]
        task["verification_status"] = target
        task["verification_evidence"].extend(require_evidence(args))
    elif command == "block-verification":
        if task["implementation_status"] != "COMPLETED" or not args.reason.strip():
            raise TaskStateError("verification blocker requires completed implementation and --reason")
        task["verification_status"] = "BLOCKED"
        task["verification_block_reason"] = args.reason.strip()
    else:
        raise TaskStateError(f"unsupported task command: {command}")
    state["state_version"] += 1
    validate_state(state)
    write_state(path, args.repo, state)
    write_plan_body(plan, metadata, order, render_body(body, state))
    print(json.dumps(state, ensure_ascii=False, indent=2))


def command_inspect(args: argparse.Namespace) -> None:
    """Print validated task state."""
    _, _, _, _, path = plan_context(args)
    print(json.dumps(load_state(path, args.repo), ensure_ascii=False, indent=2))


def command_render(args: argparse.Namespace) -> None:
    """Refresh the localized Markdown view from structured state."""
    plan, metadata, order, body, path = plan_context(args)
    state = load_state(path, args.repo)
    rendered = render_body(body, state)
    if rendered != body:
        write_plan_body(plan, metadata, order, rendered)
    print(f"rendered {len(state['tasks'])} tasks in {state['display_language']}")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, handler in (("inspect", command_inspect), ("render", command_render), ("migrate", command_migrate)):
        child = subparsers.add_parser(name)
        child.add_argument("plan", type=Path)
        child.add_argument("--repo", required=True, type=Path)
        if name == "migrate":
            child.add_argument("--display-language", default="en-US")
        child.set_defaults(handler=handler)
    for name in sorted(MUTATION_COMMANDS - {"migrate"}):
        child = subparsers.add_parser(name)
        child.add_argument("plan", type=Path)
        child.add_argument("task_id")
        child.add_argument("--repo", required=True, type=Path)
        child.add_argument("--expected-version", type=int)
        child.add_argument("--evidence", action="append", default=[])
        child.add_argument("--reason", default="")
        child.set_defaults(handler=command_update)
    return parser


def main() -> int:
    """Run a task-state command with stable public errors."""
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args()
    args.repo = args.repo.expanduser().resolve()
    try:
        plan, _, _, _, path = plan_context(args)
        if args.command in MUTATION_COMMANDS:
            with locked_plan(plan, repo=args.repo):
                with locked_state(path, repo=args.repo):
                    args.handler(args)
        else:
            args.handler(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
