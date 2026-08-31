#!/usr/bin/env python3
"""Run a quiet, read-only preflight for the Project Workflow plugin."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from orchestration_state import (
    OrchestrationError,
    load_state as load_orchestration_state,
    validate_final_state as validate_final_orchestration_state,
    validate_plan as validate_orchestration_plan,
    validate_state as validate_orchestration_state,
)
from workflow_state import (
    WorkflowError,
    detect_git,
    parse_document,
    policy_contract,
    require_approval_record,
    require_common,
    require_execution_vcs,
    requested_vcs_mode,
    resolve_vcs,
    rollback_evidence_verified,
    validate_completed_evidence,
)
from task_state import (
    TASK_HEADING,
    TaskStateError,
    state_exists as task_state_exists,
    task_state_path,
    validate_for_plan,
)


SCHEMA = "project-workflow/doctor/v1"
MANIFEST = Path(".codex-plugin/plugin.json")
REQUIRED_WORKFLOW_COMMANDS = (
    "init",
    "approve",
    "check-execute",
    "transition",
    "start-execution",
    "create-baseline",
    "complete",
    "resume",
    "validate",
    "experience",
)
REQUIRED_ORCHESTRATION_COMMANDS = (
    "init",
    "validate",
    "ready",
    "assign",
    "activate",
    "complete",
    "release",
    "block",
)
REQUIRED_TASK_COMMANDS = (
    "migrate",
    "inspect",
    "render",
    "start-implementation",
    "complete-implementation",
    "start-verification",
    "pass-verification",
)


def issue(code: str, severity: str, message: str) -> Dict[str, str]:
    """Build one stable diagnostic issue record."""
    return {"code": code, "severity": severity, "message": message}


def valid_plugin_root(path: Path) -> bool:
    """Return whether a path has the minimum Project Workflow plugin layout."""
    return (
        (path / MANIFEST).is_file()
        and (path / "scripts/workflow_state.py").is_file()
        and (path / "scripts/orchestration_state.py").is_file()
    )


def unique_paths(paths: Sequence[Path]) -> List[Path]:
    """Return existing path candidates in stable, de-duplicated order."""
    unique: List[Path] = []
    seen = set()
    for path in paths:
        resolved = path.expanduser().resolve()
        key = str(resolved)
        if key not in seen:
            unique.append(resolved)
            seen.add(key)
    return unique


def cache_candidates() -> List[Path]:
    """Find locally cached plugin roots without emitting search progress."""
    cache_root = Path.home() / ".codex/plugins/cache"
    if not cache_root.is_dir():
        return []
    return sorted(
        path.parent.parent
        for path in cache_root.glob("*/project-workflow/*/.codex-plugin/plugin.json")
    )


def locate_plugin_root(repo: Path, requested: Optional[Path]) -> Tuple[Optional[Path], bool]:
    """Resolve the plugin root, quietly recovering a stale preferred location."""
    environment_root = os.environ.get("PROJECT_WORKFLOW_PLUGIN_ROOT", "").strip()
    preferred = requested or (Path(environment_root) if environment_root else None)
    if preferred is not None and valid_plugin_root(preferred.expanduser().resolve()):
        return preferred.expanduser().resolve(), False

    authoritative = unique_paths(
        [Path(__file__).resolve().parents[1], repo / "plugins/project-workflow"]
    )
    authoritative = [path for path in authoritative if valid_plugin_root(path)]
    if authoritative:
        return authoritative[0], preferred is not None

    cached = [path for path in unique_paths(cache_candidates()) if valid_plugin_root(path)]
    if len(cached) == 1:
        return cached[0], preferred is not None
    return None, False


def load_manifest(plugin_root: Path) -> Tuple[str, Optional[Dict[str, str]]]:
    """Read and validate the plugin manifest version."""
    try:
        manifest = json.loads((plugin_root / MANIFEST).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return "", issue("PLUGIN_MANIFEST_INVALID", "BLOCKER", str(exc))
    version = manifest.get("version") if isinstance(manifest, dict) else None
    if not isinstance(version, str) or not version.strip():
        return "", issue(
            "PLUGIN_VERSION_INVALID", "BLOCKER", "plugin manifest version must be a string"
        )
    return version.strip(), None


def check_cli(script: Path, commands: Sequence[str]) -> Tuple[str, str]:
    """Validate a helper's top-level argparse contract through its public help."""
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "BLOCKED", str(exc)
    if result.returncode != 0:
        return "BLOCKED", (result.stderr or result.stdout).strip()
    missing = [command for command in commands if command not in result.stdout]
    if missing:
        return "BLOCKED", f"missing commands: {', '.join(missing)}"
    return "OK", ""


def check_cli_static(script: Path, commands: Sequence[str]) -> Tuple[str, str]:
    """Inspect an untrusted helper contract without importing or executing it."""
    try:
        if script.stat().st_size > 1_000_000:
            return "BLOCKED", "untrusted helper exceeds the static inspection limit"
        source = script.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        return "BLOCKED", str(exc)
    missing = [command for command in commands if command not in source]
    if missing:
        return "BLOCKED", f"missing commands: {', '.join(missing)}"
    return "OK", ""


def nearest_existing_path(path: Path) -> Path:
    """Return the nearest existing path for a not-yet-created target."""
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def writable_directory_target(path: Path) -> bool:
    """Return whether a directory exists or can be created at the target."""
    if path.exists():
        return path.is_dir() and os.access(path, os.W_OK | os.X_OK)
    parent = nearest_existing_path(path.parent)
    return parent.is_dir() and os.access(parent, os.W_OK | os.X_OK)


def safe_state_directory(repo: Path, state_directory: Path) -> bool:
    """Reject repository state paths containing symlink components."""
    current = repo
    for component in state_directory.relative_to(repo).parts:
        current = current / component
        if current.is_symlink():
            return False
    return True


def resolve_under_repo(repo: Path, supplied: Path) -> Path:
    """Resolve a repository input and reject lexical or symbolic-link escape."""
    resolved_repo = repo.expanduser().resolve()
    resolved = (
        supplied.expanduser().resolve()
        if supplied.is_absolute()
        else (resolved_repo / supplied).resolve()
    )
    try:
        resolved.relative_to(resolved_repo)
    except ValueError as exc:
        raise WorkflowError(f"path must be inside repository: {supplied}") from exc
    return resolved


def inspect_plan(
    repo: Path,
    plan_argument: Optional[Path],
    state_argument: Optional[Path],
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Check optional plan frontmatter and orchestration revision linkage."""
    result: Dict[str, Any] = {
        "status": "NOT_CHECKED",
        "path": None,
        "plan_id": None,
        "revision": None,
        "orchestration_status": "NOT_CHECKED",
        "orchestration_path": None,
        "task_state_status": "NOT_CHECKED",
        "task_state_path": None,
    }
    issues: List[Dict[str, str]] = []
    if plan_argument is None:
        if state_argument is not None:
            issues.append(
                issue("STATE_WITHOUT_PLAN", "BLOCKER", "--orchestration requires --plan")
            )
            result["status"] = "BLOCKED"
        return result, issues

    try:
        plan = resolve_under_repo(repo, plan_argument)
        result["path"] = str(plan)
        metadata, _, body = parse_document(plan)
        revision, phase = require_common(metadata)
        if phase in {"APPROVED", "IN_PROGRESS", "COMPLETED"}:
            require_approval_record(metadata, revision)
    except (OSError, WorkflowError) as exc:
        result["status"] = "BLOCKED"
        issues.append(issue("PLAN_INVALID", "BLOCKER", str(exc)))
        return result, issues
    result.update(
        {
            "status": "OK",
            "plan_id": metadata["plan_id"],
            "revision": revision,
        }
    )
    task_path = task_state_path(repo, str(metadata["plan_id"]))
    result["task_state_path"] = str(task_path)
    try:
        contract = policy_contract(metadata)
        if task_state_exists(task_path, repo):
            task_version = validate_for_plan(plan, repo, final=phase == "COMPLETED")
            if phase == "COMPLETED" and contract == "v0.5" and metadata.get(
                "final_task_state_version"
            ) != task_version:
                raise TaskStateError(
                    "completed plan does not bind the validated task state_version"
                )
            result["task_state_status"] = "OK"
        elif contract == "v0.5" and TASK_HEADING.search(body):
            raise TaskStateError("v0.5 plan requires internal task state")
        else:
            result["task_state_status"] = "MIGRATABLE"
    except (OSError, WorkflowError, OrchestrationError, TaskStateError) as exc:
        result["status"] = "BLOCKED"
        result["task_state_status"] = "BLOCKED"
        issues.append(issue("TASK_STATE_INVALID", "BLOCKER", str(exc)))
        return result, issues
    if phase == "COMPLETED":
        try:
            validate_completed_evidence(metadata, plan, repo)
        except (OSError, WorkflowError) as exc:
            result["status"] = "BLOCKED"
            issues.append(issue("FINAL_EVIDENCE_INVALID", "BLOCKER", str(exc)))
            return result, issues

    inferred_state = str(metadata.get("orchestration_state", "")).strip()
    state = state_argument or (Path(inferred_state) if inferred_state else None)
    if state is None:
        return result, issues
    try:
        state_path = resolve_under_repo(repo, state)
        result["orchestration_path"] = str(state_path)
        state_data = load_orchestration_state(state_path)
        if phase == "COMPLETED":
            validate_final_orchestration_state(state_data, plan, repo)
            if state_data.get("policy_contract") == "v0.4":
                bound_version = metadata.get("final_orchestration_state_version")
                if (
                    isinstance(bound_version, bool)
                    or not isinstance(bound_version, int)
                    or bound_version != state_data.get("state_version", 0)
                ):
                    raise OrchestrationError(
                        "completed plan does not bind the validated orchestration state_version"
                    )
        else:
            validate_orchestration_state(state_data, repo)
            validate_orchestration_plan(
                state_data,
                plan,
                require_approval=phase in {"APPROVED", "IN_PROGRESS"},
            )
    except (OSError, OrchestrationError, WorkflowError) as exc:
        result["status"] = "BLOCKED"
        result["orchestration_status"] = "BLOCKED"
        issues.append(issue("ORCHESTRATION_INCOMPATIBLE", "BLOCKER", str(exc)))
        return result, issues
    result["orchestration_status"] = "OK"
    return result, issues


def inspect_version_control(
    repo: Path,
    requested_argument: Optional[str],
    plan_argument: Optional[Path],
) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Resolve VCS capability and validate a persisted plan's evidence model."""
    metadata: Dict[str, object] = {}
    phase = ""
    issues: List[Dict[str, str]] = []
    if plan_argument is not None:
        try:
            metadata, _, _ = parse_document(resolve_under_repo(repo, plan_argument))
            _, phase = require_common(metadata)
        except (OSError, WorkflowError):
            return {
                "requested": None,
                "resolved": None,
                "git_available": False,
                "git_worktree": False,
                "rollback_capable": False,
                "status": "BLOCKED",
            }, issues
        if requested_argument is not None and requested_argument != requested_vcs_mode(metadata):
            issues.append(
                issue(
                    "VCS_MODE_CONFLICT",
                    "BLOCKER",
                    "--vcs-mode does not match the persisted plan",
                )
            )
    elif requested_argument is not None:
        metadata["vcs_mode"] = requested_argument

    requested: Optional[str] = None
    resolved: Optional[str] = None
    git_available = False
    git_worktree = False
    rollback_capable = False
    try:
        requested = requested_vcs_mode(metadata)
        if plan_argument is not None and phase in {"APPROVED", "IN_PROGRESS", "COMPLETED"}:
            require_execution_vcs(metadata, repo)
        resolved, git_available, git_worktree, rollback_capable = resolve_vcs(metadata, repo)
    except WorkflowError as exc:
        message = str(exc)
        if requested is not None and requested != "NONE":
            git_available, git_worktree = detect_git(repo)
            if "environment drift" in message:
                resolved = "GIT" if git_available and git_worktree else "NONE"
        try:
            rollback_capable = (
                bool(resolved == "GIT") or rollback_evidence_verified(metadata)
            )
        except WorkflowError:
            rollback_capable = False
        if "environment drift" in message:
            code = "VCS_ENVIRONMENT_DRIFT"
        elif "rollback" in message:
            code = "ROLLBACK_REQUIRED"
        elif "vcs_mode" in message or "resolved_vcs_mode" in message:
            code = "VCS_MODE_INVALID"
        else:
            code = "VCS_UNAVAILABLE"
        issues.append(issue(code, "BLOCKER", message))

    status = "BLOCKED" if issues else "OK"
    return {
        "requested": requested,
        "resolved": resolved,
        "git_available": git_available,
        "git_worktree": git_worktree,
        "rollback_capable": rollback_capable,
        "status": status,
    }, issues


def run_doctor(args: argparse.Namespace) -> Dict[str, Any]:
    """Collect stable preflight results without mutating the repository."""
    issues: List[Dict[str, str]] = []
    repo = args.repo.expanduser().resolve()
    repo_ok = repo.is_dir() and os.access(repo, os.R_OK | os.X_OK)
    state_directory = repo / ".codex/project-workflow"
    state_safe = repo_ok and safe_state_directory(repo, state_directory)
    state_writable = state_safe and writable_directory_target(state_directory)
    if not repo_ok:
        issues.append(issue("REPOSITORY_UNREADABLE", "BLOCKER", f"unreadable repo: {repo}"))
    elif not state_safe:
        issues.append(
            issue(
                "STATE_DIRECTORY_UNSAFE",
                "BLOCKER",
                f"state directory contains a symlink or non-directory component: {state_directory}",
            )
        )
    elif not state_writable:
        issues.append(
            issue(
                "STATE_DIRECTORY_NOT_WRITABLE",
                "BLOCKER",
                f"state directory is not writable: {state_directory}",
            )
        )

    plugin_root, recovered = locate_plugin_root(repo, args.plugin_root)
    version = ""
    plugin_status = "OK"
    if plugin_root is None:
        plugin_status = "BLOCKED"
        issues.append(
            issue("PLUGIN_NOT_FOUND", "BLOCKER", "no unique valid Project Workflow plugin root")
        )
    else:
        version, manifest_issue = load_manifest(plugin_root)
        if manifest_issue:
            plugin_status = "BLOCKED"
            issues.append(manifest_issue)
        trusted_plugin_root = Path(__file__).resolve().parents[1]
        if plugin_root != trusted_plugin_root:
            plugin_status = "BLOCKED"
            issues.append(
                issue(
                    "PLUGIN_ROOT_UNTRUSTED",
                    "BLOCKER",
                    "external plugin root is inspected statically and is never executed",
                )
            )

    cli: Dict[str, Any] = {
        "status": "NOT_CHECKED",
        "workflow_state": "NOT_CHECKED",
        "orchestration_state": "NOT_CHECKED",
        "task_state": "NOT_CHECKED",
    }
    if plugin_root is not None:
        trusted = plugin_root == Path(__file__).resolve().parents[1]
        checker = check_cli if trusted else check_cli_static
        workflow_status, workflow_detail = checker(
            plugin_root / "scripts/workflow_state.py", REQUIRED_WORKFLOW_COMMANDS
        )
        orchestration_status, orchestration_detail = checker(
            plugin_root / "scripts/orchestration_state.py", REQUIRED_ORCHESTRATION_COMMANDS
        )
        task_status, task_detail = checker(
            plugin_root / "scripts/task_state.py", REQUIRED_TASK_COMMANDS
        )
        cli.update(
            {
                "status": "OK"
                if workflow_status == orchestration_status == task_status == "OK"
                else "BLOCKED",
                "workflow_state": workflow_status,
                "orchestration_state": orchestration_status,
                "task_state": task_status,
            }
        )
        if workflow_detail:
            issues.append(issue("WORKFLOW_CLI_INVALID", "BLOCKER", workflow_detail))
        if orchestration_detail:
            issues.append(issue("ORCHESTRATION_CLI_INVALID", "BLOCKER", orchestration_detail))
        if task_detail:
            issues.append(issue("TASK_CLI_INVALID", "BLOCKER", task_detail))

    python_status = "OK" if sys.version_info >= (3, 9) else "BLOCKED"
    if python_status == "BLOCKED":
        issues.append(
            issue("PYTHON_UNSUPPORTED", "BLOCKER", "Python 3.9 or newer is required")
        )
    plan, plan_issues = inspect_plan(repo, args.plan, args.orchestration)
    issues.extend(plan_issues)
    version_control, vcs_issues = inspect_version_control(repo, args.vcs_mode, args.plan)
    issues.extend(vcs_issues)
    blocked = any(item["severity"] == "BLOCKER" for item in issues)
    return {
        "schema": SCHEMA,
        "status": "BLOCKED" if blocked else "OK",
        "exit_code": 2 if blocked else 0,
        "plugin": {
            "status": plugin_status,
            "root": str(plugin_root) if plugin_root else None,
            "version": version or None,
            "recovered": recovered,
        },
        "python": {
            "status": python_status,
            "version": ".".join(str(part) for part in sys.version_info[:3]),
        },
        "cli": cli,
        "repository": {
            "status": "OK" if repo_ok and state_writable else "BLOCKED",
            "root": str(repo),
            "state_directory": str(state_directory),
            "state_writable": state_writable,
        },
        "plan": plan,
        "version_control": version_control,
        "native_agents": {"status": "UNKNOWN", "capacity": None},
        "issues": issues,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the public Doctor command parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path, help="repository root to inspect")
    parser.add_argument("--plugin-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--plan", type=Path, help="optional plan path, relative to the repository")
    parser.add_argument("--vcs-mode", help="AUTO, GIT, or NONE; plan metadata wins when supplied")
    parser.add_argument(
        "--orchestration",
        type=Path,
        help="optional orchestration state path, relative to the repository",
    )
    parser.add_argument("--json", action="store_true", help="emit stable machine-readable output")
    return parser


def main() -> int:
    """Run Doctor and return a stable blocking-only exit code."""
    args = build_parser().parse_args()
    result = run_doctor(args)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    elif result["status"] == "OK":
        print(
            "Project Workflow doctor: OK "
            f"(plugin {result['plugin']['version']}, Python {result['python']['version']}, "
            "native agents UNKNOWN)."
        )
    else:
        codes = ", ".join(item["code"] for item in result["issues"])
        print(f"Project Workflow doctor: BLOCKED ({codes}).")
    return int(result["exit_code"])


if __name__ == "__main__":
    raise SystemExit(main())
