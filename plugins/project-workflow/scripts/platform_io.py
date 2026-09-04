"""Secure local filesystem primitives shared by workflow tools (Python 3.9+)."""

from __future__ import annotations

import math
import os
import secrets
import stat
import time
import sys
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

if os.name == "nt":
    import windows_io as backend
else:
    import fcntl


def require_capabilities() -> None:
    """Fail explicitly if this platform cannot provide anchored local I/O."""
    if os.name == "nt":
        backend.require_capabilities()
    elif not all(hasattr(os, flag) for flag in ("O_NOFOLLOW", "O_DIRECTORY")):
        raise OSError("secure descriptor-relative filesystem operations are unavailable")


def configure_stdio() -> None:
    """Keep CLI UTF-8 output usable without mutating streams during import."""
    if os.name == "nt":
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if reconfigure is not None:
                reconfigure(encoding="utf-8", errors="backslashreplace")


def validate_component(name: str) -> str:
    """Validate one literal child name, never a path or traversal expression."""
    if not isinstance(name, str) or not name or name in (".", ".."):
        raise ValueError("a non-empty literal filename is required")
    if "/" in name or "\\" in name or "\0" in name:
        raise ValueError("filename must not contain a path separator or NUL")
    if os.name == "nt":
        backend.validate_component(name)
    return name


def set_file_mode(descriptor: int, mode: int) -> None:
    """Preserve POSIX modes; Windows uses inherited ACLs, not POSIX chmod."""
    if os.name != "nt":
        os.fchmod(descriptor, mode)


def lock_file(descriptor: int, timeout_seconds: float = 30.0) -> None:
    """Acquire an exclusive OS lock with a finite monotonic deadline."""
    if isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds < 0:
        raise ValueError("lock timeout must be finite and non-negative")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            if os.name == "nt":
                backend.lock_file(descriptor)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out acquiring workflow file lock")
            time.sleep(min(0.05, remaining))


def unlock_file(descriptor: int) -> None:
    """Release the same byte range / flock acquired by lock_file."""
    if os.name == "nt":
        backend.unlock_file(descriptor)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_UN)


@contextmanager
def file_lock(descriptor: int, timeout_seconds: float = 30.0):
    """Release an acquired lock even when the protected operation raises."""
    lock_file(descriptor, timeout_seconds)
    try:
        yield
    finally:
        unlock_file(descriptor)


class SecureDirectory:
    """Hold a trusted directory and operate only on literal child entries.

    Windows holds every ancestor without FILE_SHARE_DELETE. POSIX operations are
    descriptor-relative, retaining the existing inode and flock contract.
    Callers must close this object, preferably using a with statement.
    """

    def __init__(self, path: Path, root: Optional[Path] = None, create: bool = False):
        require_capabilities()
        self.path = Path(os.path.abspath(os.fspath(path)))
        self.parent_fd = -1
        self._windows = None
        anchor = Path(os.path.abspath(os.fspath(root))) if root is not None else Path(self.path.anchor)
        relative = self.path.relative_to(anchor)
        if os.name == "nt":
            self._windows = backend.WindowsDirectory(self.path, create=create)
            return
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(anchor, flags)
        try:
            for component in relative.parts:
                validate_component(component)
                try:
                    child = os.open(component, flags, dir_fd=descriptor)
                except FileNotFoundError:
                    if not create:
                        raise
                    try:
                        os.mkdir(component, 0o700, dir_fd=descriptor)
                    except FileExistsError:
                        pass
                    child = os.open(component, flags, dir_fd=descriptor)
                    os.fsync(descriptor)
                os.close(descriptor)
                descriptor = child
            self.parent_fd = descriptor
        except BaseException:
            os.close(descriptor)
            raise

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self) -> None:
        """Idempotently release all directory handles."""
        if self._windows is not None:
            self._windows.close()
        if self.parent_fd >= 0:
            os.close(self.parent_fd)
            self.parent_fd = -1

    def open_regular(self, name: str, flags: int, mode: int = 0o600, delete_access: bool = False) -> int:
        """Open a no-follow ordinary file and return an owned Python fd."""
        validate_component(name)
        if self._windows is not None:
            return self._windows.open_regular(name, flags, mode, delete_access=delete_access)
        for attempt in range(3):
            try:
                descriptor = os.open(name, flags | os.O_NOFOLLOW | getattr(os, "O_NONBLOCK", 0), mode, dir_fd=self.parent_fd)
                break
            except FileNotFoundError:
                # APFS may report ENOENT during competing create/open calls.
                # Retry the same anchored, no-follow create; never retry reads.
                if not flags & os.O_CREAT or flags & os.O_EXCL or attempt == 2:
                    raise
                time.sleep(0.01)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise OSError("workflow entry is not a regular file: " + name)
        return descriptor

    def stat(self, name: str):
        """Read child metadata without following links or reparse points."""
        validate_component(name)
        if self._windows is not None:
            return self._windows.stat(name)
        return os.stat(name, dir_fd=self.parent_fd, follow_symlinks=False)

    def list_names(self):
        """Enumerate the held directory, without recursively following entries."""
        if self._windows is not None:
            return self._windows.list_names()
        return os.listdir(self.parent_fd)

    def readlink(self, name: str) -> str:
        """Read only link text; callers must compare metadata around this call."""
        validate_component(name)
        if self._windows is not None:
            return self._windows.readlink(name)
        return os.readlink(name, dir_fd=self.parent_fd)

    def replace(self, source: str, target: str, create_only: bool = False) -> None:
        """Publish within one held directory, optionally refusing overwrite."""
        validate_component(source)
        validate_component(target)
        if self._windows is not None:
            self._windows.replace(source, target, create_only=create_only)
        elif create_only:
            os.link(source, target, src_dir_fd=self.parent_fd, dst_dir_fd=self.parent_fd, follow_symlinks=False)
            os.unlink(source, dir_fd=self.parent_fd)
        else:
            os.replace(source, target, src_dir_fd=self.parent_fd, dst_dir_fd=self.parent_fd)

    def unlink(self, name: str) -> None:
        """Remove a child without following it outside the trusted directory."""
        validate_component(name)
        if self._windows is not None:
            self._windows.unlink(name)
        else:
            os.unlink(name, dir_fd=self.parent_fd)

    def unlink_fd(self, descriptor: int, name: str) -> None:
        """Remove an opened legacy lock while its lock remains held.

        Windows requires open_regular(delete_access=True); POSIX verifies that
        the anchored leaf still names the locked inode before removing it.
        """
        validate_component(name)
        if self._windows is not None:
            self._windows.unlink_fd(descriptor)
        else:
            opened = os.fstat(descriptor)
            current = self.stat(name)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise OSError("legacy lock identity changed before deletion")
            self.unlink(name)

    def sync(self) -> bool:
        """Fsync directory metadata on POSIX; report Windows unsupported as False.

        Windows FlushFileBuffers does not provide a supported directory-fsync
        contract. File contents are flushed before publication on both platforms;
        this method must not be interpreted as a Windows power-loss guarantee.
        """
        if self._windows is not None:
            return False
        os.fsync(self.parent_fd)
        return True

    def write_atomic(self, name: str, content: bytes, mode: int = 0o600, create_only: bool = False) -> None:
        """Flush content then publish atomically, preserving old data on failure."""
        validate_component(name)
        if self._windows is not None:
            self._windows.write_atomic(name, content, create_only=create_only)
            return
        temporary = "." + name + "." + secrets.token_hex(12) + ".tmp"
        descriptor = self.open_regular(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                set_file_mode(stream.fileno(), mode)
                os.fsync(stream.fileno())
            self.replace(temporary, name, create_only=create_only)
            temporary = ""
            self.sync()
        finally:
            if temporary:
                try:
                    self.unlink(temporary)
                except FileNotFoundError:
                    pass
