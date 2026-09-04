"""Native Windows local-disk I/O; never substitute checks for handle protection.

Directory handles deny delete sharing for their entire lifetime. Child operations
are relative to pinned handles and never traverse a re-resolved ancestor pathname.
Reparse points are opened without following them and rejected before regular I/O.
"""

from __future__ import annotations

import ctypes
import errno
import os
import re
import secrets
import stat
import struct
import time
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

if os.name == "nt":
    import msvcrt
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _native = ctypes.WinDLL("ntdll", use_last_error=True)
else:
    _kernel = None
    _native = None

INVALID_HANDLE = ctypes.c_void_p(-1).value
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
DELETE = 0x10000
SHARE_READ_WRITE = 3
OPEN_EXISTING = 3
OPEN_ALWAYS = 4
CREATE_NEW = 1
OPEN_REPARSE = 0x00200000
BACKUP_SEMANTICS = 0x02000000
ATTRIBUTE_REPARSE = 0x400
ATTRIBUTE_DIRECTORY = 0x10
FILE_RENAME_INFO_CLASS = 3
FILE_DISPOSITION_INFO_CLASS = 4


class Overlapped(ctypes.Structure):
    """Architecture-correct synchronous LockFileEx range descriptor."""
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", wintypes.DWORD), ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE)]


class HandleInfo(ctypes.Structure):
    """Win32 file type, volume, identity, timestamps and link count."""
    _fields_ = [("attributes", wintypes.DWORD), ("creation", wintypes.FILETIME),
                ("access", wintypes.FILETIME), ("write", wintypes.FILETIME),
                ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD),
                ("size_low", wintypes.DWORD), ("links", wintypes.DWORD),
                ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]


class RenameInfo(ctypes.Structure):
    """Header for variable-length FILE_RENAME_INFO (not the Ex variant)."""
    _fields_ = [("replace", wintypes.BOOLEAN), ("root", wintypes.HANDLE),
                ("length", wintypes.DWORD), ("name", wintypes.WCHAR * 1)]


class IoStatus(ctypes.Structure):
    """Pointer-sized IO_STATUS_BLOCK storage for synchronous native calls.

    @author chenjiaxing
    @since 2026-09-05
    """
    _fields_ = [("status", ctypes.c_void_p), ("information", ctypes.c_size_t)]


class UnicodeString(ctypes.Structure):
    """Counted native UTF-16 string; backing storage remains caller-owned.

    @author chenjiaxing
    @since 2026-09-05
    """
    _fields_ = [("length", wintypes.USHORT), ("maximum", wintypes.USHORT),
                ("buffer", wintypes.LPWSTR)]


class ObjectAttributes(ctypes.Structure):
    """Native name lookup anchored to an existing directory handle.

    @author chenjiaxing
    @since 2026-09-05
    """
    _fields_ = [("length", wintypes.ULONG), ("root", wintypes.HANDLE),
                ("name", ctypes.POINTER(UnicodeString)), ("attributes", wintypes.ULONG),
                ("security", ctypes.c_void_p), ("quality", ctypes.c_void_p)]


def _declare() -> None:
    """Declare pointer-width-safe signatures once, only on Windows."""
    if _kernel is None:
        return
    signatures = {
        "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
        "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
        "GetFileInformationByHandle": ([wintypes.HANDLE, ctypes.POINTER(HandleInfo)], wintypes.BOOL),
        "SetFileInformationByHandle": ([wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD], wintypes.BOOL),
        "LockFileEx": ([wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)], wintypes.BOOL),
        "UnlockFileEx": ([wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(Overlapped)], wintypes.BOOL),
        "GetDriveTypeW": ([wintypes.LPCWSTR], wintypes.UINT),
        "DeviceIoControl": ([wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p], wintypes.BOOL),
    }
    for name, (arguments, result) in signatures.items():
        function = getattr(_kernel, name)
        function.argtypes = arguments
        function.restype = result
    _native.NtSetInformationFile.argtypes = [wintypes.HANDLE, ctypes.POINTER(IoStatus), ctypes.c_void_p, wintypes.ULONG, ctypes.c_int]
    _native.NtSetInformationFile.restype = wintypes.LONG
    _native.RtlNtStatusToDosError.argtypes = [wintypes.LONG]
    _native.RtlNtStatusToDosError.restype = wintypes.ULONG
    _native.NtCreateFile.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, ctypes.POINTER(ObjectAttributes), ctypes.POINTER(IoStatus), ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG, wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG]
    _native.NtCreateFile.restype = wintypes.LONG
    _native.NtQueryDirectoryFile.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(IoStatus), ctypes.c_void_p, wintypes.ULONG, ctypes.c_int, wintypes.BOOLEAN, ctypes.c_void_p, wintypes.BOOLEAN]
    _native.NtQueryDirectoryFile.restype = wintypes.LONG


_declare()


def require_capabilities() -> None:
    """Reject unsupported hosts rather than importing Unix fallbacks."""
    if _kernel is None:
        raise OSError("Windows native filesystem backend requires Windows")


def validate_component(name: str) -> None:
    """Reject Win32 aliases, ADS, reserved devices and ambiguous names."""
    if not name or name in (".", "..") or name[-1:] in (".", " "):
        raise ValueError("invalid Windows filename: " + repr(name))
    if any(ord(char) < 32 or char in '<>:"/\\|?*' for char in name):
        raise ValueError("invalid Windows filename: " + repr(name))
    if len(name.encode("utf-16-le")) > 510:
        raise ValueError("Windows filename exceeds 255 UTF-16 code units")
    device = name.split(".", 1)[0].rstrip(" ").upper()
    if device in ("CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$") or re.fullmatch(r"(?:COM|LPT)[1-9¹²³]", device):
        raise ValueError("reserved Windows device filename: " + repr(name))


def _extended(path: Path) -> str:
    """Use Unicode extended local paths without enabling device/UNC namespaces."""
    value = os.path.abspath(os.fspath(path))
    if value.startswith("\\\\") or not Path(value).drive:
        raise OSError("workflow state requires a local Windows drive, not UNC/device paths")
    return "\\\\?\\" + value


def _error(path=None):
    """Preserve native error codes and Python's useful filesystem subclasses."""
    error = ctypes.WinError(ctypes.get_last_error())
    if path is not None:
        error.filename = os.fspath(path)
    return error


def _open(path: Path, access: int, disposition: int = OPEN_EXISTING, directory: bool = False, root_handle=None):
    """Open the entry itself and deny replacement while its handle is alive."""
    if root_handle is not None:
        validate_component(path.name)
        _ordinary(root_handle, directory=True)
        storage = ctypes.create_unicode_buffer(path.name)
        length = len(path.name.encode("utf-16-le"))
        name = UnicodeString(length, length + 2, ctypes.cast(storage, wintypes.LPWSTR))
        attributes = ObjectAttributes(ctypes.sizeof(ObjectAttributes), root_handle,
                                      ctypes.pointer(name), 0x1040, None, None)
        handle = wintypes.HANDLE()
        # Synchronous, no-follow, handle-relative lookup. Directories allow write
        # sharing because the filesystem needs it for a child atomic rename.
        options = OPEN_REPARSE | 0x20 | 0x4000
        if directory and disposition != OPEN_EXISTING:
            options |= 1  # FILE_DIRECTORY_FILE for atomic directory creation.
        native_disposition = {OPEN_EXISTING: 1, OPEN_ALWAYS: 3, CREATE_NEW: 2}[disposition]
        # Native creates do not add Win32's implicit FILE_READ_ATTRIBUTES;
        # retain that right so every opened object can be type/identity checked.
        status = _native.NtCreateFile(ctypes.byref(handle), access | 0x100080,
            ctypes.byref(attributes), ctypes.byref(IoStatus()), None, 0,
            SHARE_READ_WRITE, native_disposition, options, None, 0)
        if status < 0:
            error = ctypes.WinError(_native.RtlNtStatusToDosError(status))
            error.filename = os.fspath(path)
            raise error
        return handle.value
    flags = OPEN_REPARSE | (BACKUP_SEMANTICS if directory else 0)
    handle = _kernel.CreateFileW(_extended(path), access, SHARE_READ_WRITE, None, disposition, flags, None)
    if handle == INVALID_HANDLE:
        raise _error(path)
    return handle


def _info(handle) -> HandleInfo:
    """Read metadata from the same object used for subsequent operations."""
    info = HandleInfo()
    if not _kernel.GetFileInformationByHandle(handle, ctypes.byref(info)):
        raise _error()
    return info


def _ordinary(handle, directory: bool = False) -> None:
    """Reject every reparse tag, including junctions and unknown redirectors."""
    info = _info(handle)
    if info.attributes & ATTRIBUTE_REPARSE:
        raise OSError("workflow paths must not traverse a reparse point or junction")
    if bool(info.attributes & ATTRIBUTE_DIRECTORY) != directory:
        raise OSError("workflow entry has an unsupported filesystem type")


def lock_file(descriptor: int) -> None:
    """Try one exclusive nonblocking lock; process exit releases it in kernel."""
    overlap = Overlapped()
    if not _kernel.LockFileEx(msvcrt.get_osfhandle(descriptor), 3, 0, 1, 0, ctypes.byref(overlap)):
        if ctypes.get_last_error() == 33:
            raise BlockingIOError(errno.EAGAIN, "workflow lock is held")
        raise _error()


def unlock_file(descriptor: int) -> None:
    """Unlock exactly the first byte range acquired by lock_file."""
    overlap = Overlapped()
    if not _kernel.UnlockFileEx(msvcrt.get_osfhandle(descriptor), 0, 1, 0, ctypes.byref(overlap)):
        raise _error()


def _set_info(handle, kind: int, value, size: int) -> None:
    """Retry only sharing/lock violations, never ACL or unrelated errors."""
    for attempt in range(6):
        if _kernel.SetFileInformationByHandle(handle, kind, value, size):
            return
        error = _error()
        if error.winerror not in (32, 33) or attempt == 5:
            raise error
        time.sleep(0.02 * (attempt + 1))


def _rename(handle, target: Path, create_only: bool, root_handle) -> None:
    """Rename an already held source, never re-open it by an untrusted path."""
    _ordinary(root_handle, directory=True)
    encoded = target.name.encode("utf-16-le")
    size = RenameInfo.name.offset + len(encoded)
    # Win32 consumes the path as a wide string even though length excludes NUL.
    buffer = ctypes.create_string_buffer(max(size + 2, ctypes.sizeof(RenameInfo)))
    header = RenameInfo.from_buffer(buffer)
    header.replace = not create_only
    header.root = root_handle
    header.length = len(encoded)
    ctypes.memmove(ctypes.addressof(buffer) + RenameInfo.name.offset, encoded, len(encoded))
    for attempt in range(6):
        status = _native.NtSetInformationFile(handle, ctypes.byref(IoStatus()), buffer, ctypes.sizeof(buffer), 10)
        if status >= 0:
            return
        error = ctypes.WinError(_native.RtlNtStatusToDosError(status))
        if error.winerror not in (32, 33) or attempt == 5:
            raise error
        time.sleep(0.02 * (attempt + 1))


class WindowsDirectory:
    """Pin ancestors and anchor child I/O without following path redirection."""

    def __init__(self, path: Path, create: bool = False):
        require_capabilities()
        self.path = Path(os.path.abspath(os.fspath(path)))
        self.handles = []
        anchor = Path(self.path.anchor)
        _extended(self.path)
        if _kernel.GetDriveTypeW(str(anchor)) != 3:
            raise OSError("workflow secure I/O requires a fixed local Windows drive")
        current = anchor
        try:
            for component in (None,) + self.path.relative_to(anchor).parts:
                if component is not None:
                    validate_component(component)
                    current = current / component
                parent = self.handles[-1] if self.handles else None
                disposition = OPEN_ALWAYS if create and component is not None else OPEN_EXISTING
                handle = _open(current, GENERIC_READ, disposition, directory=True, root_handle=parent)
                self.handles.append(handle)
                _ordinary(handle, directory=True)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """Release children before parents; safe after partial construction."""
        while self.handles:
            _kernel.CloseHandle(self.handles.pop())

    def _child(self, name: str) -> Path:
        """Reject operations after close and validate literal child names."""
        if not self.handles:
            raise OSError("secure directory is closed")
        validate_component(name)
        return self.path / name

    def open_regular(self, name: str, flags: int, mode: int = 0o600, delete_access: bool = False) -> int:
        """Return an owned CRT fd, applying truncation only after type checks."""
        path = self._child(name)
        access = GENERIC_READ if not flags & (os.O_WRONLY | os.O_RDWR) else GENERIC_WRITE
        if flags & os.O_RDWR:
            access |= GENERIC_READ
        if delete_access:
            access |= DELETE
        disposition = CREATE_NEW if flags & os.O_CREAT and flags & os.O_EXCL else OPEN_ALWAYS if flags & os.O_CREAT else OPEN_EXISTING
        handle = _open(path, access, disposition, root_handle=self.handles[-1])
        try:
            _ordinary(handle)
            if flags & os.O_TRUNC and _info(handle).links != 1:
                raise OSError("refusing to truncate a multiply linked workflow file")
            descriptor = msvcrt.open_osfhandle(handle, (flags & (os.O_RDONLY | os.O_WRONLY | os.O_RDWR | os.O_APPEND)) | os.O_BINARY)
            handle = None
            try:
                if flags & os.O_TRUNC:
                    os.ftruncate(descriptor, 0)
                return descriptor
            except BaseException:
                os.close(descriptor)
                raise
        finally:
            if handle is not None:
                _kernel.CloseHandle(handle)

    def stat(self, name: str):
        """Read no-follow metadata while ancestor identities are pinned."""
        handle = _open(self._child(name), 0x80, directory=True, root_handle=self.handles[-1])
        try:
            attributes = _info(handle).attributes
            descriptor = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            handle = None
            try:
                info = os.fstat(descriptor)
                fields = {field: getattr(info, field) for field in dir(info) if field.startswith("st_")}
                fields["st_file_attributes"] = attributes
                return SimpleNamespace(**fields)
            finally:
                os.close(descriptor)
        finally:
            if handle is not None:
                _kernel.CloseHandle(handle)

    def list_names(self):
        """Enumerate a held directory without following children."""
        if not self.handles:
            raise OSError("secure directory is closed")
        _ordinary(self.handles[-1], directory=True)
        names = []
        restart = True
        while True:
            buffer = ctypes.create_string_buffer(65536)
            result = IoStatus()
            status = _native.NtQueryDirectoryFile(self.handles[-1], None, None, None,
                ctypes.byref(result), buffer, len(buffer), 12, False, None, restart)
            if status & 0xffffffff == 0x80000006:  # STATUS_NO_MORE_FILES
                return names
            if status < 0:
                raise ctypes.WinError(_native.RtlNtStatusToDosError(status))
            restart = False
            offset = 0
            data = buffer.raw[:result.information]
            while True:
                if offset + 12 > len(data):
                    raise OSError("invalid native directory enumeration")
                next_offset, _, length = struct.unpack_from("<III", data, offset)
                if length % 2 or offset + 12 + length > len(data):
                    raise OSError("invalid native directory entry")
                name = data[offset + 12:offset + 12 + length].decode("utf-16-le")
                if name not in (".", ".."):
                    names.append(name)
                if not next_offset:
                    break
                if next_offset < 12 + length:
                    raise OSError("invalid native directory offset")
                offset += next_offset

    def readlink(self, name: str) -> str:
        """Read a symlink/junction payload without traversing its target."""
        handle = _open(self._child(name), 0, directory=True, root_handle=self.handles[-1])
        try:
            buffer = ctypes.create_string_buffer(16384)
            returned = wintypes.DWORD()
            if not _kernel.DeviceIoControl(handle, 0x900a8, None, 0, buffer,
                    len(buffer), ctypes.byref(returned), None):
                raise _error()
            data = buffer.raw[:returned.value]
            if len(data) < 16:
                raise OSError("invalid Windows reparse data")
            tag, _, _, offset, length = struct.unpack_from("<IHHHH", data)
            base = {0xa0000003: 16, 0xa000000c: 20}.get(tag)
            if base is None or length % 2 or base + offset + length > len(data):
                raise OSError("unsupported Windows reparse data")
            target = data[base + offset:base + offset + length].decode("utf-16-le")
            return "\\\\?\\" + target[4:] if target.startswith("\\??\\") else target
        finally:
            _kernel.CloseHandle(handle)

    def replace(self, source: str, target: str, create_only: bool = False) -> None:
        """Rename a no-follow source through its DELETE-capable handle."""
        destination = self._child(target)
        handle = _open(self._child(source), DELETE, root_handle=self.handles[-1])
        try:
            _ordinary(handle)
            _rename(handle, destination, create_only, self.handles[-1])
        finally:
            _kernel.CloseHandle(handle)

    def unlink(self, name: str) -> None:
        """Delete the opened entry itself, never its reparse target."""
        handle = _open(self._child(name), DELETE, directory=True, root_handle=self.handles[-1])
        try:
            value = wintypes.BOOLEAN(True)
            _set_info(handle, FILE_DISPOSITION_INFO_CLASS, ctypes.byref(value), ctypes.sizeof(value))
        finally:
            _kernel.CloseHandle(handle)

    def unlink_fd(self, descriptor: int) -> None:
        """Delete the held lock inode without releasing its exclusive lock first."""
        value = wintypes.BOOLEAN(True)
        _set_info(msvcrt.get_osfhandle(descriptor), FILE_DISPOSITION_INFO_CLASS, ctypes.byref(value), ctypes.sizeof(value))

    def write_atomic(self, name: str, content: bytes, create_only: bool = False) -> None:
        """Flush and rename one continuously held temporary file handle."""
        destination = self._child(name)
        temporary = self._child("." + name + "." + secrets.token_hex(12) + ".tmp")
        handle = _open(temporary, GENERIC_WRITE | DELETE, CREATE_NEW, root_handle=self.handles[-1])
        descriptor = -1
        published = False
        try:
            _ordinary(handle)
            descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
            handle = None
            view = memoryview(content)
            while view:
                written = os.write(descriptor, view)
                if written <= 0:
                    raise OSError("short write while publishing workflow state")
                view = view[written:]
            os.fsync(descriptor)
            _rename(msvcrt.get_osfhandle(descriptor), destination, create_only, self.handles[-1])
            published = True
        finally:
            live_handle = msvcrt.get_osfhandle(descriptor) if descriptor >= 0 else handle
            try:
                if not published and live_handle is not None:
                    value = wintypes.BOOLEAN(True)
                    _set_info(live_handle, FILE_DISPOSITION_INFO_CLASS, ctypes.byref(value), ctypes.sizeof(value))
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
                elif handle is not None:
                    _kernel.CloseHandle(handle)
