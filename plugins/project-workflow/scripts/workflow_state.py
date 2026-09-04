#!/usr/bin/env python3
"""Manage durable Project Workflow state stored in Markdown frontmatter."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple


from platform_io import SecureDirectory, configure_stdio, file_lock


_PLAN_ACCESS = ContextVar("workflow_plan_access", default=None)
WORKFLOW = "project-workflow/v1"
VALID_VCS_MODES = {"AUTO", "GIT", "NONE"}
RESOLVED_VCS_MODES = {"GIT", "NONE"}
DEFAULT_PROGRESS_HEARTBEAT_MINUTES = 5
MAX_PROGRESS_HEARTBEAT_MINUTES = 60
REQUIRED_FIELDS = (
    "workflow",
    "plan_id",
    "revision",
    "phase",
    "approved_revision",
    "approved_at",
    "confirmation_record",
)
VALID_PHASES = {
    "DRAFT",
    "AWAITING_CONFIRMATION",
    "APPROVED",
    "IN_PROGRESS",
    "BLOCKED",
    "COMPLETED",
}
ALLOWED_TRANSITIONS = {
    "DRAFT": {"AWAITING_CONFIRMATION"},
    "AWAITING_CONFIRMATION": {"APPROVED"},
    "APPROVED": {"IN_PROGRESS", "AWAITING_CONFIRMATION", "BLOCKED"},
    "IN_PROGRESS": {"COMPLETED", "AWAITING_CONFIRMATION", "BLOCKED"},
    "BLOCKED": {"AWAITING_CONFIRMATION"},
    "COMPLETED": set(),
}
MUTATION_COMMANDS = {
    "init",
    "create-baseline",
    "approve",
    "start-execution",
    "complete",
    "resume",
    "transition",
    "cleanup-legacy-lock",
}
PLAN_LOCK_TIMEOUT_SECONDS = 5.0
CURRENT_POLICY_CONTRACT = "v0.5"
SUPPORTED_POLICY_CONTRACTS = {"v0.4", CURRENT_POLICY_CONTRACT}
TRANSITIONAL_V04_FIELDS = {
    "workflow_profile",
    "vcs_mode",
    "resolved_vcs_mode",
    "rollback_required",
    "orchestration_state",
    "conversation_title",
    "progress_heartbeat_minutes",
    "execution_mode",
    "agent_topology",
    "filesystem_baseline",
    "filesystem_write_scopes",
}


class WorkflowError(ValueError):
    """Report invalid workflow state or an unsafe transition."""


def policy_contract(metadata: Dict[str, object]) -> str:
    """Classify explicit/current plans without letting malformed plans become legacy."""
    if "policy_contract" in metadata:
        value = metadata["policy_contract"]
        if not isinstance(value, str) or value not in SUPPORTED_POLICY_CONTRACTS:
            raise WorkflowError(f"unsupported policy_contract: {value}")
        return value
    if any(field in metadata for field in TRANSITIONAL_V04_FIELDS):
        return "v0.4"
    return "legacy"


def managed_policy(metadata: Dict[str, object]) -> bool:
    """Return whether a plan uses a supported persisted policy contract."""
    return policy_contract(metadata) in SUPPORTED_POLICY_CONTRACTS


def requested_vcs_mode(metadata: Dict[str, object]) -> str:
    """Return a validated requested VCS mode, defaulting historical plans to AUTO."""
    raw_mode = metadata.get("vcs_mode", "AUTO")
    if not isinstance(raw_mode, str) or raw_mode not in VALID_VCS_MODES:
        raise WorkflowError("vcs_mode must be one of AUTO, GIT, or NONE")
    return raw_mode


def detect_git(repo: Path) -> Tuple[bool, bool]:
    """Detect executable Git and valid worktree membership using a bounded command."""
    git = shutil.which("git")
    if git is None:
        return False, False
    try:
        result = subprocess.run(
            [git, "rev-parse", "--is-inside-work-tree"],
            cwd=str(repo.expanduser().resolve()),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return True, False
    return True, result.returncode == 0 and result.stdout.strip() == "true"


def rollback_evidence_verified(metadata: Dict[str, object]) -> bool:
    """Return whether a NONE workflow records verified equivalent recovery evidence."""
    strategy = metadata.get("rollback_strategy", "")
    evidence = metadata.get("rollback_evidence", "")
    verification = metadata.get("rollback_verification", "")
    if not isinstance(strategy, str):
        raise WorkflowError("rollback_strategy must be a string when present")
    if not isinstance(evidence, str):
        raise WorkflowError("rollback_evidence must be a string when present")
    if not isinstance(verification, str) or verification not in {"", "VERIFIED"}:
        raise WorkflowError("rollback_verification must be VERIFIED when present")
    return (
        bool(strategy.strip())
        and bool(evidence.strip())
        and verification == "VERIFIED"
    )


def rollback_required(metadata: Dict[str, object]) -> bool:
    """Return the strict persisted rollback requirement for current plans."""
    if "rollback_required" not in metadata:
        return False
    value = metadata["rollback_required"]
    if not isinstance(value, str) or value not in {"true", "false"}:
        raise WorkflowError("rollback_required must be the string true or false")
    return value == "true"


def require_none_topology(metadata: Dict[str, object], resolved: str) -> None:
    """Reject VCS NONE plans that claim a worktree or remote-agent topology."""
    topology = metadata.get("agent_topology", "SHARED_WORKSPACE")
    if not isinstance(topology, str):
        raise WorkflowError("agent_topology must be a string when present")
    if resolved == "NONE" and topology != "SHARED_WORKSPACE":
        raise WorkflowError("VCS NONE requires SHARED_WORKSPACE agent_topology")


def resolve_vcs(
    metadata: Dict[str, object], repo: Path
) -> Tuple[str, bool, bool, bool]:
    """Resolve the plan VCS mode and reject capability loss or evidence-model drift."""
    requested = requested_vcs_mode(metadata)
    if requested == "NONE":
        git_available, git_worktree = False, False
        current = "NONE"
    else:
        git_available, git_worktree = detect_git(repo)
        current = "GIT" if git_available and git_worktree else "NONE"
        if requested == "GIT" and current != "GIT":
            raise WorkflowError("vcs_mode GIT requires executable Git and a valid worktree")

    stored = metadata.get("resolved_vcs_mode", "")
    if stored not in {"", None}:
        if not isinstance(stored, str) or stored not in RESOLVED_VCS_MODES:
            raise WorkflowError("resolved_vcs_mode must be GIT or NONE")
        expected = "NONE" if requested == "NONE" else current
        if stored != expected:
            raise WorkflowError(
                f"VCS environment drift: approved resolution {stored}, current resolution {expected}"
            )

    rollback_capable = current == "GIT" or rollback_evidence_verified(metadata)
    return current, git_available, git_worktree, rollback_capable


def require_execution_vcs(metadata: Dict[str, object], repo: Path) -> str:
    """Enforce VCS drift and FULL-profile rollback requirements at execution gates."""
    resolved, _, _, rollback_capable = resolve_vcs(metadata, repo)
    profile = metadata.get("workflow_profile", "FULL")
    if not isinstance(profile, str) or profile not in {"LIGHT", "STANDARD", "FULL"}:
        raise WorkflowError("workflow_profile must be LIGHT, STANDARD, or FULL")
    require_none_topology(metadata, resolved)
    requires_rollback = rollback_required(metadata)
    if resolved == "NONE" and (profile == "FULL" or requires_rollback) and not rollback_capable:
        raise WorkflowError(
            "VCS NONE with required rollback requires verified equivalent rollback evidence"
        )
    return resolved


def command_repo(args: argparse.Namespace) -> Path:
    """Resolve an explicit workspace or retain the historical current-directory default."""
    supplied = getattr(args, "repo", None)
    return supplied if supplied is not None else Path.cwd().resolve()


def path_is_within(path: Path, root: Path) -> bool:
    """Return whether a resolved path is contained by a resolved root."""
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def normalize_command_paths(args: argparse.Namespace) -> None:
    """Normalize CLI paths once while preserving historical cwd-based behavior."""
    supplied_repo = getattr(args, "repo", None)
    args.repo_explicit = supplied_repo is not None
    if supplied_repo is not None:
        repo = supplied_repo.expanduser().resolve()
        if not repo.is_dir():
            raise WorkflowError(f"repository root does not exist: {repo}")
        args.repo = repo
        if not args.plan.expanduser().is_absolute():
            args.plan = (repo / args.plan.expanduser()).resolve()
        else:
            args.plan = args.plan.expanduser().resolve()
        if not path_is_within(args.plan, repo):
            raise WorkflowError("plan must be inside repository")
        return
    args.plan = args.plan.expanduser().resolve()


def private_lock_path(path: Path, namespace: str, repo: Optional[Path] = None) -> Path:
    """Return a stable internal lock path without touching user document directories."""
    target = path.expanduser().resolve()
    if repo is not None:
        root = repo.expanduser().resolve()
        if not path_is_within(target, root):
            raise WorkflowError("lock target must be inside repository")
        identity = os.path.normcase(target.relative_to(root).as_posix()) if os.name == "nt" else target.relative_to(root).as_posix()
        lock_root = root / ".codex/project-workflow/.locks"
        current = root
        for component in lock_root.relative_to(root).parts:
            current = current / component
            if current.is_symlink() or (current.exists() and getattr(current.lstat(), "st_file_attributes", 0) & 0x400):
                raise WorkflowError("lock directory must not traverse a symlink or reparse point")
    else:
        identity = os.path.normcase(str(target))
        if os.name == "nt":
            lock_root = Path.home().resolve() / ".codex/project-workflow/private-locks"
        else:
            lock_root = Path(tempfile.gettempdir()).resolve() / f"project-workflow-{os.getuid()}" / "locks"
        lock_root.mkdir(parents=True, mode=0o700, exist_ok=True)
        try:
            os.chmod(lock_root, 0o700)
        except OSError:
            pass
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return lock_root / f"{namespace}-{digest}.lock"


@contextmanager
def document_access(path: Path):
    """Reuse the held plan parent so a rename cannot redirect document I/O."""
    active = _PLAN_ACCESS.get()
    if active is not None and active[0] == path:
        yield active[1]
    else:
        with SecureDirectory(path.parent.resolve()) as directory:
            yield directory


@contextmanager
def locked_plan(
    path: Path,
    timeout_seconds: float = PLAN_LOCK_TIMEOUT_SECONDS,
    repo: Optional[Path] = None,
):
    """Lock and anchor a complete plan read-modify-write on either platform."""
    lock_path = private_lock_path(path, "plan", repo)
    root = repo.expanduser().resolve() if repo is not None else None
    with SecureDirectory(lock_path.parent, root=root, create=True) as lock_directory:
        descriptor = lock_directory.open_regular(lock_path.name, os.O_RDWR | os.O_CREAT)
        try:
            with file_lock(descriptor, timeout_seconds):
                with SecureDirectory(path.parent, root=root, create=True) as directory:
                    token = _PLAN_ACCESS.set((path, directory))
                    try:
                        yield
                    finally:
                        _PLAN_ACCESS.reset(token)
        except TimeoutError as exc:
            raise WorkflowError(f"timed out acquiring plan lock: {path}") from exc
        finally:
            os.close(descriptor)


def content_sha256(path: Path) -> str:
    """Return the current plan bytes digest for optional compare-and-swap."""
    with document_access(path) as directory:
        with os.fdopen(directory.open_regular(path.name, os.O_RDONLY), "rb") as stream:
            return hashlib.sha256(stream.read()).hexdigest()


def require_expected_plan(args: argparse.Namespace) -> None:
    """Reject stale lifecycle writers before their read-modify-write operation."""
    expected_revision = getattr(args, "expected_revision", None)
    expected_phase = getattr(args, "expected_phase", None)
    expected_sha256 = getattr(args, "expected_sha256", None)
    if expected_revision is None and expected_phase is None and expected_sha256 is None:
        return
    metadata, _, _ = parse_document(args.plan)
    revision, phase = require_common(metadata)
    if expected_revision is not None and revision != expected_revision:
        raise WorkflowError(
            f"plan revision conflict: expected {expected_revision}, found {revision}"
        )
    if expected_phase is not None and phase != expected_phase:
        raise WorkflowError(f"plan phase conflict: expected {expected_phase}, found {phase}")
    if expected_sha256 is not None:
        normalized = expected_sha256.lower()
        if len(normalized) != 64 or any(character not in "0123456789abcdef" for character in normalized):
            raise WorkflowError("expected SHA-256 must contain exactly 64 hexadecimal characters")
        current = content_sha256(args.plan)
        if current != normalized:
            raise WorkflowError(
                f"plan content conflict: expected SHA-256 {normalized}, found {current}"
            )


def decode_value(value: str) -> object:
    """Decode a supported frontmatter scalar without external YAML packages."""
    value = value.strip()
    if not value:
        return ""
    if value.startswith(('"', "[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"invalid JSON frontmatter value: {value}") from exc
    if value.isdigit():
        return int(value)
    return value


def encode_value(value: object) -> str:
    """Encode a scalar in the restricted frontmatter format."""
    if value is None or value == "":
        return ""
    if type(value) is int:
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(str(value), ensure_ascii=False)


def parse_document(path: Path) -> Tuple[Dict[str, object], List[str], str]:
    """Return metadata, key order, and the untouched Markdown body."""
    if not path.is_file():
        raise WorkflowError(f"plan file does not exist: {path}")
    with document_access(path) as directory:
        with os.fdopen(directory.open_regular(path.name, os.O_RDONLY), "r", encoding="utf-8") as stream:
            text = stream.read()
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        return {}, [], text

    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        raise WorkflowError("frontmatter opening delimiter has no closing delimiter")

    metadata: Dict[str, object] = {}
    order: List[str] = []
    for raw_line in lines[1:closing]:
        line = raw_line.rstrip("\r\n")
        if not line.strip():
            continue
        if ":" not in line:
            raise WorkflowError(f"unsupported frontmatter line: {line}")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or key in metadata:
            raise WorkflowError(f"invalid or duplicate frontmatter key: {key}")
        metadata[key] = decode_value(value)
        order.append(key)
    return metadata, order, "".join(lines[closing + 1 :])


def write_document(path: Path, metadata: Dict[str, object], order: List[str], body: str) -> None:
    """Atomically write controlled frontmatter while preserving the Markdown body."""
    final_order = list(order)
    for key in REQUIRED_FIELDS:
        if key not in final_order:
            final_order.append(key)
    for key in metadata:
        if key not in final_order:
            final_order.append(key)

    frontmatter = ["---\n"]
    for key in final_order:
        if key in metadata:
            frontmatter.append(f"{key}: {encode_value(metadata[key])}\n")
    frontmatter.append("---\n")
    if body and not body.startswith("\n"):
        frontmatter.append("\n")
    content = "".join(frontmatter) + body

    with document_access(path) as directory:
        mode = 0o644
        try:
            existing = directory.stat(path.name)
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISREG(existing.st_mode) or getattr(existing, "st_file_attributes", 0) & 0x400:
                raise WorkflowError(f"plan must be a regular file: {path}")
            mode = existing.st_mode & 0o777
        directory.write_atomic(path.name, content.encode("utf-8"), mode=mode)


def require_common(metadata: Dict[str, object]) -> Tuple[int, str]:
    """Validate fields shared by approval, execution, and transitions."""
    missing = [key for key in REQUIRED_FIELDS if key not in metadata]
    if missing:
        raise WorkflowError(f"missing required fields: {', '.join(missing)}")
    if metadata["workflow"] != WORKFLOW:
        raise WorkflowError(f"unsupported workflow: {metadata['workflow']}")
    policy_contract(metadata)
    if not isinstance(metadata["plan_id"], str) or not metadata["plan_id"].strip():
        raise WorkflowError("plan_id must not be empty")
    revision = metadata["revision"]
    if type(revision) is not int or revision < 1:
        raise WorkflowError("revision must be a positive integer")
    if not isinstance(metadata["phase"], str):
        raise WorkflowError("phase must be a string")
    phase = metadata["phase"]
    if phase not in VALID_PHASES:
        raise WorkflowError(f"invalid phase: {phase}")
    rollback_required(metadata)
    require_experience(metadata)
    return revision, phase


def first_heading(body: str) -> str:
    """Return the first level-one Markdown heading without its marker."""
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def require_experience(
    metadata: Dict[str, object],
    body: str = "",
) -> Tuple[str, int]:
    """Validate or derive the conversation title and heartbeat interval."""
    raw_title = metadata.get("conversation_title", "")
    if raw_title and not isinstance(raw_title, str):
        raise WorkflowError("conversation_title must be a string")
    title = str(raw_title).strip() or first_heading(body) or str(metadata.get("plan_id", "")).strip()
    if not title:
        raise WorkflowError("conversation_title cannot be derived from the plan")
    if len(title) > 80:
        raise WorkflowError("conversation_title must not exceed 80 characters")

    heartbeat = metadata.get(
        "progress_heartbeat_minutes",
        DEFAULT_PROGRESS_HEARTBEAT_MINUTES,
    )
    if (
        isinstance(heartbeat, bool)
        or not isinstance(heartbeat, int)
        or not 1 <= heartbeat <= MAX_PROGRESS_HEARTBEAT_MINUTES
    ):
        raise WorkflowError(
            "progress_heartbeat_minutes must be an integer between 1 and 60"
        )
    return title, heartbeat


def command_inspect(args: argparse.Namespace) -> None:
    """Print normalized workflow state as JSON."""
    metadata, _, _ = parse_document(args.plan)
    require_common(metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


def command_init(args: argparse.Namespace) -> None:
    """Initialize a new or draft plan at the confirmation boundary."""
    metadata, order, body = parse_document(args.plan)
    if metadata:
        policy_contract(metadata)
    existing_phase = str(metadata.get("phase", "DRAFT"))
    if existing_phase not in {"DRAFT", "AWAITING_CONFIRMATION"}:
        raise WorkflowError(f"cannot initialize plan in phase {existing_phase}")
    revision = metadata.get("revision", 1)
    if type(revision) is not int or revision < 1:
        raise WorkflowError("revision must be a positive integer")
    existing_plan_id = str(metadata.get("plan_id", "")).strip()
    plan_id = args.plan_id.strip() or existing_plan_id
    if not plan_id:
        raise WorkflowError("plan_id must not be empty")
    experience_metadata = dict(metadata)
    experience_metadata["plan_id"] = plan_id
    title, heartbeat = require_experience(experience_metadata, body)
    requested = args.vcs_mode
    vcs_metadata: Dict[str, object] = {"vcs_mode": requested}
    resolved, _, _, _ = resolve_vcs(vcs_metadata, command_repo(args))
    rollback_required(metadata)
    require_none_topology(metadata, resolved)
    metadata.update(
        {
            "workflow": WORKFLOW,
            "policy_contract": CURRENT_POLICY_CONTRACT,
            "plan_id": plan_id,
            "revision": revision,
            "phase": "AWAITING_CONFIRMATION",
            "approved_revision": "",
            "approved_at": "",
            "confirmation_record": "",
            "conversation_title": title,
            "progress_heartbeat_minutes": heartbeat,
            "vcs_mode": requested,
            "resolved_vcs_mode": resolved,
        }
    )
    write_document(args.plan, metadata, order, body)
    print(f"initialized {plan_id} revision {revision} at AWAITING_CONFIRMATION")


def command_experience(args: argparse.Namespace) -> None:
    """Print the normalized user-facing execution experience contract."""
    metadata, _, body = parse_document(args.plan)
    require_common(metadata)
    title, heartbeat = require_experience(metadata, body)
    print(
        json.dumps(
            {
                "conversation_title": title,
                "progress_heartbeat_minutes": heartbeat,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def command_approve(args: argparse.Namespace) -> None:
    """Record explicit approval for the current revision."""
    confirmation = args.confirmation.strip()
    if not confirmation:
        raise WorkflowError("confirmation must contain the explicit user message")
    metadata, order, body = parse_document(args.plan)
    revision, phase = require_common(metadata)
    if phase != "AWAITING_CONFIRMATION":
        raise WorkflowError(f"approval requires AWAITING_CONFIRMATION, found {phase}")
    approved_at = normalize_approval_time(args.at)
    approval_update: Dict[str, object] = {
        "phase": "APPROVED",
        "approved_revision": revision,
        "approved_at": approved_at,
        "confirmation_record": confirmation,
    }
    if (
        managed_policy(metadata)
        and metadata.get("resolved_vcs_mode") == "NONE"
    ):
        approval_update["approved_filesystem_policy_sha256"] = (
            filesystem_policy_sha256(metadata)
        )
    metadata.update(approval_update)
    write_document(args.plan, metadata, order, body)
    print(f"approved revision {revision} at {approved_at}")


def normalize_approval_time(value: Optional[str]) -> str:
    """Return a timezone-aware ISO-8601 approval time or fail before mutation."""
    if value is None:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    normalized = value.strip()
    if not normalized:
        raise WorkflowError("approval time must not be empty")
    parseable = f"{normalized[:-1]}+00:00" if normalized.endswith(("Z", "z")) else normalized
    try:
        parsed = datetime.fromisoformat(parseable)
        offset = parsed.utcoffset()
    except (TypeError, ValueError) as exc:
        raise WorkflowError("approval time must be a timezone-aware ISO-8601 value") from exc
    if parsed.tzinfo is None or offset is None:
        raise WorkflowError("approval time must be a timezone-aware ISO-8601 value")
    return normalized


def validate_approval_time(value: object) -> str:
    """Validate a persisted approval timestamp without coercing its type."""
    if not isinstance(value, str):
        raise WorkflowError("approved_at must be a timezone-aware ISO-8601 string")
    try:
        return normalize_approval_time(value)
    except WorkflowError as exc:
        raise WorkflowError("approved_at must be a timezone-aware ISO-8601 string") from exc


def require_approval_record(metadata: Dict[str, object], revision: int) -> None:
    """Fail unless metadata contains a complete approval for the current revision."""
    approved_revision = metadata["approved_revision"]
    if type(approved_revision) is not int or approved_revision != revision:
        raise WorkflowError(
            f"approved_revision {approved_revision} does not match revision {revision}"
        )
    validate_approval_time(metadata["approved_at"])
    confirmation = metadata["confirmation_record"]
    if not isinstance(confirmation, str) or not confirmation.strip():
        raise WorkflowError("confirmation_record must be a non-empty string")


def approval_confirmation_sha256(metadata: Dict[str, object]) -> str:
    """Return a stable digest of the exact persisted approval confirmation."""
    confirmation = metadata["confirmation_record"]
    if not isinstance(confirmation, str):
        raise WorkflowError("confirmation_record must be a non-empty string")
    return hashlib.sha256(confirmation.encode("utf-8")).hexdigest()


def filesystem_policy_sha256(metadata: Dict[str, object]) -> str:
    """Digest the NONE evidence configuration that explicit approval covers."""
    payload = {
        "policy_contract": policy_contract(metadata),
        "plan_id": metadata.get("plan_id"),
        "revision": metadata.get("revision"),
        "resolved_vcs_mode": metadata.get("resolved_vcs_mode"),
        "orchestration_state": metadata.get("orchestration_state", ""),
        "snapshot_scopes": metadata.get("filesystem_snapshot_scopes"),
        "snapshot_excludes": metadata.get("filesystem_snapshot_excludes"),
        "write_scopes": metadata.get("filesystem_write_scopes"),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def require_approved_filesystem_policy(metadata: Dict[str, object]) -> None:
    """Reject NONE evidence configuration drift after explicit approval."""
    approved_policy = metadata.get("approved_filesystem_policy_sha256")
    current_policy = filesystem_policy_sha256(metadata)
    if approved_policy != current_policy:
        raise WorkflowError(
            "approved filesystem policy does not match current scopes/excludes"
        )


def normalize_metadata_paths(values: object, field: str) -> List[str]:
    """Validate one persisted list of normalized workspace-relative paths."""
    import filesystem_snapshot as snapshot_module

    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise WorkflowError(f"{field} must be a list of strings")
    try:
        normalized = snapshot_module.normalize_scopes(values)
    except snapshot_module.SnapshotError as exc:
        raise WorkflowError(str(exc)) from exc
    if normalized != values:
        raise WorkflowError(f"{field} must be normalized and unique")
    return normalized


def canonical_repo_relative(path: Path, repo: Path) -> str:
    """Return a canonical repository-relative POSIX path."""
    try:
        return path.relative_to(repo.expanduser().resolve()).as_posix()
    except ValueError as exc:
        raise WorkflowError("filesystem evidence must stay inside repository") from exc


def load_bound_baseline(
    metadata: Dict[str, object], repo: Path
) -> Tuple[Dict[str, object], Path, str, List[str]]:
    """Load and validate the immutable approval-bound baseline for a current NONE plan."""
    import filesystem_snapshot as snapshot_module

    require_approved_filesystem_policy(metadata)
    raw_path = metadata.get("filesystem_baseline")
    expected_digest = metadata.get("filesystem_baseline_sha256")
    if not isinstance(raw_path, str) or not raw_path.strip() or not isinstance(
        expected_digest, str
    ):
        raise WorkflowError("current NONE plan requires a bound filesystem baseline")
    if len(expected_digest) != 64 or any(
        character not in "0123456789abcdef" for character in expected_digest
    ):
        raise WorkflowError("filesystem_baseline_sha256 must be a lowercase SHA-256")
    try:
        baseline_path = snapshot_module.internal_state_path(repo, Path(raw_path))
        baseline = snapshot_module.read_snapshot(baseline_path, repo)
        actual_digest = snapshot_module.canonical_json_sha256(baseline)
    except snapshot_module.SnapshotError as exc:
        raise WorkflowError(str(exc)) from exc
    if actual_digest != expected_digest:
        raise WorkflowError(
            "filesystem baseline digest mismatch: "
            f"expected {expected_digest}, found {actual_digest}"
        )
    revision = metadata["revision"]
    binding = baseline.get("binding")
    expected_binding = {
        "policy_contract": policy_contract(metadata),
        "plan_id": metadata["plan_id"],
        "revision": revision,
        "approved_revision": metadata["approved_revision"],
        "confirmation_sha256": approval_confirmation_sha256(metadata),
    }
    if binding != expected_binding:
        raise WorkflowError("filesystem baseline approval binding does not match the plan")
    scopes = normalize_metadata_paths(
        metadata.get("filesystem_snapshot_scopes"), "filesystem_snapshot_scopes"
    )
    excludes = normalize_metadata_paths(
        metadata.get("filesystem_snapshot_excludes"), "filesystem_snapshot_excludes"
    )
    write_scopes = normalize_metadata_paths(
        metadata.get("filesystem_write_scopes"), "filesystem_write_scopes"
    )
    if baseline.get("scopes") != scopes or baseline.get("excludes") != excludes:
        raise WorkflowError("filesystem baseline scopes/excludes do not match the approved plan")
    return baseline, baseline_path, actual_digest, write_scopes


def require_current_none_baseline(metadata: Dict[str, object], repo: Path) -> None:
    """Require approval-bound evidence before a current NONE plan may execute."""
    if (
        managed_policy(metadata)
        and metadata.get("resolved_vcs_mode") == "NONE"
    ):
        load_bound_baseline(metadata, repo)


def create_bound_baseline(
    metadata: Dict[str, object],
    repo: Path,
    raw_output: Optional[Path] = None,
    replace_if_sha256: Optional[str] = None,
) -> Dict[str, object]:
    """Create or idempotently reuse baseline evidence bound to approved metadata."""
    import filesystem_snapshot as snapshot_module

    require_approved_filesystem_policy(metadata)
    scopes = normalize_metadata_paths(
        metadata.get("filesystem_snapshot_scopes"), "filesystem_snapshot_scopes"
    )
    excludes = normalize_metadata_paths(
        metadata.get("filesystem_snapshot_excludes"), "filesystem_snapshot_excludes"
    )
    write_scopes = normalize_metadata_paths(
        metadata.get("filesystem_write_scopes"), "filesystem_write_scopes"
    )
    if not write_scopes:
        raise WorkflowError("filesystem_write_scopes must contain at least one path")
    output_value = raw_output or Path(
        f".codex/project-workflow/{metadata['plan_id']}/filesystem-baseline.json"
    )
    try:
        output = snapshot_module.internal_state_path(repo, output_value)
        snapshot = snapshot_module.build_snapshot(repo, scopes, excludes)
        snapshot["binding"] = {
            "policy_contract": policy_contract(metadata),
            "plan_id": metadata["plan_id"],
            "revision": metadata["revision"],
            "approved_revision": metadata["approved_revision"],
            "confirmation_sha256": approval_confirmation_sha256(metadata),
        }
        digest = snapshot_module.canonical_json_sha256(snapshot)
        if output.exists():
            existing = snapshot_module.read_snapshot(output, repo)
            existing_digest = snapshot_module.canonical_json_sha256(existing)
            if existing_digest == digest:
                pass
            elif replace_if_sha256 is not None:
                snapshot_module.atomic_write_json(
                    output,
                    snapshot,
                    repo,
                    expected_sha256=replace_if_sha256,
                )
            else:
                raise WorkflowError(f"filesystem baseline already exists: {output}")
        else:
            if replace_if_sha256 is not None:
                raise WorkflowError("baseline recovery requires an existing target")
            snapshot_module.atomic_write_json(output, snapshot, repo, create_only=True)
    except snapshot_module.SnapshotError as exc:
        raise WorkflowError(str(exc)) from exc
    updated = dict(metadata)
    updated.update(
        {
            "filesystem_baseline": canonical_repo_relative(output, repo),
            "filesystem_baseline_sha256": digest,
        }
    )
    return updated


def command_create_baseline(args: argparse.Namespace) -> None:
    """Create and bind an immutable approved baseline for one current NONE plan."""
    import filesystem_snapshot as snapshot_module

    if not args.repo_explicit:
        raise WorkflowError("create-baseline requires explicit --repo")
    metadata, order, body = parse_document(args.plan)
    revision, phase = require_common(metadata)
    if not managed_policy(metadata):
        raise WorkflowError("create-baseline is only available for current plans")
    if phase != "APPROVED":
        raise WorkflowError(f"create-baseline requires APPROVED, found {phase}")
    require_approval_record(metadata, revision)
    repo = command_repo(args)
    if require_execution_vcs(metadata, repo) != "NONE":
        raise WorkflowError("create-baseline is only valid for VCS NONE plans")
    require_approved_filesystem_policy(metadata)
    scopes = normalize_metadata_paths(
        metadata.get("filesystem_snapshot_scopes"), "filesystem_snapshot_scopes"
    )
    excludes = normalize_metadata_paths(
        metadata.get("filesystem_snapshot_excludes"), "filesystem_snapshot_excludes"
    )
    write_scopes = normalize_metadata_paths(
        metadata.get("filesystem_write_scopes"), "filesystem_write_scopes"
    )
    supplied = (
        ("--scope", args.scope, scopes),
        ("--exclude", args.exclude, excludes),
        ("--write-scope", args.write_scope, write_scopes),
    )
    for option, raw_values, approved_values in supplied:
        if raw_values:
            try:
                normalized_values = snapshot_module.normalize_scopes(raw_values)
            except snapshot_module.SnapshotError as exc:
                raise WorkflowError(str(exc)) from exc
            if normalized_values != approved_values:
                raise WorkflowError(f"{option} values do not match the approved plan")
    updated = create_bound_baseline(
        metadata,
        repo,
        args.output,
        args.replace_if_sha256,
    )
    write_document(args.plan, updated, order, body)
    print(f"created and bound filesystem baseline for {metadata['plan_id']} revision {revision}")


def resolve_orchestration_path(metadata: Dict[str, object], repo: Path) -> Optional[Path]:
    """Resolve an optional companion state inside the repository state root."""
    import orchestration_state as orchestration_module

    raw_state = metadata.get("orchestration_state", "")
    if raw_state == "" or raw_state is None:
        return None
    if not isinstance(raw_state, str):
        raise WorkflowError("orchestration_state must be a repository-relative string")
    supplied = Path(raw_state).expanduser()
    state_path = supplied.resolve() if supplied.is_absolute() else (repo / supplied).resolve()
    if not path_is_within(state_path, repo):
        raise WorkflowError("orchestration_state must be inside repository")
    try:
        return orchestration_module.require_internal_state_path(state_path, repo)
    except orchestration_module.OrchestrationError as exc:
        raise WorkflowError(str(exc)) from exc


def validate_task_state(
    metadata: Dict[str, object], plan: Path, repo: Path, final: bool = False
) -> Optional[int]:
    """Validate v0.5 task-state linkage and return its state version."""
    if policy_contract(metadata) != "v0.5":
        return None
    import task_state as task_module

    try:
        state_path = task_module.task_state_path(repo, str(metadata["plan_id"]))
        if not task_module.state_exists(state_path, repo):
            _, _, body = parse_document(plan)
            if not task_module.TASK_HEADING.search(body):
                return None
        return task_module.validate_for_plan(plan, repo, final=final)
    except (OSError, task_module.TaskStateError) as exc:
        raise WorkflowError(str(exc)) from exc


@contextmanager
def locked_final_orchestration(
    metadata: Dict[str, object],
    plan: Path,
    repo: Path,
) -> Iterator[Tuple[Optional[int], Optional[Dict[str, Dict[str, object]]]]]:
    """Hold and validate companion scheduler evidence through plan replacement."""
    import orchestration_state as orchestration_module

    state_path = resolve_orchestration_path(metadata, repo)
    if state_path is None:
        yield None, None
        return
    try:
        with orchestration_module.locked_state(state_path, repo=repo):
            state = orchestration_module.load_state(state_path)
            tasks = orchestration_module.validate_final_state(state, plan, repo)
            version = state.get("state_version", 0)
            if isinstance(version, bool) or not isinstance(version, int) or version < 0:
                raise WorkflowError("orchestration state_version must be a non-negative integer")
            yield version, tasks
    except orchestration_module.OrchestrationError as exc:
        raise WorkflowError(str(exc)) from exc


def require_final_filesystem_evidence(
    metadata: Dict[str, object],
    repo: Path,
    tasks: Optional[Dict[str, Dict[str, object]]],
    state_version: Optional[int],
) -> Optional[Tuple[str, str, Dict[str, object]]]:
    """Persist and return an immutable final artifact for a current NONE plan."""
    if metadata.get("resolved_vcs_mode", "") != "NONE":
        return None
    if not managed_policy(metadata):
        return None

    import filesystem_snapshot as snapshot_module

    baseline, baseline_path, baseline_digest, write_scopes = load_bound_baseline(
        metadata, repo
    )
    if tasks is not None:
        task_scopes = sorted(
            {
                scope
                for task in tasks.values()
                for scope in task["write_scope"]
            }
        )
        if task_scopes != write_scopes:
            raise WorkflowError(
                "filesystem_write_scopes do not match final orchestration task scopes"
            )
    try:
        current = snapshot_module.build_snapshot(
            repo,
            baseline.get("scopes"),
            baseline.get("excludes", []),
        )
        result = snapshot_module.compare_snapshots(
            baseline,
            current,
            write_scopes,
        )
    except snapshot_module.SnapshotError as exc:
        raise WorkflowError(str(exc)) from exc
    if result["out_of_scope"]:
        raise WorkflowError(
            "final filesystem comparison contains out-of-scope changes: "
            + ", ".join(result["out_of_scope"])
        )
    artifact: Dict[str, object] = {
        "schema": snapshot_module.FINAL_EVIDENCE_SCHEMA,
        "policy_contract": policy_contract(metadata),
        "plan_id": metadata["plan_id"],
        "revision": metadata["revision"],
        "approved_revision": metadata["approved_revision"],
        "confirmation_sha256": approval_confirmation_sha256(metadata),
        "baseline": canonical_repo_relative(baseline_path, repo),
        "baseline_sha256": baseline_digest,
        "current_snapshot_sha256": snapshot_module.canonical_json_sha256(current),
        "scopes": baseline["scopes"],
        "excludes": baseline.get("excludes", []),
        "write_scopes": write_scopes,
        "added": result["added"],
        "modified": result["modified"],
        "deleted": result["deleted"],
        "out_of_scope": result["out_of_scope"],
        "orchestration_state_version": state_version,
    }
    raw_artifact = metadata.get(
        "final_filesystem_artifact",
        f".codex/project-workflow/{metadata['plan_id']}/filesystem-final-diff.json",
    )
    if not isinstance(raw_artifact, str) or not raw_artifact.strip():
        raise WorkflowError("final_filesystem_artifact must be a non-empty string")
    try:
        artifact_path = snapshot_module.internal_state_path(repo, Path(raw_artifact))
        artifact_digest = snapshot_module.canonical_json_sha256(artifact)
        if artifact_path.exists():
            existing = snapshot_module.read_json_document(artifact_path, repo)
            if snapshot_module.canonical_json_sha256(existing) != artifact_digest:
                raise WorkflowError(f"final filesystem artifact already exists: {artifact_path}")
        else:
            snapshot_module.atomic_write_json(
                artifact_path, artifact, repo, create_only=True
            )
    except snapshot_module.SnapshotError as exc:
        raise WorkflowError(str(exc)) from exc
    return canonical_repo_relative(artifact_path, repo), artifact_digest, artifact


def validate_completed_evidence(
    metadata: Dict[str, object], plan: Path, repo: Path
) -> None:
    """Validate immutable evidence bound to one completed current plan."""
    if metadata.get("phase") != "COMPLETED":
        raise WorkflowError("completed evidence validation requires COMPLETED phase")
    if not managed_policy(metadata):
        return
    task_state_version = validate_task_state(metadata, plan, repo, final=True)
    if task_state_version is not None and metadata.get(
        "final_task_state_version"
    ) != task_state_version:
        raise WorkflowError("final task state version does not match completed plan")
    state_version: Optional[int] = None
    if metadata.get("orchestration_state", ""):
        with locked_final_orchestration(metadata, plan, repo) as final_state:
            state_version, _ = final_state
        if metadata.get("final_orchestration_state_version") != state_version:
            raise WorkflowError("final orchestration state version does not match completed plan")
    if metadata.get("resolved_vcs_mode") != "NONE":
        return

    import filesystem_snapshot as snapshot_module

    baseline, baseline_path, baseline_digest, write_scopes = load_bound_baseline(
        metadata, repo
    )
    raw_artifact = metadata.get("final_filesystem_artifact")
    expected_digest = metadata.get("final_filesystem_artifact_sha256")
    if not isinstance(raw_artifact, str) or not raw_artifact.strip() or not isinstance(
        expected_digest, str
    ):
        raise WorkflowError("completed NONE plan requires a final filesystem artifact")
    try:
        artifact_path = snapshot_module.internal_state_path(repo, Path(raw_artifact))
        artifact = snapshot_module.read_json_document(artifact_path, repo)
        actual_digest = snapshot_module.canonical_json_sha256(artifact)
    except snapshot_module.SnapshotError as exc:
        raise WorkflowError(f"invalid final filesystem artifact: {exc}") from exc
    if actual_digest != expected_digest:
        raise WorkflowError("final filesystem artifact digest does not match completed plan")
    expected_fields = {
        "schema": snapshot_module.FINAL_EVIDENCE_SCHEMA,
        "policy_contract": policy_contract(metadata),
        "plan_id": metadata["plan_id"],
        "revision": metadata["revision"],
        "approved_revision": metadata["approved_revision"],
        "confirmation_sha256": approval_confirmation_sha256(metadata),
        "baseline": canonical_repo_relative(baseline_path, repo),
        "baseline_sha256": baseline_digest,
        "scopes": baseline["scopes"],
        "excludes": baseline.get("excludes", []),
        "write_scopes": write_scopes,
        "orchestration_state_version": metadata.get(
            "final_orchestration_state_version"
        ),
    }
    if any(artifact.get(key) != value for key, value in expected_fields.items()):
        raise WorkflowError("final filesystem artifact binding does not match completed plan")
    current_digest = artifact.get("current_snapshot_sha256")
    if (
        not isinstance(current_digest, str)
        or len(current_digest) != 64
        or any(character not in "0123456789abcdef" for character in current_digest)
    ):
        raise WorkflowError("final filesystem artifact has invalid current snapshot digest")
    changed_paths = set()
    for key in ("added", "modified", "deleted", "out_of_scope"):
        value = artifact.get(key)
        if (
            not isinstance(value, list)
            or not all(isinstance(path, str) for path in value)
            or value != sorted(set(value))
        ):
            raise WorkflowError(f"final filesystem artifact has invalid {key} paths")
        try:
            if any(snapshot_module.normalize_relative_path(path) != path for path in value):
                raise WorkflowError(f"final filesystem artifact has invalid {key} paths")
        except snapshot_module.SnapshotError as exc:
            raise WorkflowError(f"final filesystem artifact has invalid {key} paths") from exc
        if key != "out_of_scope":
            overlap = changed_paths.intersection(value)
            if overlap:
                raise WorkflowError("final filesystem artifact change lists overlap")
            changed_paths.update(value)
    if artifact["out_of_scope"]:
        raise WorkflowError("final filesystem artifact contains out-of-scope changes")
    if any(
        not snapshot_module.path_in_scope(path, write_scopes)
        for path in changed_paths
    ):
        raise WorkflowError("final filesystem artifact contains changes outside write scopes")
    for key in ("added", "modified", "deleted"):
        count = metadata.get(f"final_filesystem_{key}_count")
        if type(count) is not int or count != len(artifact[key]):
            raise WorkflowError(f"final filesystem {key} count does not match artifact")
    legacy_digest = metadata.get("final_filesystem_evidence_sha256")
    if legacy_digest != expected_digest:
        raise WorkflowError("final filesystem evidence digest does not match artifact")


def command_check_execute(args: argparse.Namespace) -> None:
    """Fail unless the plan has a current, explicit approval record."""
    metadata, _, _ = parse_document(args.plan)
    revision, phase = require_common(metadata)
    if phase not in {"APPROVED", "IN_PROGRESS"}:
        raise WorkflowError(f"execution requires APPROVED or IN_PROGRESS, found {phase}")
    require_approval_record(metadata, revision)
    repo = command_repo(args)
    require_execution_vcs(metadata, repo)
    validate_task_state(metadata, args.plan, repo)
    print(f"execution allowed for {metadata['plan_id']} revision {revision} in {phase}")


def command_start_execution(args: argparse.Namespace) -> None:
    """Atomically record approval and enter execution for the current revision."""
    confirmation = args.confirmation.strip()
    if not confirmation:
        raise WorkflowError("confirmation must contain the explicit user message")
    supplied_at = normalize_approval_time(args.at) if args.at is not None else None
    metadata, order, body = parse_document(args.plan)
    revision, phase = require_common(metadata)
    repo = command_repo(args)
    resolved_vcs = require_execution_vcs(metadata, repo)

    if phase == "AWAITING_CONFIRMATION":
        stale_fields = (
            metadata["approved_revision"],
            metadata["approved_at"],
            metadata["confirmation_record"],
        )
        if any(value not in {"", None} for value in stale_fields):
            raise WorkflowError("unapproved plan must not retain an approval record")
        approved_at = supplied_at or normalize_approval_time(None)
        updated = dict(metadata)
        updated.update(
            {
                "phase": "APPROVED",
                "approved_revision": revision,
                "approved_at": approved_at,
                "confirmation_record": confirmation,
            }
        )
        if (
            resolved_vcs == "NONE"
            and managed_policy(updated)
        ):
            if not args.repo_explicit:
                raise WorkflowError("current NONE start-execution requires explicit --repo")
            updated["approved_filesystem_policy_sha256"] = filesystem_policy_sha256(
                updated
            )
            updated = create_bound_baseline(updated, repo)
        updated["phase"] = "IN_PROGRESS"
        validate_task_state(updated, args.plan, repo)
        write_document(args.plan, updated, order, body)
        print(f"started execution for {updated['plan_id']} revision {revision} at {approved_at}")
        return

    if phase not in {"APPROVED", "IN_PROGRESS"}:
        raise WorkflowError(
            f"start-execution requires AWAITING_CONFIRMATION, APPROVED, or IN_PROGRESS, found {phase}"
        )
    require_approval_record(metadata, revision)
    require_current_none_baseline(metadata, repo)
    validate_task_state(metadata, args.plan, repo)
    if metadata["confirmation_record"] != confirmation:
        raise WorkflowError("confirmation does not match the recorded approval")
    if supplied_at is not None and str(metadata["approved_at"]) != supplied_at:
        raise WorkflowError("approval time does not match the recorded approval")
    if phase == "APPROVED":
        updated = dict(metadata)
        updated["phase"] = "IN_PROGRESS"
        write_document(args.plan, updated, order, body)
    print(f"execution active for {metadata['plan_id']} revision {revision}")


def command_complete(args: argparse.Namespace) -> None:
    """Complete a currently executing plan with a valid approval record."""
    metadata, order, body = parse_document(args.plan)
    revision, phase = require_common(metadata)
    if phase != "IN_PROGRESS":
        raise WorkflowError(f"completion requires IN_PROGRESS, found {phase}")
    require_approval_record(metadata, revision)
    repo = command_repo(args)
    require_execution_vcs(metadata, repo)
    task_state_version = validate_task_state(metadata, args.plan, repo, final=True)
    if metadata.get("orchestration_state", "") and not args.repo_explicit:
        raise WorkflowError("completion with orchestration_state requires explicit --repo")
    with locked_final_orchestration(metadata, args.plan, repo) as final_state:
        state_version, tasks = final_state
        filesystem_evidence = require_final_filesystem_evidence(
            metadata, repo, tasks, state_version
        )
        updated = dict(metadata)
        updated["phase"] = "COMPLETED"
        if task_state_version is not None:
            updated["final_task_state_version"] = task_state_version
        if state_version is not None:
            updated["final_orchestration_state_version"] = state_version
        if filesystem_evidence is not None:
            artifact_path, digest, comparison = filesystem_evidence
            updated["final_filesystem_artifact"] = artifact_path
            updated["final_filesystem_artifact_sha256"] = digest
            updated["final_filesystem_evidence_sha256"] = digest
            for key in ("added", "modified", "deleted"):
                updated[f"final_filesystem_{key}_count"] = len(comparison[key])
        write_document(args.plan, updated, order, body)
    print(f"completed {updated['plan_id']} revision {revision}")


def command_resume(args: argparse.Namespace) -> None:
    """Replay execution gates, idempotently for an already executing plan."""
    metadata, order, body = parse_document(args.plan)
    revision, phase = require_common(metadata)
    if phase not in {"BLOCKED", "IN_PROGRESS"}:
        raise WorkflowError(f"resume requires BLOCKED or IN_PROGRESS, found {phase}")
    require_approval_record(metadata, revision)
    repo = command_repo(args)
    require_execution_vcs(metadata, repo)
    require_current_none_baseline(metadata, repo)
    validate_task_state(metadata, args.plan, repo)
    if phase == "IN_PROGRESS":
        print(f"execution active for {metadata['plan_id']} revision {revision}")
        return
    metadata["phase"] = "IN_PROGRESS"
    write_document(args.plan, metadata, order, body)
    print(f"resumed {metadata['plan_id']} revision {revision}")


def command_validate(args: argparse.Namespace) -> None:
    """Validate the plan state without printing its full metadata."""
    metadata, _, _ = parse_document(args.plan)
    revision, phase = require_common(metadata)
    if phase in {"APPROVED", "IN_PROGRESS", "COMPLETED"}:
        require_approval_record(metadata, revision)
        repo = command_repo(args)
        require_execution_vcs(metadata, repo)
        if phase == "COMPLETED":
            validate_completed_evidence(metadata, args.plan, repo)
        else:
            validate_task_state(metadata, args.plan, repo)
    else:
        resolve_vcs(metadata, command_repo(args))
    print(f"valid workflow state for {metadata['plan_id']} revision {revision} in {phase}")


def command_cleanup_legacy_lock(args: argparse.Namespace) -> None:
    """Explicitly remove one inactive pre-v0.5 adjacent plan lock."""
    legacy_lock = args.plan.parent / f".{args.plan.name}.lock"
    with document_access(args.plan) as directory:
        try:
            descriptor = directory.open_regular(legacy_lock.name, os.O_RDWR, delete_access=True)
        except FileNotFoundError:
            print(f"no legacy adjacent lock for {args.plan.name}")
            return
        try:
            with file_lock(descriptor, 0):
                directory.unlink_fd(descriptor, legacy_lock.name)
        except TimeoutError as exc:
            raise WorkflowError("legacy adjacent lock is held by another process") from exc
        finally:
            os.close(descriptor)
    print(f"removed inactive legacy adjacent lock for {args.plan.name}")


def command_transition(args: argparse.Namespace) -> None:
    """Apply a legal workflow phase transition."""
    metadata, order, body = parse_document(args.plan)
    revision, phase = require_common(metadata)
    target = args.phase
    if target not in ALLOWED_TRANSITIONS[phase]:
        raise WorkflowError(f"illegal transition: {phase} -> {target}")
    if target == "APPROVED":
        raise WorkflowError("use the approve command to enter APPROVED")
    if target == "COMPLETED":
        raise WorkflowError("use the complete command to enter COMPLETED")
    if target == "IN_PROGRESS":
        require_approval_record(metadata, revision)
        repo = command_repo(args)
        require_execution_vcs(metadata, repo)
        require_current_none_baseline(metadata, repo)
    if target == "AWAITING_CONFIRMATION" and phase in {"APPROVED", "IN_PROGRESS", "BLOCKED"}:
        if not args.increment_revision:
            raise WorkflowError("returning for re-approval requires --increment-revision")
        revision += 1
        metadata.update(
            {
                "revision": revision,
                "approved_revision": "",
                "approved_at": "",
                "confirmation_record": "",
                "approved_filesystem_policy_sha256": "",
            }
        )
    elif args.increment_revision:
        raise WorkflowError("--increment-revision is only valid when returning for re-approval")
    metadata["phase"] = target
    write_document(args.plan, metadata, order, body)
    print(f"transitioned {phase} -> {target} at revision {revision}")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    inspect_parser = subparsers.add_parser("inspect", help="print normalized workflow state")
    inspect_parser.add_argument("plan", type=Path)
    inspect_parser.set_defaults(handler=command_inspect)

    experience_parser = subparsers.add_parser(
        "experience",
        help="print normalized title and progress heartbeat settings",
    )
    experience_parser.add_argument("plan", type=Path)
    experience_parser.set_defaults(handler=command_experience)

    init_parser = subparsers.add_parser("init", help="initialize a plan for confirmation")
    init_parser.add_argument("plan", type=Path)
    init_parser.add_argument("--plan-id", required=True)
    init_parser.add_argument("--repo", type=Path, help="workspace root; defaults to current directory")
    init_parser.add_argument("--vcs-mode", choices=sorted(VALID_VCS_MODES), default="AUTO")
    init_parser.set_defaults(handler=command_init)

    baseline_parser = subparsers.add_parser(
        "create-baseline", help="create and bind immutable VCS NONE baseline evidence"
    )
    baseline_parser.add_argument("plan", type=Path)
    baseline_parser.add_argument("--repo", required=True, type=Path)
    baseline_parser.add_argument("--output", type=Path)
    baseline_parser.add_argument("--scope", action="append", default=[])
    baseline_parser.add_argument("--exclude", action="append", default=[])
    baseline_parser.add_argument("--write-scope", action="append", default=[])
    baseline_parser.add_argument(
        "--replace-if-sha256",
        help="recover an existing baseline only when its canonical JSON SHA-256 matches",
    )
    baseline_parser.set_defaults(handler=command_create_baseline)

    approve_parser = subparsers.add_parser("approve", help="record explicit user approval")
    approve_parser.add_argument("plan", type=Path)
    approve_parser.add_argument("--confirmation", required=True)
    approve_parser.add_argument("--at", help="ISO-8601 approval time; defaults to current UTC")
    approve_parser.add_argument("--repo", type=Path, help="workspace root")
    approve_parser.set_defaults(handler=command_approve)

    check_parser = subparsers.add_parser("check-execute", help="validate execution eligibility")
    check_parser.add_argument("plan", type=Path)
    check_parser.add_argument("--repo", type=Path, help="workspace root")
    check_parser.set_defaults(handler=command_check_execute)

    start_parser = subparsers.add_parser(
        "start-execution", help="atomically record approval and enter execution"
    )
    start_parser.add_argument("plan", type=Path)
    start_parser.add_argument("--confirmation", required=True)
    start_parser.add_argument("--at", help="ISO-8601 approval time; defaults to current UTC")
    start_parser.add_argument("--repo", type=Path, help="workspace root")
    start_parser.set_defaults(handler=command_start_execution)

    complete_parser = subparsers.add_parser(
        "complete", help="complete a currently executing plan"
    )
    complete_parser.add_argument("plan", type=Path)
    complete_parser.add_argument("--repo", type=Path, help="workspace root")
    complete_parser.set_defaults(handler=command_complete)

    resume_parser = subparsers.add_parser(
        "resume", help="resume a blocked plan after replaying execution gates"
    )
    resume_parser.add_argument("plan", type=Path)
    resume_parser.add_argument("--repo", type=Path, help="workspace root")
    resume_parser.set_defaults(handler=command_resume)

    validate_parser = subparsers.add_parser("validate", help="validate workflow state")
    validate_parser.add_argument("plan", type=Path)
    validate_parser.add_argument("--repo", type=Path, help="workspace root")
    validate_parser.set_defaults(handler=command_validate)

    cleanup_parser = subparsers.add_parser(
        "cleanup-legacy-lock",
        help="explicitly remove one inactive pre-v0.5 adjacent plan lock",
    )
    cleanup_parser.add_argument("plan", type=Path)
    cleanup_parser.add_argument("--repo", type=Path, help="workspace root")
    cleanup_parser.set_defaults(handler=command_cleanup_legacy_lock)

    transition_parser = subparsers.add_parser("transition", help="apply a legal phase transition")
    transition_parser.add_argument("plan", type=Path)
    transition_parser.add_argument("phase", choices=sorted(VALID_PHASES))
    transition_parser.add_argument("--increment-revision", action="store_true")
    transition_parser.add_argument("--repo", type=Path, help="workspace root")
    transition_parser.set_defaults(handler=command_transition)

    for mutation_parser in (
        init_parser,
        baseline_parser,
        approve_parser,
        start_parser,
        complete_parser,
        resume_parser,
        transition_parser,
        cleanup_parser,
    ):
        mutation_parser.add_argument("--expected-revision", type=int)
        mutation_parser.add_argument("--expected-phase", choices=sorted(VALID_PHASES))
        mutation_parser.add_argument(
            "--expected-sha256",
            "--expected-digest",
            dest="expected_sha256",
        )
    return parser


def main() -> int:
    """Run the workflow state command."""
    configure_stdio()
    parser = build_parser()
    args = parser.parse_args()
    try:
        normalize_command_paths(args)
        if args.command in MUTATION_COMMANDS:
            with locked_plan(args.plan, repo=getattr(args, "repo", None)):
                require_expected_plan(args)
                args.handler(args)
        else:
            args.handler(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
