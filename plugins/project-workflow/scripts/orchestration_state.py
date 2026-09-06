#!/usr/bin/env python3
"""Manage durable multi-agent task scheduling state for Project Workflow."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import secrets
import stat
import sys
import tempfile
import time
import unicodedata
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from platform_io import SecureDirectory, configure_stdio, file_lock, require_capabilities

from workflow_state import WorkflowError, parse_document, private_lock_path, require_common


SCHEMA = "project-workflow/orchestration/v1"
VALID_MODES = {"AUTO_MULTI_AGENT", "SINGLE_AGENT", "MANUAL_MULTI_AGENT"}
VALID_TOPOLOGIES = {"SHARED_WORKSPACE", "ISOLATED_WORKTREE", "REMOTE_AGENT"}
VALID_TASK_STATES = {"PENDING", "ASSIGNED", "COMPLETED", "BLOCKED"}
VALID_ASSIGNMENT_KINDS = {"", "WORKER_PENDING", "WORKER", "COORDINATOR"}
VALID_SPAWN_STATUSES = {"", "PENDING", "RUNNING", "COMPLETED", "UNKNOWN", "NOT_APPLICABLE"}
VALID_RUNTIME_VERIFICATIONS = {"", "PENDING", "VERIFIED", "UNAVAILABLE", "NOT_APPLICABLE"}
VALID_PARALLELISM_POLICIES = {"LEGACY", "BENEFIT_GATED"}
VALID_TASK_ROLES = {
    "",
    "IMPLEMENTATION",
    "CONTRACT_VERIFIER",
    "DOCUMENTATION",
    "COORDINATOR",
    "MIGRATION",
}
VALID_EVENT_ACTIONS = {
    "assign",
    "spawn",
    "complete",
    "worker_stopped",
    "spawn_failed",
    "release",
    "block",
}
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
CURRENT_EVENT_FIELDS = {
    "at",
    "action",
    "task_id",
    "owner",
    "runtime_agent_id",
    "runtime_task_name",
    "detail",
}
LEGACY_EVENT_FIELDS = CURRENT_EVENT_FIELDS - {"runtime_agent_id", "runtime_task_name"}
MUTATION_COMMANDS = {"init", "assign", "activate", "complete", "release", "block"}
INTERNAL_STATE_ROOT = Path(".codex/project-workflow")
HAS_FD_FILESYSTEM_SUPPORT = (
    hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and all(
        function in os.supports_dir_fd
        for function in (os.open, os.mkdir, os.rename, os.unlink)
    )
)


class OrchestrationError(ValueError):
    """Report invalid scheduler state or an unsafe task transition."""


def now_utc() -> str:
    """Return a stable UTC timestamp without fractional seconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def lexical_absolute(path: Path) -> Path:
    """Return an absolute path without following its final or parent links."""
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def path_is_internal_lexically(path: Path, repo: Path) -> bool:
    """Return whether a lexical path names repository-owned scheduler state."""
    return path_is_within(lexical_absolute(path), repo / INTERNAL_STATE_ROOT)


class InternalStateAccess:
    """Bind state operations to a trusted cross-platform directory handle."""

    def __init__(self, path: Path, repo: Path, create_parents: bool) -> None:
        self.repo = repo.expanduser().resolve()
        self.path = require_internal_state_path(path, self.repo)
        self.name = self.path.name
        self.directory = SecureDirectory(self.path.parent, root=self.repo, create=create_parents)
        self.parent_fd = self.directory.parent_fd

    def close(self) -> None:
        """Release owned directory handles on either platform."""
        self.directory.close()
        self.parent_fd = -1

    def __enter__(self) -> "InternalStateAccess":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def matches(self, path: Path) -> bool:
        """Return whether a caller names this anchored state leaf."""
        return lexical_absolute(path) == self.path

    def open_regular(self, name: str, flags: int, mode: int = 0o600) -> int:
        """Open a literal regular child without following links."""
        return self.directory.open_regular(name, flags, mode)

    def exists(self) -> bool:
        """Check existence without following a redirected state entry."""
        try:
            descriptor = self.open_regular(self.name, os.O_RDONLY)
        except FileNotFoundError:
            return False
        os.close(descriptor)
        return True

    def load(self) -> Dict[str, Any]:
        """Read one complete JSON object through a protected descriptor."""
        try:
            descriptor = self.open_regular(self.name, os.O_RDONLY)
        except FileNotFoundError as exc:
            raise OrchestrationError(f"orchestration state does not exist: {self.path}") from exc
        try:
            with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
                state = json.load(handle)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OrchestrationError(f"invalid orchestration JSON: {exc}") from exc
        if not isinstance(state, dict):
            raise OrchestrationError("orchestration state root must be an object")
        return state

    def open_lock(self) -> int:
        """Open the stable lock used by all writers of this state."""
        return self.open_regular(f".{self.name}.lock", os.O_RDWR | os.O_CREAT)

    def write(self, content: str) -> None:
        """Flush and atomically publish UTF-8 bytes inside the held directory."""
        self.directory.write_atomic(self.name, content.encode("utf-8"))

    def unlink(self) -> None:
        """Remove the bound state during a failed migration without dir_fd."""
        self.directory.unlink(self.name)


def require_fd_filesystem_support() -> None:
    """Validate the available native backend, not a POSIX-only feature set."""
    require_capabilities()


_ACTIVE_STATE_ACCESS: ContextVar[Optional[InternalStateAccess]] = ContextVar(
    "orchestration_state_access",
    default=None,
)


@contextmanager
def bound_state_access(access: InternalStateAccess):
    """Expose one anchored state descriptor to existing helper call sites."""
    token = _ACTIVE_STATE_ACCESS.set(access)
    try:
        yield access
    finally:
        _ACTIVE_STATE_ACCESS.reset(token)


def load_state(path: Path) -> Dict[str, Any]:
    """Load a scheduler state document from JSON."""
    access = _ACTIVE_STATE_ACCESS.get()
    if access is not None and access.matches(path):
        return access.load()
    if not path.is_file():
        raise OrchestrationError(f"orchestration state does not exist: {path}")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise OrchestrationError(f"invalid orchestration JSON: {exc}") from exc
    if not isinstance(state, dict):
        raise OrchestrationError("orchestration state root must be an object")
    return state


def state_exists(path: Path) -> bool:
    """Check state existence through the active anchored descriptor when present."""
    access = _ACTIVE_STATE_ACCESS.get()
    return access.exists() if access is not None and access.matches(path) else path.exists()


def write_state(path: Path, state: Dict[str, Any], repo: Optional[Path] = None) -> None:
    """Atomically write normalized scheduler state."""
    current_version = state.get("state_version", 0)
    if isinstance(current_version, bool) or not isinstance(current_version, int) or current_version < 0:
        raise OrchestrationError("state_version must be a non-negative integer")
    state["state_version"] = current_version + 1
    state["updated_at"] = now_utc()
    content = json.dumps(state, ensure_ascii=False, indent=2) + "\n"
    access = _ACTIVE_STATE_ACCESS.get()
    if access is not None and access.matches(path):
        access.write(content)
        return
    if repo is not None:
        with InternalStateAccess(path, repo, create_parents=True) as one_shot_access:
            one_shot_access.write(content)
        return
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


@contextmanager
def locked_state(
    path: Path,
    timeout_seconds: float = 5.0,
    repo: Optional[Path] = None,
):
    """Hold a bounded native OS lock for one complete state mutation."""
    if repo is not None:
        with InternalStateAccess(path, repo, create_parents=True) as access:
            descriptor = access.open_lock()
            try:
                with file_lock(descriptor, timeout_seconds):
                    with bound_state_access(access):
                        yield access
            except TimeoutError as exc:
                raise OrchestrationError(f"timed out acquiring state lock: {path}") from exc
            finally:
                os.close(descriptor)
        return
    lock_path = private_lock_path(path, "orchestration")
    with SecureDirectory(lock_path.parent.resolve()) as directory:
        descriptor = directory.open_regular(lock_path.name, os.O_RDWR | os.O_CREAT)
        try:
            with file_lock(descriptor, timeout_seconds):
                yield
        except TimeoutError as exc:
            raise OrchestrationError(f"timed out acquiring state lock: {path}") from exc
        finally:
            os.close(descriptor)


def require_expected_version(path: Path, expected: Optional[int]) -> None:
    """Reject stale writers before they enter a read-modify-write operation."""
    if expected is None:
        return
    if expected < 0:
        raise OrchestrationError("expected_version must be a non-negative integer")
    current = 0 if not state_exists(path) else load_state(path).get("state_version", 0)
    if isinstance(current, bool) or not isinstance(current, int) or current < 0:
        raise OrchestrationError("state_version must be a non-negative integer")
    if current != expected:
        raise OrchestrationError(
            f"state version conflict: expected {expected}, found {current}"
        )


def require_string(value: Any, field: str, allow_empty: bool = False) -> str:
    """Validate and return a string field."""
    if not isinstance(value, str):
        raise OrchestrationError(f"{field} must be a string")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise OrchestrationError(f"{field} must not be empty")
    return normalized


def require_timestamp(value: Any, field: str, allow_empty: bool = False) -> str:
    """Validate a timezone-aware ISO-8601 timestamp string."""
    timestamp = require_string(value, field, allow_empty=allow_empty)
    if isinstance(value, str) and timestamp != value:
        raise OrchestrationError(
            f"{field} must be a timezone-aware ISO-8601 timestamp"
        )
    if not timestamp:
        return timestamp
    candidate = f"{timestamp[:-1]}+00:00" if timestamp.endswith("Z") else timestamp
    try:
        parsed = datetime.fromisoformat(candidate)
        offset = parsed.utcoffset()
    except (OverflowError, ValueError) as exc:
        raise OrchestrationError(
            f"{field} must be a timezone-aware ISO-8601 timestamp"
        ) from exc
    if parsed.tzinfo is None or offset is None:
        raise OrchestrationError(
            f"{field} must be a timezone-aware ISO-8601 timestamp"
        )
    return timestamp


def parse_timestamp(value: str) -> datetime:
    """Parse an already validated ISO-8601 timestamp for ordering checks."""
    candidate = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(candidate)


def path_is_within(path: Path, root: Path) -> bool:
    """Return whether one resolved path is contained by a resolved root."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def resolve_repo_path(repo: Path, supplied: Path) -> Path:
    """Resolve an absolute or repository-relative CLI path."""
    return supplied.expanduser().resolve() if supplied.is_absolute() else (repo / supplied).resolve()


def require_internal_state_path(path: Path, repo: Path) -> Path:
    """Require a writable state path under the repository-owned internal state root."""
    resolved_repo = repo.expanduser().resolve()
    supplied = path.expanduser() if path.is_absolute() else resolved_repo / path.expanduser()
    lexical_path = Path(os.path.abspath(str(supplied)))
    lexical_root = resolved_repo / INTERNAL_STATE_ROOT
    if not path_is_within(lexical_path, lexical_root):
        raise OrchestrationError(
            "historical orchestration state outside .codex/project-workflow is read-only; "
            "migrate it before mutation"
        )
    current = resolved_repo
    for component in lexical_path.relative_to(resolved_repo).parts[:-1]:
        current = current / component
        if current.is_symlink():
            raise OrchestrationError("orchestration state parent must not contain symlinks")
    if lexical_path.is_symlink():
        raise OrchestrationError("orchestration state file must not be a symlink")
    resolved_path = lexical_path.resolve()
    resolved_root = lexical_root.resolve()
    if not path_is_within(resolved_path, resolved_root):
        raise OrchestrationError("orchestration state path escapes the internal state root")
    return lexical_path


def repository_case_sensitive(repo: Optional[Path]) -> bool:
    """Detect case sensitivity from an existing repository path without writing probes."""
    if repo is None:
        return sys.platform not in ("darwin", "win32")
    resolved = repo.expanduser().resolve()
    parts = resolved.parts
    for index, component in enumerate(parts):
        if not any(character.isalpha() for character in component):
            continue
        swapped = "".join(
            character.swapcase() if character.isalpha() else character
            for character in component
        )
        candidate = Path(*parts[:index], swapped, *parts[index + 1 :])
        try:
            if candidate.exists() and os.path.samefile(candidate, resolved):
                return False
        except OSError:
            continue
    return True


def scope_collision_key(scope: str, repo: Optional[Path] = None) -> str:
    """Return the repository-volume comparison key for a canonical scope."""
    normalized = unicodedata.normalize("NFC", scope)
    return normalized if repository_case_sensitive(repo) else normalized.casefold()


def require_number(
    value: Any,
    field: str,
    minimum: float,
    maximum: float,
) -> float:
    """Validate a finite non-boolean numeric policy value."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise OrchestrationError(f"{field} must be a number")
    normalized = float(value)
    if not math.isfinite(normalized) or not minimum <= normalized <= maximum:
        raise OrchestrationError(
            f"{field} must be between {minimum:g} and {maximum:g}"
        )
    return normalized


def normalize_scope(scope: str, field: str) -> str:
    """Normalize a repository-relative literal write scope."""
    normalized = require_string(scope, field)
    if (
        normalized.startswith("/")
        or re.match(r"^[A-Za-z]:", normalized)
        or "\\" in normalized
    ):
        raise OrchestrationError(f"{field} must be repository-relative: {scope}")
    components = normalized.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise OrchestrationError(f"{field} must use canonical POSIX components: {scope}")
    if any(character in normalized for character in "*?[]{}"):
        raise OrchestrationError(f"{field} must be a literal path, not a glob: {scope}")
    return unicodedata.normalize("NFC", normalized)


def scopes_overlap(
    left: Iterable[str],
    right: Iterable[str],
    repo: Optional[Path] = None,
) -> bool:
    """Return whether two sets of literal repository scopes overlap."""
    for left_scope in left:
        for right_scope in right:
            left_key = scope_collision_key(left_scope, repo)
            right_key = scope_collision_key(right_scope, repo)
            if (
                left_key == right_key
                or left_key.startswith(f"{right_key}/")
                or right_key.startswith(f"{left_key}/")
            ):
                return True
    return False


def parallel_savings_percent(tasks: List[Dict[str, Any]]) -> Optional[float]:
    """Return proven parallel savings, or ``None`` when estimates are incomplete."""
    if len(tasks) < 2 or any(task["estimated_minutes"] <= 0 for task in tasks):
        return None
    serial_minutes = sum(task["estimated_minutes"] for task in tasks)
    parallel_minutes = max(task["estimated_minutes"] for task in tasks) + sum(
        task["coordination_minutes"] for task in tasks
    )
    return max(0.0, (serial_minutes - parallel_minutes) * 100.0 / serial_minutes)


def marginal_parallel_minutes(
    selected: List[Dict[str, Any]],
    candidate: Dict[str, Any],
) -> float:
    """Return the reduction in parallel net cost produced by one candidate."""
    if candidate["estimated_minutes"] <= 0:
        return float("-inf")
    if not selected:
        return -candidate["coordination_minutes"]
    current_max = max(task["estimated_minutes"] for task in selected)
    saved_work = min(current_max, candidate["estimated_minutes"])
    return saved_work - candidate["coordination_minutes"]


def benefit_gated_wave(
    state: Dict[str, Any],
    active_workers: List[Dict[str, Any]],
    candidates: List[Dict[str, Any]],
    repo: Optional[Path] = None,
) -> List[Dict[str, Any]]:
    """Choose a deterministic compatible wave that satisfies the persisted benefit gate."""
    available = state["max_workers"] - len(active_workers)
    if available <= 0:
        return []

    best_wave: List[Dict[str, Any]] = []
    best_key: Optional[Tuple[float, float, int, Tuple[str, ...]]] = None
    seeds = [list(active_workers)] if active_workers else [
        [candidate] for candidate in candidates
    ]
    for seed in seeds:
        selected = list(seed)
        selected_ids = {task["id"] for task in selected}
        selected_scopes = [scope for task in selected for scope in task["write_scope"]]
        remaining = [task for task in candidates if task["id"] not in selected_ids]
        while len(selected) < state["max_workers"]:
            compatible = [
                task
                for task in remaining
                if not scopes_overlap(task["write_scope"], selected_scopes, repo)
                and marginal_parallel_minutes(selected, task) > 0
            ]
            if not compatible:
                break
            candidate = max(
                compatible,
                key=lambda task: (
                    marginal_parallel_minutes(selected, task),
                    task["estimated_minutes"],
                    -task["coordination_minutes"],
                    task["id"],
                ),
            )
            selected.append(candidate)
            selected_scopes.extend(candidate["write_scope"])
            remaining.remove(candidate)
            savings = parallel_savings_percent(selected)
            if savings is None or savings < state["minimum_parallel_savings_percent"]:
                continue
            serial = sum(task["estimated_minutes"] for task in selected)
            parallel = max(task["estimated_minutes"] for task in selected) + sum(
                task["coordination_minutes"] for task in selected
            )
            key = (
                savings,
                serial - parallel,
                len(selected),
                tuple(task["id"] for task in selected),
            )
            if best_key is None or key > best_key:
                best_key = key
                best_wave = list(selected)

    if best_wave:
        active_ids = {task["id"] for task in active_workers}
        return sorted(
            (task for task in best_wave if task["id"] not in active_ids),
            key=lambda task: task["id"],
        )
    if not active_workers:
        independent = sorted(
            (task for task in candidates if task["independent_verification"]),
            key=lambda task: task["id"],
        )
        if independent:
            return independent[:1]
    return []


def validate_task(
    task: Any,
    index: int,
    repo: Optional[Path] = None,
    policy_contract: str = "legacy",
) -> Dict[str, Any]:
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
    scope_keys = {scope_collision_key(scope, repo) for scope in scopes}
    if len(scope_keys) != len(scopes):
        raise OrchestrationError(f"duplicate write scopes for {task_id}")
    if not isinstance(task["agent_eligible"], bool):
        raise OrchestrationError(f"agent_eligible for {task_id} must be boolean")
    if task["agent_eligible"] and not scopes:
        raise OrchestrationError(f"agent-eligible task {task_id} requires a write scope")

    owner = require_string(task["owner"], f"{task_id}.owner", allow_empty=True)
    started_at = require_timestamp(
        task["started_at"], f"{task_id}.started_at", allow_empty=True
    )
    if (
        isinstance(task["attempts"], bool)
        or not isinstance(task["attempts"], int)
        or task["attempts"] < 0
    ):
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
    task.setdefault("display_name", task_id)
    task["display_name"] = require_string(task["display_name"], f"{task_id}.display_name")
    task.setdefault("parallel_group", "")
    task.setdefault("planned_owner", "")
    task.setdefault("branch_or_worktree", "")
    task.setdefault("assignment_kind", "")
    task.setdefault("runtime_agent_id", "")
    task.setdefault("runtime_task_name", "")
    task.setdefault("spawn_status", "")
    task.setdefault("spawned_at", "")
    task.setdefault("finished_at", "")
    task.setdefault("runtime_verification", "")
    task.setdefault("estimated_minutes", 0)
    task.setdefault("coordination_minutes", 0)
    task.setdefault("critical_path", False)
    task.setdefault("role", "")
    task.setdefault("independent_verification", False)
    task["planned_owner"] = require_string(
        task["planned_owner"], f"{task_id}.planned_owner", allow_empty=True
    )
    assignment_kind = require_string(
        task["assignment_kind"], f"{task_id}.assignment_kind", allow_empty=True
    )
    if assignment_kind not in VALID_ASSIGNMENT_KINDS:
        raise OrchestrationError(f"invalid assignment_kind for {task_id}: {assignment_kind}")
    task["assignment_kind"] = assignment_kind
    for field in ("runtime_agent_id", "runtime_task_name"):
        task[field] = require_string(task[field], f"{task_id}.{field}", allow_empty=True)
    for field in ("spawned_at", "finished_at"):
        task[field] = require_timestamp(task[field], f"{task_id}.{field}", allow_empty=True)
    spawn_status = require_string(task["spawn_status"], f"{task_id}.spawn_status", allow_empty=True)
    if spawn_status not in VALID_SPAWN_STATUSES:
        raise OrchestrationError(f"invalid spawn_status for {task_id}: {spawn_status}")
    task["spawn_status"] = spawn_status
    runtime_verification = require_string(
        task["runtime_verification"], f"{task_id}.runtime_verification", allow_empty=True
    )
    if runtime_verification not in VALID_RUNTIME_VERIFICATIONS:
        raise OrchestrationError(
            f"invalid runtime_verification for {task_id}: {runtime_verification}"
        )
    task["runtime_verification"] = runtime_verification
    task["estimated_minutes"] = require_number(
        task["estimated_minutes"], f"{task_id}.estimated_minutes", 0, 1_000_000
    )
    task["coordination_minutes"] = require_number(
        task["coordination_minutes"], f"{task_id}.coordination_minutes", 0, 1_000_000
    )
    if not isinstance(task["critical_path"], bool):
        raise OrchestrationError(f"{task_id}.critical_path must be boolean")
    role = require_string(task["role"], f"{task_id}.role", allow_empty=True)
    if role not in VALID_TASK_ROLES:
        raise OrchestrationError(f"invalid role for {task_id}: {role}")
    task["role"] = role
    if not isinstance(task["independent_verification"], bool):
        raise OrchestrationError(f"{task_id}.independent_verification must be boolean")
    if task["independent_verification"]:
        if role != "CONTRACT_VERIFIER" or not task["agent_eligible"]:
            raise OrchestrationError(
                f"independent verifier {task_id} must be an agent-eligible CONTRACT_VERIFIER"
            )
    if status == "ASSIGNED" and not assignment_kind:
        raise OrchestrationError(f"assigned task {task_id} requires assignment_kind")
    if status == "PENDING" and assignment_kind:
        raise OrchestrationError(f"pending task {task_id} must not retain assignment_kind")
    runtime_fields = (
        task["runtime_agent_id"],
        task["runtime_task_name"],
        task["spawn_status"],
        task["spawned_at"],
        task["finished_at"],
        task["runtime_verification"],
    )
    if status == "PENDING" and any(runtime_fields):
        raise OrchestrationError(f"pending task {task_id} must not retain runtime fields")
    if assignment_kind == "WORKER_PENDING":
        if status not in {"ASSIGNED", "BLOCKED"} or spawn_status != "PENDING":
            raise OrchestrationError(
                f"reserved worker task {task_id} must be active with spawn_status PENDING"
            )
        if task["runtime_agent_id"] or task["runtime_task_name"] or task["spawned_at"]:
            raise OrchestrationError(f"reserved worker task {task_id} must not claim runtime identity")
        if runtime_verification != "PENDING":
            raise OrchestrationError(f"reserved worker task {task_id} requires PENDING verification")
    if assignment_kind == "WORKER":
        has_runtime_identity = bool(
            task["runtime_agent_id"] and task["runtime_task_name"] and task["spawned_at"]
        )
        if status in {"ASSIGNED", "BLOCKED"}:
            if not has_runtime_identity:
                raise OrchestrationError(
                    f"active worker task {task_id} requires native runtime identity"
                )
            if spawn_status != "RUNNING" or runtime_verification != "VERIFIED":
                raise OrchestrationError(
                    f"active worker task {task_id} requires verified RUNNING runtime"
                )
            if task["finished_at"]:
                raise OrchestrationError(
                    f"active worker task {task_id} must not have finished_at"
                )
        elif status == "COMPLETED":
            if policy_contract == "legacy" and not has_runtime_identity:
                # Existing v1 records predate runtime binding. Preserve them without inventing IDs.
                task["spawn_status"] = "UNKNOWN"
                task["runtime_verification"] = "UNAVAILABLE"
            elif not owner or not started_at or not has_runtime_identity or not task["finished_at"]:
                raise OrchestrationError(
                    f"completed worker task {task_id} requires complete native runtime identity "
                    "and timestamps"
                )
            elif spawn_status != "COMPLETED":
                raise OrchestrationError(
                    f"completed worker task {task_id} requires finished runtime evidence"
                )
            elif runtime_verification != "VERIFIED":
                raise OrchestrationError(
                    f"completed worker task {task_id} requires VERIFIED runtime"
                )
    if assignment_kind == "COORDINATOR":
        if (
            task["runtime_agent_id"]
            or task["runtime_task_name"]
            or task["spawned_at"]
            or task["finished_at"]
        ):
            raise OrchestrationError(f"coordinator task {task_id} must not claim worker runtime")
        task["spawn_status"] = "NOT_APPLICABLE"
        task["runtime_verification"] = "NOT_APPLICABLE"
    if task["spawned_at"] and started_at:
        if parse_timestamp(task["spawned_at"]) < parse_timestamp(started_at):
            raise OrchestrationError(f"{task_id}.spawned_at must not be before started_at")
    if task["finished_at"] and task["spawned_at"]:
        if parse_timestamp(task["finished_at"]) < parse_timestamp(task["spawned_at"]):
            raise OrchestrationError(f"{task_id}.finished_at must not be before spawned_at")
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


def task_holds_resources(task: Dict[str, Any]) -> bool:
    """Return whether a task still owns its slot and declared write scopes."""
    if task["status"] == "ASSIGNED":
        return True
    return (
        task["status"] == "BLOCKED"
        and task["assignment_kind"] in {"WORKER_PENDING", "WORKER"}
    )


def validate_event(
    event: Any,
    index: int,
    legacy: bool,
    task_ids: Set[str],
) -> Dict[str, Any]:
    """Validate one current or explicitly recognized historical audit event."""
    if not isinstance(event, dict):
        raise OrchestrationError(f"events[{index}] must be an object")
    fields = set(event)
    recognized = fields == CURRENT_EVENT_FIELDS or (
        legacy and fields == LEGACY_EVENT_FIELDS
    )
    if not recognized:
        raise OrchestrationError(f"events[{index}] has an unknown structure")
    require_timestamp(event["at"], f"events[{index}].at")
    action = require_string(event["action"], f"events[{index}].action")
    if action not in VALID_EVENT_ACTIONS:
        raise OrchestrationError(f"events[{index}].action is unknown: {action}")
    task_id = require_string(event["task_id"], f"events[{index}].task_id")
    if task_id not in task_ids:
        raise OrchestrationError(f"events[{index}].task_id references an unknown task")
    require_string(event["owner"], f"events[{index}].owner", allow_empty=True)
    require_string(event["detail"], f"events[{index}].detail")
    if fields == LEGACY_EVENT_FIELDS:
        event.setdefault("runtime_agent_id", "")
        event.setdefault("runtime_task_name", "")
    else:
        require_string(
            event["runtime_agent_id"],
            f"events[{index}].runtime_agent_id",
            allow_empty=True,
        )
        require_string(
            event["runtime_task_name"],
            f"events[{index}].runtime_task_name",
            allow_empty=True,
        )
    return event


def validate_state(
    state: Dict[str, Any],
    repo: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """Validate scheduler schema and return tasks indexed by ID."""
    missing = [field for field in ROOT_FIELDS if field not in state]
    if missing:
        raise OrchestrationError(f"missing root fields: {', '.join(missing)}")
    if state["schema"] != SCHEMA:
        raise OrchestrationError(f"unsupported orchestration schema: {state['schema']}")
    state.setdefault("state_version", 0)
    if (
        isinstance(state["state_version"], bool)
        or not isinstance(state["state_version"], int)
        or state["state_version"] < 0
    ):
        raise OrchestrationError("state_version must be a non-negative integer")
    require_string(state["plan_id"], "plan_id")
    if (
        isinstance(state["revision"], bool)
        or not isinstance(state["revision"], int)
        or state["revision"] < 1
    ):
        raise OrchestrationError("revision must be a positive integer")
    mode = require_string(state["execution_mode"], "execution_mode")
    if mode not in VALID_MODES:
        raise OrchestrationError(f"invalid execution_mode: {mode}")
    if (
        isinstance(state["max_workers"], bool)
        or not isinstance(state["max_workers"], int)
        or not 1 <= state["max_workers"] <= 64
    ):
        raise OrchestrationError("max_workers must be an integer between 1 and 64")
    state.setdefault("max_attempts", 2)
    if (
        isinstance(state["max_attempts"], bool)
        or not isinstance(state["max_attempts"], int)
        or not 1 <= state["max_attempts"] <= 100
    ):
        raise OrchestrationError("max_attempts must be an integer between 1 and 100")
    state.setdefault("parallelism_policy", "LEGACY")
    policy = require_string(state["parallelism_policy"], "parallelism_policy")
    if policy not in VALID_PARALLELISM_POLICIES:
        raise OrchestrationError(f"invalid parallelism_policy: {policy}")
    state["parallelism_policy"] = policy
    state.setdefault("minimum_parallel_savings_percent", 20)
    state["minimum_parallel_savings_percent"] = require_number(
        state["minimum_parallel_savings_percent"],
        "minimum_parallel_savings_percent",
        0,
        100,
    )
    state.setdefault("policy_contract", "legacy")
    policy_contract = require_string(state["policy_contract"], "policy_contract")
    if policy_contract not in {"legacy", "v0.4", "v0.5"}:
        raise OrchestrationError("policy_contract must be legacy, v0.4, or v0.5")
    state["policy_contract"] = policy_contract
    topology = require_string(state["topology"], "topology")
    if topology not in VALID_TOPOLOGIES:
        raise OrchestrationError(f"invalid topology: {topology}")
    if not isinstance(state["tasks"], list) or not state["tasks"]:
        raise OrchestrationError("tasks must be a non-empty list")
    if "events" in state and not isinstance(state["events"], list):
        raise OrchestrationError("events must be a list")
    state.setdefault("events", [])
    if "updated_at" in state:
        require_timestamp(state["updated_at"], "updated_at")

    tasks: Dict[str, Dict[str, Any]] = {}
    for index, raw_task in enumerate(state["tasks"]):
        task = validate_task(raw_task, index, repo, policy_contract)
        if task["id"] in tasks:
            raise OrchestrationError(f"duplicate task id: {task['id']}")
        tasks[task["id"]] = task
    for task in tasks.values():
        unknown = [item for item in task["depends_on"] if item not in tasks]
        if unknown:
            raise OrchestrationError(f"unknown dependencies for {task['id']}: {', '.join(unknown)}")
    detect_cycle(tasks)
    previous_event_at: Optional[datetime] = None
    for index, event in enumerate(state["events"]):
        validate_event(
            event,
            index,
            legacy=state["policy_contract"] == "legacy",
            task_ids=set(tasks),
        )
        event_at = parse_timestamp(event["at"])
        if previous_event_at is not None and event_at < previous_event_at:
            raise OrchestrationError("events must be in chronological order")
        previous_event_at = event_at

    independent_verifiers = [
        task for task in tasks.values() if task["independent_verification"]
    ]
    for verifier in independent_verifiers:
        for implementation in tasks.values():
            if implementation["id"] == verifier["id"]:
                continue
            if scopes_overlap(
                verifier["write_scope"], implementation["write_scope"], repo
            ):
                raise OrchestrationError(
                    f"contract verifier {verifier['id']} write scope overlaps "
                    f"task {implementation['id']}"
                )

    if mode == "MANUAL_MULTI_AGENT":
        for task in tasks.values():
            if task["agent_eligible"] and not task["planned_owner"]:
                raise OrchestrationError(
                    f"manual agent-eligible task {task['id']} requires planned_owner"
                )

    assigned = [task for task in tasks.values() if task_holds_resources(task)]
    assigned_workers = [
        task for task in assigned if task["assignment_kind"] in {"WORKER_PENDING", "WORKER"}
    ]
    if mode == "SINGLE_AGENT" and assigned_workers:
        raise OrchestrationError("SINGLE_AGENT mode permits coordinator-only execution")
    if len(assigned_workers) > state["max_workers"]:
        raise OrchestrationError("assigned worker count exceeds max_workers")
    active_runtime_ids: Set[str] = set()
    active_runtime_names: Set[str] = set()
    for task in assigned_workers:
        if task["assignment_kind"] != "WORKER":
            continue
        runtime_agent_id = task["runtime_agent_id"]
        runtime_task_name = task["runtime_task_name"]
        if runtime_agent_id in active_runtime_ids:
            raise OrchestrationError(
                f"duplicate active runtime_agent_id: {runtime_agent_id}"
            )
        if runtime_task_name in active_runtime_names:
            raise OrchestrationError(
                f"duplicate active runtime_task_name: {runtime_task_name}"
            )
        active_runtime_ids.add(runtime_agent_id)
        active_runtime_names.add(runtime_task_name)
    owners: Set[str] = set()
    for index, task in enumerate(assigned):
        if task["owner"] in owners:
            raise OrchestrationError(f"owner has multiple active tasks: {task['owner']}")
        owners.add(task["owner"])
        for other in assigned[index + 1 :]:
            if scopes_overlap(task["write_scope"], other["write_scope"], repo):
                raise OrchestrationError(
                    f"assigned write scopes overlap: {task['id']} and {other['id']}"
                )
    return tasks


def validate_plan(
    state: Dict[str, Any],
    plan: Path,
    require_approval: bool,
    final: bool = False,
) -> None:
    """Validate plan linkage and the requested lifecycle gate."""
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
    resolved_vcs_mode = metadata.get("resolved_vcs_mode", "")
    if resolved_vcs_mode == "NONE" and state["topology"] != "SHARED_WORKSPACE":
        raise OrchestrationError("VCS NONE requires SHARED_WORKSPACE topology")
    if "parallelism_policy" in metadata:
        plan_policy = metadata["parallelism_policy"]
        if state["policy_contract"] in {"v0.4", "v0.5"} and plan_policy != state["parallelism_policy"]:
            raise OrchestrationError("orchestration parallelism_policy does not match plan")
    workflow_profile = metadata.get("workflow_profile", "FULL")
    if workflow_profile not in {"LIGHT", "STANDARD", "FULL"}:
        raise OrchestrationError(f"invalid workflow_profile: {workflow_profile}")
    if (
        state["policy_contract"] in {"v0.4", "v0.5"}
        and workflow_profile == "FULL"
    ):
        if not any(task["independent_verification"] for task in state["tasks"]):
            raise OrchestrationError("FULL workflow requires an independent contract verifier")
    if final:
        if phase not in {"IN_PROGRESS", "COMPLETED"}:
            raise OrchestrationError(
                f"final validation requires in-progress or completed plan, found {phase}"
            )
    elif require_approval:
        if phase not in {"APPROVED", "IN_PROGRESS"}:
            raise OrchestrationError(f"orchestration requires approved plan, found {phase}")
    if require_approval or final:
        if metadata["approved_revision"] != revision:
            raise OrchestrationError("approved_revision does not match plan revision")
        if not str(metadata["approved_at"]).strip() or not str(metadata["confirmation_record"]).strip():
            raise OrchestrationError("plan approval record is incomplete")


def validate_final_state(
    state: Dict[str, Any],
    plan: Path,
    repo: Optional[Path] = None,
) -> Dict[str, Dict[str, Any]]:
    """Validate complete scheduler evidence for workflow completion or Doctor."""
    tasks = validate_state(state, repo)
    validate_plan(state, plan, require_approval=False, final=True)
    incomplete = [
        task["id"] for task in tasks.values() if task["status"] != "COMPLETED"
    ]
    if incomplete:
        raise OrchestrationError(
            f"final validation requires completed tasks: {', '.join(incomplete)}"
        )
    return tasks


def append_event(state: Dict[str, Any], action: str, task: Dict[str, Any], detail: str) -> None:
    """Append a bounded audit event to scheduler state."""
    state["events"].append(
        {
            "at": now_utc(),
            "action": action,
            "task_id": task["id"],
            "owner": task["owner"],
            "runtime_agent_id": task.get("runtime_agent_id", ""),
            "runtime_task_name": task.get("runtime_task_name", ""),
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
    validate_state(state, args.repo)
    print(json.dumps(state, ensure_ascii=False, indent=2))


def parse_initial_task(raw_task: str) -> Dict[str, Any]:
    """Expand one compact task argument into normalized scheduler state."""
    try:
        supplied = json.loads(raw_task)
    except json.JSONDecodeError as exc:
        raise OrchestrationError(f"invalid --task JSON: {exc}") from exc
    if not isinstance(supplied, dict):
        raise OrchestrationError("--task JSON must be an object")
    allowed = {
        "id",
        "display_name",
        "depends_on",
        "write_scope",
        "agent_eligible",
        "parallel_group",
        "planned_owner",
        "branch_or_worktree",
        "estimated_minutes",
        "coordination_minutes",
        "critical_path",
        "role",
        "independent_verification",
    }
    unknown = sorted(set(supplied) - allowed)
    if unknown:
        raise OrchestrationError(f"unsupported --task fields: {', '.join(unknown)}")
    for required in ("id", "depends_on", "write_scope", "agent_eligible"):
        if required not in supplied:
            raise OrchestrationError(f"--task is missing required field: {required}")
    task = {
        "id": supplied["id"],
        "display_name": supplied.get("display_name", supplied["id"]),
        "status": "PENDING",
        "depends_on": supplied["depends_on"],
        "write_scope": supplied["write_scope"],
        "agent_eligible": supplied["agent_eligible"],
        "owner": "",
        "started_at": "",
        "attempts": 0,
        "evidence": [],
        "block_reason": "",
        "parallel_group": supplied.get("parallel_group", ""),
        "planned_owner": supplied.get("planned_owner", ""),
        "branch_or_worktree": supplied.get("branch_or_worktree", ""),
        "assignment_kind": "",
        "runtime_agent_id": "",
        "runtime_task_name": "",
        "spawn_status": "",
        "spawned_at": "",
        "finished_at": "",
        "runtime_verification": "",
        "estimated_minutes": supplied.get("estimated_minutes", 0),
        "coordination_minutes": supplied.get("coordination_minutes", 0),
        "critical_path": supplied.get("critical_path", False),
        "role": supplied.get("role", ""),
        "independent_verification": supplied.get("independent_verification", False),
    }
    validate_task(task, 0)
    return task


def command_init(args: argparse.Namespace) -> None:
    """Create internal scheduler state without exposing it as an edited artifact."""
    if state_exists(args.state) and not args.replace:
        raise OrchestrationError(f"orchestration state already exists: {args.state}")
    previous_version = 0
    if state_exists(args.state):
        previous = load_state(args.state)
        previous_version = previous.get("state_version", 0)
        if (
            isinstance(previous_version, bool)
            or not isinstance(previous_version, int)
            or previous_version < 0
        ):
            raise OrchestrationError("state_version must be a non-negative integer")
    metadata, _, _ = parse_document(args.plan)
    revision, _ = require_common(metadata)
    required_metadata = ("execution_mode", "max_workers", "agent_topology")
    missing = [field for field in required_metadata if field not in metadata]
    if missing:
        raise OrchestrationError(f"plan is missing orchestration fields: {', '.join(missing)}")
    state = {
        "schema": SCHEMA,
        "plan_id": metadata["plan_id"],
        "revision": revision,
        "execution_mode": metadata["execution_mode"],
        "max_workers": metadata["max_workers"],
        "max_attempts": args.max_attempts,
        "topology": metadata["agent_topology"],
        "parallelism_policy": metadata.get("parallelism_policy", "LEGACY"),
        "minimum_parallel_savings_percent": metadata.get(
            "minimum_parallel_savings_percent", 20
        ),
        "policy_contract": metadata.get("policy_contract", "v0.4"),
        "state_version": previous_version,
        "tasks": [parse_initial_task(raw_task) for raw_task in args.task],
        "events": [],
    }
    validate_state(state, args.repo)
    validate_plan(state, args.plan, require_approval=False)
    write_state(args.state, state, args.repo)
    print(f"initialized orchestration state for {state['plan_id']} with {len(state['tasks'])} tasks")


def command_validate(args: argparse.Namespace) -> None:
    """Validate scheduler state and plan linkage."""
    state = load_state(args.state)
    if args.final:
        tasks = validate_final_state(state, args.plan, args.repo)
    else:
        tasks = validate_state(state, args.repo)
        validate_plan(
            state,
            args.plan,
            require_approval=args.require_approval,
        )
    print(f"valid orchestration state for {state['plan_id']} with {len(tasks)} tasks")


def command_ready(args: argparse.Namespace) -> None:
    """Print a maximal safe wave of dependency-ready tasks as JSON."""
    state = load_state(args.state)
    tasks = validate_state(state, args.repo)
    validate_plan(state, args.plan, require_approval=True)
    active_scopes = [
        scope
        for task in tasks.values()
        if task_holds_resources(task)
        for scope in task["write_scope"]
    ]
    active_workers = [
        task
        for task in tasks.values()
        if task_holds_resources(task)
        and task["assignment_kind"] in {"WORKER_PENDING", "WORKER"}
    ]
    available = max(0, state["max_workers"] - len(active_workers))
    candidates = list(state["tasks"])
    if state["parallelism_policy"] == "BENEFIT_GATED":
        candidates.sort(
            key=lambda item: (
                not item["critical_path"],
                -item["estimated_minutes"],
                item["id"],
            )
        )
    ready_candidates: List[Dict[str, Any]] = []
    for task in candidates:
        if task["status"] != "PENDING" or not dependencies_complete(task, tasks):
            continue
        if args.agent_only and not task["agent_eligible"]:
            continue
        if scopes_overlap(task["write_scope"], active_scopes, args.repo):
            continue
        ready_candidates.append(task)
    if args.agent_only and state["parallelism_policy"] == "BENEFIT_GATED":
        selected = benefit_gated_wave(
            state, active_workers, ready_candidates, args.repo
        )
    else:
        selected = []
        selected_scopes: List[str] = []
        for task in ready_candidates:
            if len(selected) >= available:
                break
            if scopes_overlap(task["write_scope"], selected_scopes, args.repo):
                continue
            selected.append(task)
            selected_scopes.extend(task["write_scope"])
    print(json.dumps(selected, ensure_ascii=False, indent=2))


def command_assign(args: argparse.Namespace) -> None:
    """Assign one ready task to a worker."""
    state = load_state(args.state)
    tasks = validate_state(state, args.repo)
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
    if not coordinator_assignment and state["parallelism_policy"] == "BENEFIT_GATED":
        active_workers = [
            item
            for item in tasks.values()
            if task_holds_resources(item)
            and item["assignment_kind"] in {"WORKER_PENDING", "WORKER"}
        ]
        active_scopes = [
            scope
            for item in tasks.values()
            if task_holds_resources(item)
            for scope in item["write_scope"]
        ]
        ready_candidates = [
            item
            for item in tasks.values()
            if item["status"] == "PENDING"
            and item["agent_eligible"]
            and dependencies_complete(item, tasks)
            and not scopes_overlap(item["write_scope"], active_scopes, args.repo)
        ]
        allowed_ids = {
            item["id"]
            for item in benefit_gated_wave(
                state, active_workers, ready_candidates, args.repo
            )
        }
        if task["id"] not in allowed_ids:
            raise OrchestrationError(
                f"task {task['id']} is not in the current benefit-approved worker wave"
            )
    if task["attempts"] >= state["max_attempts"]:
        raise OrchestrationError(f"task {task['id']} reached max_attempts")
    if not coordinator_assignment and state["execution_mode"] == "MANUAL_MULTI_AGENT":
        if not task["planned_owner"] or task["planned_owner"] != owner:
            raise OrchestrationError(
                f"manual assignment for {task['id']} must use planned_owner {task['planned_owner']}"
            )
    if not dependencies_complete(task, tasks):
        raise OrchestrationError(f"task {task['id']} has incomplete dependencies")
    assigned = [item for item in tasks.values() if task_holds_resources(item)]
    assigned_workers = [
        item for item in assigned if item["assignment_kind"] in {"WORKER_PENDING", "WORKER"}
    ]
    if not coordinator_assignment and len(assigned_workers) >= state["max_workers"]:
        raise OrchestrationError("max_workers reached")
    if any(item["owner"] == owner for item in assigned):
        raise OrchestrationError(f"owner already has an active task: {owner}")
    for active in assigned:
        if scopes_overlap(task["write_scope"], active["write_scope"], args.repo):
            raise OrchestrationError(
                f"write scope conflicts with assigned task {active['id']}"
            )
    task.update(
        {
            "status": "ASSIGNED",
            "owner": owner,
            "assignment_kind": "COORDINATOR" if coordinator_assignment else "WORKER_PENDING",
            "started_at": now_utc(),
            "attempts": task["attempts"] + 1,
            "block_reason": "",
            "runtime_agent_id": "",
            "runtime_task_name": "",
            "spawn_status": "NOT_APPLICABLE" if coordinator_assignment else "PENDING",
            "spawned_at": "",
            "finished_at": "",
            "runtime_verification": "NOT_APPLICABLE" if coordinator_assignment else "PENDING",
        }
    )
    detail = "coordinator assignment persisted" if coordinator_assignment else (
        "worker slot reserved; native spawn and runtime binding required"
    )
    append_event(state, "assign", task, detail)
    write_state(args.state, state, args.repo)
    print(f"assigned {task['id']} to {owner} as {task['assignment_kind']}")


def command_activate(args: argparse.Namespace) -> None:
    """Bind a reserved task to a successfully spawned native Codex worker."""
    runtime_agent_id = require_string(args.runtime_agent_id, "runtime_agent_id")
    runtime_task_name = require_string(args.runtime_task_name, "runtime_task_name")
    state = load_state(args.state)
    tasks = validate_state(state, args.repo)
    validate_plan(state, args.plan, require_approval=True)
    task = require_task(tasks, args.task_id)
    if task["status"] != "ASSIGNED" or task["assignment_kind"] != "WORKER_PENDING":
        raise OrchestrationError(f"task {task['id']} is not awaiting native worker binding")
    for active in tasks.values():
        if active["id"] == task["id"] or not task_holds_resources(active):
            continue
        if active["assignment_kind"] != "WORKER":
            continue
        if active["runtime_agent_id"] == runtime_agent_id:
            raise OrchestrationError(
                f"duplicate active runtime_agent_id: {runtime_agent_id}"
            )
        if active["runtime_task_name"] == runtime_task_name:
            raise OrchestrationError(
                f"duplicate active runtime_task_name: {runtime_task_name}"
            )
    task.update(
        {
            "assignment_kind": "WORKER",
            "runtime_agent_id": runtime_agent_id,
            "runtime_task_name": runtime_task_name,
            "spawn_status": "RUNNING",
            "spawned_at": now_utc(),
            "runtime_verification": "VERIFIED",
        }
    )
    append_event(state, "spawn", task, "native Codex worker bound to reserved task")
    write_state(args.state, state, args.repo)
    print(f"activated {task['id']} with native worker {runtime_task_name}")


def command_complete(args: argparse.Namespace) -> None:
    """Complete an assigned task with coordinator-accepted evidence."""
    evidence = require_string(args.evidence, "evidence")
    state = load_state(args.state)
    tasks = validate_state(state, args.repo)
    validate_plan(state, args.plan, require_approval=True)
    task = require_task(tasks, args.task_id)
    if task["status"] != "ASSIGNED":
        raise OrchestrationError(f"task {task['id']} is not assigned")
    if task["assignment_kind"] == "WORKER_PENDING":
        raise OrchestrationError(
            f"task {task['id']} cannot complete before native worker activation"
        )
    if task["assignment_kind"] == "WORKER":
        runtime_agent_id = require_string(
            args.runtime_agent_id or "", "runtime_agent_id", allow_empty=True
        )
        if not runtime_agent_id or runtime_agent_id != task["runtime_agent_id"]:
            raise OrchestrationError(
                f"task {task['id']} completion requires matching runtime_agent_id"
            )
        task["spawn_status"] = "COMPLETED"
        task["finished_at"] = now_utc()
    task["status"] = "COMPLETED"
    task["evidence"].append(evidence)
    task["block_reason"] = ""
    append_event(state, "complete", task, evidence)
    write_state(args.state, state, args.repo)
    print(f"completed {task['id']}")


def command_release(args: argparse.Namespace) -> None:
    """Release an assigned or resolved blocked task back to pending."""
    reason = require_string(args.reason, "reason")
    state = load_state(args.state)
    tasks = validate_state(state, args.repo)
    validate_plan(state, args.plan, require_approval=True)
    task = require_task(tasks, args.task_id)
    if task["status"] not in {"ASSIGNED", "BLOCKED"}:
        raise OrchestrationError(f"task {task['id']} cannot be released from {task['status']}")
    if args.spawn_failed and task["assignment_kind"] != "WORKER_PENDING":
        raise OrchestrationError("--spawn-failed requires a reserved worker task")
    if task["assignment_kind"] == "WORKER_PENDING" and not args.spawn_failed:
        raise OrchestrationError("reserved worker release requires --spawn-failed")
    if task["assignment_kind"] == "WORKER":
        runtime_agent_id = require_string(
            args.runtime_agent_id or "", "runtime_agent_id", allow_empty=True
        )
        stopped_evidence = require_string(
            args.stopped_evidence or "", "stopped_evidence", allow_empty=True
        )
        if not runtime_agent_id or runtime_agent_id != task["runtime_agent_id"]:
            raise OrchestrationError(
                f"task {task['id']} release requires matching runtime_agent_id"
            )
        if not stopped_evidence:
            raise OrchestrationError(
                f"task {task['id']} release requires stopped_evidence"
            )
        append_event(state, "worker_stopped", task, stopped_evidence)
    previous_owner = task["owner"]
    action = "spawn_failed" if args.spawn_failed else "release"
    append_event(state, action, task, f"{reason}; previous owner={previous_owner}")
    task.update(
        {
            "status": "PENDING",
            "owner": "",
            "assignment_kind": "",
            "started_at": "",
            "block_reason": "",
            "runtime_agent_id": "",
            "runtime_task_name": "",
            "spawn_status": "",
            "spawned_at": "",
            "finished_at": "",
            "runtime_verification": "",
        }
    )
    write_state(args.state, state, args.repo)
    print(f"released {task['id']}")


def command_block(args: argparse.Namespace) -> None:
    """Block a pending or assigned task with a concrete reason."""
    reason = require_string(args.reason, "reason")
    state = load_state(args.state)
    tasks = validate_state(state, args.repo)
    validate_plan(state, args.plan, require_approval=True)
    task = require_task(tasks, args.task_id)
    if task["status"] not in {"PENDING", "ASSIGNED"}:
        raise OrchestrationError(f"task {task['id']} cannot be blocked from {task['status']}")
    task["status"] = "BLOCKED"
    task["block_reason"] = reason
    append_event(state, "block", task, reason)
    write_state(args.state, state, args.repo)
    print(f"blocked {task['id']}")


def add_plan_argument(parser: argparse.ArgumentParser) -> None:
    """Add the canonical plan argument to a command parser."""
    parser.add_argument("--plan", type=Path, required=True)


def add_repo_argument(parser: argparse.ArgumentParser) -> None:
    """Add explicit repository context while preserving read-only legacy usage."""
    parser.add_argument("--repo", type=Path)


def add_mutation_contract(parser: argparse.ArgumentParser) -> None:
    """Add optimistic-concurrency input shared by state-changing commands."""
    parser.add_argument("--expected-version", type=int)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser(
        "init", help="create internal scheduler state from compact task arguments"
    )
    init_parser.add_argument("state", type=Path)
    add_plan_argument(init_parser)
    add_repo_argument(init_parser)
    init_parser.add_argument("--task", action="append", required=True)
    init_parser.add_argument("--max-attempts", type=int, default=2)
    init_parser.add_argument("--replace", action="store_true")
    add_mutation_contract(init_parser)
    init_parser.set_defaults(handler=command_init)

    inspect_parser = subparsers.add_parser("inspect", help="print normalized state")
    inspect_parser.add_argument("state", type=Path)
    add_repo_argument(inspect_parser)
    inspect_parser.set_defaults(handler=command_inspect)

    validate_parser = subparsers.add_parser("validate", help="validate state and plan linkage")
    validate_parser.add_argument("state", type=Path)
    add_plan_argument(validate_parser)
    add_repo_argument(validate_parser)
    validation_mode = validate_parser.add_mutually_exclusive_group()
    validation_mode.add_argument("--require-approval", action="store_true")
    validation_mode.add_argument("--final", action="store_true")
    validate_parser.set_defaults(handler=command_validate)

    ready_parser = subparsers.add_parser("ready", help="print a safe ready-task wave")
    ready_parser.add_argument("state", type=Path)
    add_plan_argument(ready_parser)
    add_repo_argument(ready_parser)
    ready_parser.add_argument("--agent-only", action="store_true")
    ready_parser.set_defaults(handler=command_ready)

    assign_parser = subparsers.add_parser("assign", help="assign a ready task")
    assign_parser.add_argument("state", type=Path)
    assign_parser.add_argument("task_id")
    assign_parser.add_argument("--owner", required=True)
    assign_parser.add_argument("--coordinator", action="store_true")
    add_mutation_contract(assign_parser)
    add_plan_argument(assign_parser)
    add_repo_argument(assign_parser)
    assign_parser.set_defaults(handler=command_assign)

    activate_parser = subparsers.add_parser(
        "activate", help="bind a reserved task to a native Codex worker"
    )
    activate_parser.add_argument("state", type=Path)
    activate_parser.add_argument("task_id")
    activate_parser.add_argument("--runtime-agent-id", required=True)
    activate_parser.add_argument("--runtime-task-name", required=True)
    add_mutation_contract(activate_parser)
    add_plan_argument(activate_parser)
    add_repo_argument(activate_parser)
    activate_parser.set_defaults(handler=command_activate)

    complete_parser = subparsers.add_parser("complete", help="complete an assigned task")
    complete_parser.add_argument("state", type=Path)
    complete_parser.add_argument("task_id")
    complete_parser.add_argument("--evidence", required=True)
    complete_parser.add_argument("--runtime-agent-id")
    add_mutation_contract(complete_parser)
    add_plan_argument(complete_parser)
    add_repo_argument(complete_parser)
    complete_parser.set_defaults(handler=command_complete)

    release_parser = subparsers.add_parser("release", help="release a task to pending")
    release_parser.add_argument("state", type=Path)
    release_parser.add_argument("task_id")
    release_parser.add_argument("--reason", required=True)
    release_parser.add_argument("--spawn-failed", action="store_true")
    release_parser.add_argument("--runtime-agent-id")
    release_parser.add_argument("--stopped-evidence")
    add_mutation_contract(release_parser)
    add_plan_argument(release_parser)
    add_repo_argument(release_parser)
    release_parser.set_defaults(handler=command_release)

    block_parser = subparsers.add_parser("block", help="block a task")
    block_parser.add_argument("state", type=Path)
    block_parser.add_argument("task_id")
    block_parser.add_argument("--reason", required=True)
    add_mutation_contract(block_parser)
    add_plan_argument(block_parser)
    add_repo_argument(block_parser)
    block_parser.set_defaults(handler=command_block)
    return parser


def prepare_cli_context(args: argparse.Namespace) -> None:
    """Resolve CLI paths and enforce repository mutation boundaries."""
    repo = getattr(args, "repo", None)
    if args.command in MUTATION_COMMANDS and repo is None:
        inferred_plan = args.plan.expanduser().resolve()
        inferred_state = args.state.expanduser().resolve()
        parts = inferred_state.parts
        marker_index = next(
            (
                index
                for index in range(len(parts) - 1)
                if parts[index : index + 2] == (".codex", "project-workflow")
            ),
            -1,
        )
        inferred_repo = Path(*parts[:marker_index]) if marker_index > 0 else inferred_plan.parent
        inferred_root = (inferred_repo / INTERNAL_STATE_ROOT).resolve()
        if (
            marker_index <= 0
            or not path_is_within(inferred_state, inferred_root)
            or not path_is_within(inferred_plan, inferred_repo)
        ):
            raise OrchestrationError(
                f"{args.command} requires --repo and an internal "
                ".codex/project-workflow state path; historical external state is read-only"
            )
        args.state = inferred_state
        repo = inferred_repo
    if repo is None:
        args.state = args.state.expanduser().resolve()
        if hasattr(args, "plan"):
            args.plan = args.plan.expanduser().resolve()
        return
    lexical_repo = repo.expanduser().absolute()
    resolved_repo = repo.expanduser().resolve()
    if not resolved_repo.is_dir():
        raise OrchestrationError(f"repository root does not exist: {resolved_repo}")
    args.repo = resolved_repo
    supplied_state = args.state.expanduser()
    if supplied_state.is_absolute():
        try:
            supplied_state = resolved_repo / supplied_state.absolute().relative_to(
                lexical_repo
            )
        except ValueError:
            pass
    supplied_state = (
        supplied_state
        if supplied_state.is_absolute()
        else resolved_repo / supplied_state
    )
    lexical_state = lexical_absolute(supplied_state)
    args.state = (
        lexical_state
        if path_is_within(lexical_state, resolved_repo)
        else supplied_state.resolve()
    )
    if hasattr(args, "plan"):
        args.plan = resolve_repo_path(resolved_repo, args.plan)
        if not path_is_within(args.plan, resolved_repo):
            raise OrchestrationError("plan must be inside repository")
    if args.command in MUTATION_COMMANDS:
        args.state = require_internal_state_path(args.state, resolved_repo)


def main() -> int:
    """Run the orchestration state command."""
    parser = build_parser()
    configure_stdio()
    args = parser.parse_args()
    try:
        prepare_cli_context(args)
        if args.command in MUTATION_COMMANDS:
            with locked_state(args.state, repo=args.repo):
                require_expected_version(args.state, args.expected_version)
                args.handler(args)
        elif args.repo is not None and path_is_internal_lexically(args.state, args.repo):
            with InternalStateAccess(
                args.state,
                args.repo,
                create_parents=False,
            ) as access, bound_state_access(access):
                args.handler(args)
        else:
            args.handler(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
