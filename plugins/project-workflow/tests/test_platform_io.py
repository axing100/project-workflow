"""Portable native-process contracts for the secure filesystem backend."""

import os
import ctypes
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import platform_io
import windows_io


class PlatformIOTests(unittest.TestCase):
    """Run the same real lock/atomicity contracts on each host OS."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="workflow 中文 ")
        self.root = Path(self.temporary.name).resolve()

    def tearDown(self):
        self.temporary.cleanup()

    def test_atomic_unicode_create_replace_and_delete(self):
        with platform_io.SecureDirectory(self.root / "状态 目录", root=self.root, create=True) as directory:
            directory.write_atomic("计划.json", "中文".encode(), create_only=True)
            with self.assertRaises(FileExistsError):
                directory.write_atomic("计划.json", b"must not replace", create_only=True)
            fd = directory.open_regular("计划.json", os.O_RDONLY)
            with os.fdopen(fd, "rb") as stream:
                self.assertEqual(stream.read(), "中文".encode())
            directory.write_atomic("计划.json", b"updated")
            self.assertEqual(directory.list_names(), ["计划.json"])
            directory.unlink("计划.json")
            self.assertEqual(directory.list_names(), [])

    def test_failure_before_replace_preserves_old_data(self):
        with platform_io.SecureDirectory(self.root, root=self.root) as directory:
            directory.write_atomic("state", b"old")
            with mock.patch("os.fsync", side_effect=OSError("disk failure")):
                with self.assertRaises(OSError):
                    directory.write_atomic("state", b"new")
            self.assertEqual((self.root / "state").read_bytes(), b"old")
            self.assertEqual(directory.list_names(), ["state"])

    def test_no_traversal_leaf(self):
        with platform_io.SecureDirectory(self.root, root=self.root) as directory:
            for name in ("../outside", "a/b", "a\\b", ".", "..", "", "x\0y"):
                with self.subTest(name=name), self.assertRaises(ValueError):
                    directory.open_regular(name, os.O_CREAT | os.O_WRONLY)

    def test_reserved_windows_names(self):
        for name in ("NUL", "con.txt", "COM1.json", "LPT²", "name.", "name ", "a:stream", "a?b", "CONIN$"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                windows_io.validate_component(name)
        windows_io.validate_component("中文 file.json")
        windows_io.validate_component("x" * 255)
        with self.assertRaises(ValueError):
            windows_io.validate_component("x" * 256)
        with self.assertRaises(ValueError):
            windows_io.validate_component("😀" * 128)

    def test_outside_root_rejected(self):
        with self.assertRaises(ValueError):
            platform_io.SecureDirectory(self.root.parent, root=self.root)

    def test_directory_not_regular(self):
        (self.root / "directory").mkdir()
        with platform_io.SecureDirectory(self.root, root=self.root) as directory:
            with self.assertRaises(OSError):
                directory.open_regular("directory", os.O_RDONLY)

    def test_lock_timeout_and_process_exit_release(self):
        script = """import os,sys,time
from pathlib import Path
sys.path.insert(0,sys.argv[1])
from platform_io import SecureDirectory,lock_file
root=Path(sys.argv[2])
with SecureDirectory(root,root=root) as directory:
    fd=directory.open_regular('stable.lock',os.O_RDWR|os.O_CREAT)
    lock_file(fd)
    print('locked',flush=True)
    time.sleep(30)
"""
        process = subprocess.Popen([sys.executable, "-u", "-c", script, str(SCRIPTS), str(self.root)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            self.assertEqual(process.stdout.readline().strip(), "locked")
            with platform_io.SecureDirectory(self.root, root=self.root) as directory:
                fd = directory.open_regular("stable.lock", os.O_RDWR)
                try:
                    with self.assertRaises(TimeoutError):
                        platform_io.lock_file(fd, 0.1)
                    process.kill()
                    process.wait(timeout=10)
                    with platform_io.file_lock(fd, 2):
                        self.assertTrue((self.root / "stable.lock").exists())
                finally:
                    os.close(fd)
        finally:
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=10)

    def test_exception_releases_lock(self):
        with platform_io.SecureDirectory(self.root, root=self.root) as directory:
            first = directory.open_regular("lock", os.O_RDWR | os.O_CREAT)
            second = directory.open_regular("lock", os.O_RDWR)
            try:
                with self.assertRaisesRegex(RuntimeError, "intentional"):
                    with platform_io.file_lock(first):
                        raise RuntimeError("intentional")
                with platform_io.file_lock(second, 0):
                    pass
            finally:
                os.close(first)
                os.close(second)

    @unittest.skipIf(os.name == "nt", "POSIX concurrent-create ENOENT contract")
    def test_create_race_retry_is_bounded(self):
        """Retry only transient anchored create failures, never ordinary reads."""
        with platform_io.SecureDirectory(self.root, root=self.root) as directory:
            real_open = os.open
            calls = []

            def contested_open(*args, **kwargs):
                """Inject one transient kernel create failure."""
                calls.append(args)
                if len(calls) == 1:
                    raise FileNotFoundError("concurrent create")
                return real_open(*args, **kwargs)

            with mock.patch("os.open", side_effect=contested_open):
                descriptor = directory.open_regular("race.lock", os.O_RDWR | os.O_CREAT)
                os.close(descriptor)
            self.assertEqual(2, len(calls))
            with mock.patch("os.open", side_effect=FileNotFoundError("persistent")) as opening:
                with self.assertRaises(FileNotFoundError):
                    directory.open_regular("race.lock", os.O_RDWR | os.O_CREAT)
                self.assertEqual(3, opening.call_count)
            with mock.patch("os.open", side_effect=FileNotFoundError("missing")) as opening:
                with self.assertRaises(FileNotFoundError):
                    directory.open_regular("missing", os.O_RDONLY)
                self.assertEqual(1, opening.call_count)

    def test_timeout_values_rejected(self):
        for timeout in (-1, float("inf"), float("nan"), True):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                platform_io.lock_file(-1, timeout)

    def test_delete_legacy_lock_while_held(self):
        with platform_io.SecureDirectory(self.root, root=self.root) as directory:
            descriptor = directory.open_regular("legacy.lock", os.O_RDWR | os.O_CREAT, delete_access=True)
            try:
                with platform_io.file_lock(descriptor):
                    directory.unlink_fd(descriptor, "legacy.lock")
            finally:
                os.close(descriptor)
            self.assertFalse((self.root / "legacy.lock").exists())

    @unittest.skipIf(os.name == "nt", "POSIX symlink fixture; Windows junction covered separately")
    def test_posix_link_rejected(self):
        (self.root / "target").mkdir()
        (self.root / "link").symlink_to(self.root / "target", target_is_directory=True)
        with self.assertRaises(OSError):
            platform_io.SecureDirectory(self.root / "link", root=self.root)
        (self.root / "file").write_bytes(b"safe")
        (self.root / "file-link").symlink_to(self.root / "file")
        with platform_io.SecureDirectory(self.root, root=self.root) as directory:
            with self.assertRaises(OSError):
                directory.open_regular("file-link", os.O_WRONLY | os.O_TRUNC)
        self.assertEqual((self.root / "file").read_bytes(), b"safe")

    @unittest.skipUnless(os.name == "nt", "native Windows directory-sharing guarantee")
    def test_windows_ancestor_cannot_be_replaced(self):
        parent = self.root / "parent"
        parent.mkdir()
        with platform_io.SecureDirectory(parent / "child", root=self.root, create=True) as directory:
            with self.assertRaises(PermissionError):
                parent.rename(self.root / "moved")
            directory.write_atomic("state", b"inside")
        parent.rename(self.root / "moved")
        self.assertEqual((self.root / "moved/child/state").read_bytes(), b"inside")

    @unittest.skipUnless(os.name == "nt", "native Windows in-place reparse protection")
    def test_windows_in_place_junction_cannot_escape(self):
        """Attempt real FSCTL redirection between validation and native open."""
        parent = self.root / "parent"
        parent.mkdir()
        external = self.root / "external"
        external.mkdir()
        target = ("\\??\\" + str(external)).encode("utf-16-le")
        payload = struct.pack("<HHHH", 0, len(target), len(target) + 2, 0) + target + b"\0\0\0\0"
        reparse = struct.pack("<IHH", 0xa0000003, len(payload), 0) + payload
        attempted = False
        redirected = False
        original = windows_io._native.NtCreateFile

        def attack(*args):
            """Mutate after the backend's root check, before the kernel lookup."""
            nonlocal attempted, redirected
            if not attempted:
                attempted = True
                handle = windows_io._open(parent, windows_io.GENERIC_WRITE, directory=True)
                try:
                    buffer = ctypes.create_string_buffer(reparse)
                    returned = windows_io.wintypes.DWORD()
                    redirected = bool(windows_io._kernel.DeviceIoControl(handle, 0x900a4,
                        buffer, len(reparse), None, 0, ctypes.byref(returned), None))
                    if not redirected:
                        self.assertIn(ctypes.get_last_error(), (5, 32, 145, 4390))
                finally:
                    windows_io._kernel.CloseHandle(handle)
            return original(*args)

        try:
            with platform_io.SecureDirectory(parent, root=self.root) as directory:
                with mock.patch.object(windows_io._native, "NtCreateFile", side_effect=attack):
                    try:
                        directory.write_atomic("state", b"inside")
                    except OSError:
                        pass
            self.assertTrue(attempted)
            self.assertEqual(list(external.iterdir()), [])
        finally:
            if redirected:
                os.rmdir(parent)

    @unittest.skipUnless(os.name == "nt", "native Windows junction, no symlink privilege required")
    def test_windows_junction_rejected(self):
        target = self.root / "target"
        target.mkdir()
        junction = self.root / "junction"
        result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            with self.assertRaises(OSError):
                platform_io.SecureDirectory(junction, root=self.root)
        finally:
            os.rmdir(junction)
        self.assertEqual(list(target.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "native Windows file-sharing semantics")
    def test_windows_busy_target_preserved(self):
        with platform_io.SecureDirectory(self.root, root=self.root) as directory:
            directory.write_atomic("state", b"old")
            fd = directory.open_regular("state", os.O_RDONLY)
            try:
                with self.assertRaises(OSError):
                    directory.write_atomic("state", b"new")
            finally:
                os.close(fd)
            self.assertEqual((self.root / "state").read_bytes(), b"old")
            self.assertEqual(directory.list_names(), ["state"])


if __name__ == "__main__":
    unittest.main()
