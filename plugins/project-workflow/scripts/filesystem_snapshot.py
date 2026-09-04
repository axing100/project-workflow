#!/usr/bin/env python3
"""Create and compare deterministic file-system evidence for VCS NONE workflows."""

from __future__ import annotations

import argparse
from platform_io import SecureDirectory, configure_stdio, file_lock
import hashlib
import json
import os
import secrets
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Sequence, Tuple


SCHEMA = "project-workflow/filesystem-snapshot/v1"
DIFF_SCHEMA = "project-workflow/filesystem-diff/v1"
FINAL_EVIDENCE_SCHEMA = "project-workflow/filesystem-final-evidence/v1"
EXCLUDED_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "node_modules",
}
LEGACY_EXCLUDED_DIRECTORIES = {".idea", ".vscode"}
EXCLUDED_FILES = {".DS_Store"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".swp", ".tmp"}


class SnapshotError(ValueError):
    """Report an invalid snapshot request without exposing an internal traceback."""


def canonical_json_sha256(payload: object) -> str:
    """Return the SHA-256 of one canonical JSON value."""
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _no_follow_flag() -> int:
    """Return the platform no-follow flag or fail closed when it is unavailable."""
    flag = getattr(os, "O_NOFOLLOW", None)
    if flag is None:
        raise SnapshotError("secure no-follow filesystem operations are unavailable")
    return flag


def _directory_flags() -> int:
    """Return flags for opening one trusted directory component."""
    directory = getattr(os, "O_DIRECTORY", None)
    if directory is None:
        raise SnapshotError("secure directory filesystem operations are unavailable")
    return os.O_RDONLY | directory | getattr(os, "O_CLOEXEC", 0) | _no_follow_flag()


def normalize_relative_path(value: str) -> str:
    """Return one safe workspace-relative POSIX path."""
    path = PurePosixPath(value.replace("\\", "/"))
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise SnapshotError(f"path must stay inside the workspace: {value}")
    normalized = path.as_posix()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized == ".":
        raise SnapshotError(f"path must identify workspace content: {value}")
    return normalized.rstrip("/")


def normalize_scopes(scopes: Optional[Sequence[str]]) -> List[str]:
    """Normalize, de-duplicate, and sort optional write scopes."""
    return sorted({normalize_relative_path(scope) for scope in scopes or []})


def path_in_scope(path: str, scopes: Sequence[str]) -> bool:
    """Return whether a changed path belongs to at least one declared scope."""
    if not scopes:
        return True
    candidate = PurePosixPath(path)
    for scope in scopes:
        scoped = PurePosixPath(scope)
        if candidate == scoped or scoped in candidate.parents:
            return True
    return False


def path_intersects_scope(path: str, scopes: Sequence[str]) -> bool:
    """Return whether a directory contains or belongs to a selected snapshot scope."""
    if not scopes:
        return True
    candidate = PurePosixPath(path)
    for scope in scopes:
        scoped = PurePosixPath(scope)
        if candidate == scoped or scoped in candidate.parents or candidate in scoped.parents:
            return True
    return False


def excluded_path(
    relative: PurePosixPath,
    is_directory: bool,
    excludes: Sequence[str],
    legacy_ide_excludes: bool = False,
) -> bool:
    """Return whether a path is plugin state, cache, IDE state, or temporary output."""
    parts = relative.parts
    if len(parts) >= 2 and parts[0] == ".codex" and parts[1] == "project-workflow":
        return True
    if any(part in EXCLUDED_DIRECTORIES for part in parts):
        return True
    if legacy_ide_excludes and any(part in LEGACY_EXCLUDED_DIRECTORIES for part in parts):
        return True
    relative_text = relative.as_posix()
    if any(path_in_scope(relative_text, [excluded]) for excluded in excludes):
        return True
    if is_directory:
        return False
    return relative.name in EXCLUDED_FILES or relative.suffix.lower() in EXCLUDED_SUFFIXES


def _identity(file_stat: os.stat_result) -> Tuple[Any, ...]:
    """Return fields that must remain stable while snapshot evidence is collected."""
    return (
        file_stat.st_dev,
        file_stat.st_ino,
        file_stat.st_mode,
        file_stat.st_nlink,
        file_stat.st_uid,
        file_stat.st_gid,
        file_stat.st_size,
        file_stat.st_mtime,
        file_stat.st_ctime,
    )


def _hash_regular_file(
    path: Path, dir_fd: Optional[int] = None
) -> Tuple[int, str, int]:
    """Hash one regular file through a no-follow descriptor and verify its identity."""
    if os.name == "nt":
        with SecureDirectory(path.parent.resolve()) as directory:
            return _hash_secure_file(directory, path.name)
    digest = hashlib.sha256()
    size = 0
    display_name = os.fspath(path)
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | _no_follow_flag()
    descriptor = -1
    try:
        before = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode):
            raise SnapshotError(f"unsupported workspace file type: {display_name}")
        descriptor = os.open(path, flags, dir_fd=dir_fd)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or _identity(before) != _identity(opened):
            raise SnapshotError(f"workspace file changed before reading: {display_name}")
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
        finished = os.fstat(descriptor)
        if _identity(opened) != _identity(finished) or size != finished.st_size:
            raise SnapshotError(f"workspace file changed while reading: {display_name}")
    except SnapshotError:
        raise
    except OSError as exc:
        detail = exc.strerror or str(exc)
        raise SnapshotError(
            f"cannot safely read workspace file: {display_name}: {detail}"
        ) from exc
    finally:
        if descriptor >= 0:
            while True:
                try:
                    os.close(descriptor)
                    break
                except InterruptedError:
                    continue
    return size, digest.hexdigest(), opened.st_mode & 0o7777


def hash_file(path: Path) -> Tuple[int, str]:
    """Return a regular file's byte size and SHA-256 digest."""
    size, digest, _ = _hash_regular_file(path)
    return size, digest


def _symlink_record(path: Path, dir_fd: Optional[int] = None) -> Tuple[int, str, int]:
    """Hash only a symbolic link's target text without following the target."""
    display_name = os.fspath(path)
    try:
        before = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
        if not stat.S_ISLNK(before.st_mode):
            raise SnapshotError(f"workspace symlink changed before reading: {display_name}")
        target = os.readlink(path, dir_fd=dir_fd).encode("utf-8", errors="surrogateescape")
        finished = os.stat(path, dir_fd=dir_fd, follow_symlinks=False)
        if _identity(before) != _identity(finished):
            raise SnapshotError(f"workspace symlink changed while reading: {display_name}")
    except SnapshotError:
        raise
    except OSError as exc:
        raise SnapshotError(
            f"cannot safely read workspace symlink: {display_name}: {exc.strerror or exc}"
        ) from exc
    return (
        len(target),
        hashlib.sha256(b"symlink\0" + target).hexdigest(),
        before.st_mode & 0o7777,
    )


def symlink_record(path: Path) -> Tuple[int, str]:
    """Return a symbolic link target's byte size and SHA-256 digest."""
    size, digest, _ = _symlink_record(path)
    return size, digest


def _hash_secure_file(directory: SecureDirectory, name: str) -> Tuple[int, str, int]:
    """Hash the opened identity and reject replacement or concurrent mutation."""
    before = directory.stat(name)
    with os.fdopen(directory.open_regular(name, os.O_RDONLY), "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _identity(before) != _identity(opened):
            raise SnapshotError(f"workspace file changed before reading: {name}")
        digest = hashlib.sha256()
        size = 0
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
        finished = os.fstat(stream.fileno())
        if _identity(opened) != _identity(finished) or size != finished.st_size:
            raise SnapshotError(f"workspace file changed while reading: {name}")
    return size, digest.hexdigest(), opened.st_mode & 0o7777


def _windows_records(root: Path, current: Path, scopes, excludes, legacy):
    """Enumerate anchored Windows directories without following reparse points."""
    with SecureDirectory(current, root=root) as directory:
        for name in sorted(directory.list_names()):
            path = current / name
            relative = PurePosixPath(path.relative_to(root).as_posix())
            entry = directory.stat(name)
            is_directory = stat.S_ISDIR(entry.st_mode)
            if excluded_path(relative, is_directory, excludes, legacy):
                continue
            text = relative.as_posix()
            if getattr(entry, "st_file_attributes", 0) & 0x400:
                if path_in_scope(text, scopes):
                    target = directory.readlink(name).encode("utf-8", errors="surrogateescape")
                    if _identity(entry) != _identity(directory.stat(name)):
                        raise SnapshotError(f"workspace link changed while reading: {path}")
                    yield {"path": text, "type": "symlink", "size": len(target),
                           "sha256": hashlib.sha256(b"symlink\0" + target).hexdigest(),
                           "mode": entry.st_mode & 0o7777}
            elif is_directory:
                if path_intersects_scope(text, scopes):
                    if text != ".codex":
                        yield {"path": text, "type": "directory", "mode": entry.st_mode & 0o7777}
                    yield from _windows_records(root, path, scopes, excludes, legacy)
            elif path_in_scope(text, scopes):
                if not stat.S_ISREG(entry.st_mode):
                    raise SnapshotError(f"unsupported workspace file type: {text}")
                size, digest, mode = _hash_secure_file(directory, name)
                if _identity(entry) != _identity(directory.stat(name)):
                    raise SnapshotError(f"workspace file changed while reading: {path}")
                yield {"path": text, "type": "file", "size": size,
                       "sha256": digest, "mode": mode}


def build_snapshot(
    repo: Path,
    scopes: Optional[Sequence[str]] = None,
    excludes: Optional[Sequence[str]] = None,
    legacy_ide_excludes: bool = False,
) -> Dict[str, Any]:
    """Build a deterministic content manifest without following symbolic links."""
    root = repo.expanduser().resolve()
    if not root.is_dir():
        raise SnapshotError(f"workspace is not a readable directory: {root}")
    normalized_scopes = normalize_scopes(scopes)
    normalized_excludes = normalize_scopes(excludes)
    records: List[Dict[str, Any]] = []
    if os.name == "nt":
        try:
            records = list(_windows_records(root, root, normalized_scopes, normalized_excludes, legacy_ide_excludes))
        except (OSError, ValueError) as exc:
            raise SnapshotError(f"cannot inspect workspace: {exc}") from exc
        return {"schema": SCHEMA, "scopes": normalized_scopes, "excludes": normalized_excludes,
                "directory_records": True, "files": sorted(records, key=lambda item: item["path"])}

    def raise_walk_error(error: OSError) -> None:
        """Reject unreadable or unstable directories instead of omitting evidence."""
        raise SnapshotError(
            f"cannot inspect workspace directory: {error.filename or root}: "
            f"{error.strerror or error}"
        ) from error

    for current, directory_names, file_names, current_fd in os.fwalk(
        str(root), topdown=True, onerror=raise_walk_error, follow_symlinks=False
    ):
        current_path = Path(current)
        kept_directories: List[str] = []
        for name in sorted(directory_names):
            path = current_path / name
            relative = PurePosixPath(path.relative_to(root).as_posix())
            if excluded_path(relative, True, normalized_excludes, legacy_ide_excludes):
                continue
            try:
                entry_stat = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
            except OSError as exc:
                raise SnapshotError(
                    f"cannot inspect workspace entry: {relative.as_posix()}: "
                    f"{exc.strerror or exc}"
                ) from exc
            if stat.S_ISLNK(entry_stat.st_mode):
                if path_in_scope(relative.as_posix(), normalized_scopes):
                    size, digest, mode = _symlink_record(Path(name), current_fd)
                    records.append(
                        {
                            "path": relative.as_posix(),
                            "type": "symlink",
                            "size": size,
                            "sha256": digest,
                            "mode": mode,
                        }
                    )
                continue
            if not stat.S_ISDIR(entry_stat.st_mode):
                raise SnapshotError(
                    f"unsupported workspace entry type: {relative.as_posix()}"
                )
            if relative.as_posix() != ".codex" and path_intersects_scope(
                relative.as_posix(), normalized_scopes
            ):
                records.append(
                    {
                        "path": relative.as_posix(),
                        "type": "directory",
                        "mode": entry_stat.st_mode & 0o7777,
                    }
                )
            if path_intersects_scope(relative.as_posix(), normalized_scopes):
                kept_directories.append(name)
        directory_names[:] = kept_directories

        for name in sorted(file_names):
            path = current_path / name
            relative = PurePosixPath(path.relative_to(root).as_posix())
            relative_text = relative.as_posix()
            if excluded_path(
                relative, False, normalized_excludes, legacy_ide_excludes
            ) or not path_in_scope(
                relative_text, normalized_scopes
            ):
                continue
            try:
                entry_stat = os.stat(name, dir_fd=current_fd, follow_symlinks=False)
            except OSError as exc:
                raise SnapshotError(
                    f"cannot inspect workspace entry: {relative_text}: {exc.strerror or exc}"
                ) from exc
            if stat.S_ISLNK(entry_stat.st_mode):
                size, digest, mode = _symlink_record(Path(name), current_fd)
                record_type = "symlink"
            elif stat.S_ISREG(entry_stat.st_mode):
                size, digest, mode = _hash_regular_file(Path(name), current_fd)
                record_type = "file"
            else:
                raise SnapshotError(f"unsupported workspace file type: {relative_text}")
            records.append(
                {
                    "path": relative_text,
                    "type": record_type,
                    "size": size,
                    "sha256": digest,
                    "mode": mode,
                }
            )

    records.sort(key=lambda record: record["path"])
    return {
        "schema": SCHEMA,
        "scopes": normalized_scopes,
        "excludes": normalized_excludes,
        "directory_records": True,
        "files": records,
    }


def validate_snapshot(snapshot: object) -> Dict[str, Any]:
    """Validate a persisted snapshot and return its normalized dictionary."""
    if not isinstance(snapshot, dict) or snapshot.get("schema") != SCHEMA:
        raise SnapshotError("unsupported filesystem snapshot schema")
    files = snapshot.get("files")
    scopes = snapshot.get("scopes", [])
    excludes = snapshot.get("excludes")
    directory_records = snapshot.get("directory_records")
    if not isinstance(files, list) or not isinstance(scopes, list):
        raise SnapshotError("filesystem snapshot files and scopes must be lists")
    seen = set()
    for record in files:
        if not isinstance(record, dict):
            raise SnapshotError("filesystem snapshot contains an invalid file record")
        path = record.get("path")
        if not isinstance(path, str) or normalize_relative_path(path) != path or path in seen:
            raise SnapshotError("filesystem snapshot contains an invalid or duplicate path")
        record_type = record.get("type")
        if record_type not in {"file", "symlink", "directory"}:
            raise SnapshotError(f"filesystem snapshot has invalid type for {path}")
        size = record.get("size")
        digest = record.get("sha256")
        mode = record.get("mode")
        if record_type == "directory":
            if "size" in record or "sha256" in record:
                raise SnapshotError(f"filesystem snapshot has invalid directory data for {path}")
        else:
            if type(size) is not int or size < 0:
                raise SnapshotError(f"filesystem snapshot has invalid size for {path}")
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise SnapshotError(f"filesystem snapshot has invalid digest for {path}")
        if mode is not None and (type(mode) is not int or mode < 0 or mode > 0o7777):
            raise SnapshotError(f"filesystem snapshot has invalid mode for {path}")
        if record_type == "directory" and mode is None:
            raise SnapshotError(f"filesystem snapshot has invalid mode for {path}")
        seen.add(path)
    if normalize_scopes(scopes) != scopes:
        raise SnapshotError("filesystem snapshot scopes must be normalized and unique")
    if excludes is not None and (
        not isinstance(excludes, list) or normalize_scopes(excludes) != excludes
    ):
        raise SnapshotError("filesystem snapshot excludes must be normalized and unique")
    if directory_records is not None and directory_records is not True:
        raise SnapshotError("filesystem snapshot directory_records must be true")
    return snapshot


def compare_snapshots(
    baseline: Dict[str, Any], current: Dict[str, Any], write_scopes: Optional[Sequence[str]] = None
) -> Dict[str, Any]:
    """Return deterministic added, modified, deleted, and out-of-scope paths."""
    validate_snapshot(baseline)
    validate_snapshot(current)
    before = {record["path"]: record for record in baseline["files"]}
    after = {record["path"]: record for record in current["files"]}
    if baseline.get("directory_records") is not True:
        after = {path: record for path, record in after.items() if record["type"] != "directory"}
    added = sorted(after.keys() - before.keys())
    deleted = sorted(before.keys() - after.keys())
    modified = []
    for path in sorted(before.keys() & after.keys()):
        old_record = before[path]
        new_record = after[path]
        if "mode" not in old_record:
            new_record = {key: value for key, value in new_record.items() if key != "mode"}
        if old_record != new_record:
            modified.append(path)
    scopes = normalize_scopes(write_scopes)
    changed = sorted(set(added + modified + deleted))
    return {
        "schema": DIFF_SCHEMA,
        "added": added,
        "modified": modified,
        "deleted": deleted,
        "out_of_scope": [path for path in changed if not path_in_scope(path, scopes)],
    }


def _open_internal_parent_fd(repo: Path, path: Path, create: bool) -> Tuple[Path, int]:
    """Open and hold one trusted internal-state parent directory."""
    target = internal_state_path(repo, path)
    root = repo.expanduser().resolve()
    directory_flags = _directory_flags()
    directory_fd = os.open(root, directory_flags)
    try:
        for part in target.parent.relative_to(root).parts:
            try:
                next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(part, mode=0o755, dir_fd=directory_fd)
                os.fsync(directory_fd)
                next_fd = os.open(part, directory_flags, dir_fd=directory_fd)
            os.close(directory_fd)
            directory_fd = next_fd
    except Exception:
        os.close(directory_fd)
        raise
    return target, directory_fd


def atomic_write_json(
    path: Path,
    payload: Dict[str, Any],
    repo: Optional[Path] = None,
    *,
    create_only: bool = False,
    expected_sha256: Optional[str] = None,
) -> None:
    """Atomically publish JSON with optional create-only or digest-CAS semantics."""
    if create_only and expected_sha256 is not None:
        raise SnapshotError("create-only and digest-CAS modes are mutually exclusive")
    if expected_sha256 is not None and (
        len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256.lower())
    ):
        raise SnapshotError("expected SHA-256 must contain exactly 64 hexadecimal characters")
    target = internal_state_path(repo, path) if repo is not None else path.parent.resolve() / path.name
    root = repo.resolve() if repo is not None else None
    with SecureDirectory(target.parent, root=root, create=True) as directory:
        descriptor = directory.open_regular(f".lock-{target.name}", os.O_RDWR | os.O_CREAT)
        try:
            with file_lock(descriptor):
                if expected_sha256 is not None:
                    try:
                        with os.fdopen(directory.open_regular(target.name, os.O_RDONLY),
                                       "r", encoding="utf-8") as stream:
                            existing = json.load(stream)
                    except (OSError, ValueError) as exc:
                        raise SnapshotError(f"cannot verify existing JSON for digest-CAS: {exc}") from exc
                    actual = canonical_json_sha256(existing)
                    if actual != expected_sha256.lower():
                        raise SnapshotError(f"existing JSON digest conflict: expected {expected_sha256.lower()}, found {actual}")
                content = (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
                try:
                    directory.write_atomic(target.name, content, create_only=create_only)
                except FileExistsError as exc:
                    raise SnapshotError(f"JSON target already exists: {target}") from exc
        finally:
            os.close(descriptor)


def internal_state_path(repo: Path, path: Path) -> Path:
    """Return an internal workflow-state path or reject an external target."""
    repo_input = repo.expanduser().absolute()
    root = repo_input.resolve()
    requested = path.expanduser()
    if not requested.is_absolute():
        requested = root / requested
    else:
        try:
            requested = root / requested.absolute().relative_to(repo_input)
        except ValueError:
            pass
    target = Path(os.path.abspath(str(requested)))
    state_root = root / ".codex/project-workflow"
    try:
        target.relative_to(state_root)
    except ValueError as exc:
        raise SnapshotError(
            "snapshot paths must stay under .codex/project-workflow in the workspace"
        ) from exc
    current = root
    relative_parts = target.relative_to(root).parts
    for part in relative_parts:
        current = current / part
        if current.is_symlink():
            raise SnapshotError(
                "snapshot paths must not traverse a symbolic link under "
                ".codex/project-workflow"
            )
    return target


def read_snapshot(path: Path, repo: Optional[Path] = None) -> Dict[str, Any]:
    """Read and validate one persisted snapshot document."""
    payload = read_json_document(path, repo)
    return validate_snapshot(payload)


def read_json_document(path: Path, repo: Optional[Path] = None) -> Dict[str, Any]:
    """Read one persisted JSON object with a stable error surface."""
    try:
        target = internal_state_path(repo, path) if repo is not None else path.parent.resolve() / path.name
        with SecureDirectory(target.parent, root=repo.resolve() if repo is not None else None) as directory:
            with os.fdopen(directory.open_regular(target.name, os.O_RDONLY), "r", encoding="utf-8") as stream:
                opened = os.fstat(stream.fileno())
                payload = json.load(stream)
                if _identity(opened) != _identity(os.fstat(stream.fileno())):
                    raise SnapshotError(f"filesystem JSON changed while reading: {target}")
    except (OSError, ValueError) as exc:
        raise SnapshotError(f"cannot read filesystem JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SnapshotError("filesystem JSON must contain an object")
    return payload


def command_create(args: argparse.Namespace) -> int:
    """Create an atomic baseline snapshot."""
    snapshot = build_snapshot(args.repo, args.scope, args.exclude)
    output = internal_state_path(args.repo, args.output)
    atomic_write_json(
        output,
        snapshot,
        args.repo,
        create_only=args.replace_if_sha256 is None,
        expected_sha256=args.replace_if_sha256,
    )
    result = snapshot if args.json_details else {
        "schema": SCHEMA,
        "file_count": sum(
            record["type"] != "directory" for record in snapshot["files"]
        ),
        "scopes": snapshot["scopes"],
        "excludes": snapshot["excludes"],
        "output": output.relative_to(args.repo.expanduser().resolve()).as_posix(),
        "sha256": canonical_json_sha256(snapshot),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def command_compare(args: argparse.Namespace) -> int:
    """Compare the current workspace with a persisted baseline."""
    baseline = read_snapshot(internal_state_path(args.repo, args.baseline), args.repo)
    legacy_excludes = "excludes" not in baseline
    current = build_snapshot(
        args.repo,
        baseline.get("scopes"),
        baseline.get("excludes", []),
        legacy_ide_excludes=legacy_excludes,
    )
    result = compare_snapshots(baseline, current, args.write_scope)
    if args.output is not None:
        output = internal_state_path(args.repo, args.output)
        atomic_write_json(output, result, args.repo)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 3 if result["out_of_scope"] and not args.report_only else 0


def build_parser() -> argparse.ArgumentParser:
    """Build the public snapshot command parser."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    create_parser = subparsers.add_parser("create", help="create a filesystem baseline")
    create_parser.add_argument("--repo", required=True, type=Path)
    create_parser.add_argument("--output", required=True, type=Path)
    create_parser.add_argument("--scope", action="append", default=[])
    create_parser.add_argument("--exclude", action="append", default=[])
    create_parser.add_argument("--json-details", action="store_true")
    create_parser.add_argument(
        "--replace-if-sha256",
        help="replace an existing baseline only when its canonical JSON SHA-256 matches",
    )
    create_parser.set_defaults(handler=command_create)

    compare_parser = subparsers.add_parser("compare", help="compare against a baseline")
    compare_parser.add_argument("--repo", required=True, type=Path)
    compare_parser.add_argument("--baseline", required=True, type=Path)
    compare_parser.add_argument("--write-scope", action="append", default=[])
    compare_parser.add_argument("--output", type=Path)
    compare_parser.add_argument("--report-only", action="store_true")
    compare_parser.set_defaults(handler=command_compare)
    return parser


def main() -> int:
    """Execute one snapshot command with a stable error surface."""
    configure_stdio()
    args = build_parser().parse_args()
    try:
        return args.handler(args)
    except (OSError, SnapshotError) as exc:
        print(f"filesystem snapshot error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
