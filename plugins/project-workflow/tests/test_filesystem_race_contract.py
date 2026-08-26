"""Independent black-box race and recovery contracts for NONE-mode evidence."""

from __future__ import annotations

import errno
import hashlib
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


SNAPSHOT = Path(__file__).resolve().parents[1] / "scripts" / "filesystem_snapshot.py"


class FilesystemRaceContractTest(unittest.TestCase):
    """Probe observable safety without importing snapshot implementation internals."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        root = Path(self.temporary_directory.name)
        self.repo = root / "repo"
        self.repo.mkdir()
        self.external = root / "external"
        self.external.mkdir()
        self.baseline = self.repo / ".codex/project-workflow/race/baseline.json"

    def run_snapshot(
        self,
        *arguments: str,
        expected: int | tuple[int, ...] = 0,
        timeout: float = 10,
    ) -> subprocess.CompletedProcess[str]:
        """Run the public CLI with a bounded wait and stable error assertions."""
        result = subprocess.run(
            [sys.executable, str(SNAPSHOT), *arguments],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        allowed = (expected,) if isinstance(expected, int) else expected
        self.assertIn(result.returncode, allowed, result.stderr or result.stdout)
        self.assertNotIn("Traceback", result.stderr)
        return result

    def create(self, output: Path | None = None, *, expected: int | tuple[int, ...] = 0) -> subprocess.CompletedProcess[str]:
        """Create detailed evidence at an internal path."""
        return self.run_snapshot(
            "create",
            "--repo",
            str(self.repo),
            "--output",
            str(output or self.baseline),
            "--json-details",
            expected=expected,
        )

    def test_regular_file_symlink_swap_never_hashes_external_content(self) -> None:
        """A racing file may disappear or become a link, but must never expose its target."""
        data = self.repo / "data"
        data.mkdir()
        target = data / "payload.txt"
        target.write_text("public", encoding="utf-8")
        secret = self.external / "secret.txt"
        secret.write_text("external-secret-never-hash", encoding="utf-8")
        secret_digest = hashlib.sha256(secret.read_bytes()).hexdigest()
        stop = threading.Event()
        exchanged_once = threading.Event()
        exchange_count = 0

        def attack() -> None:
            nonlocal exchange_count
            hold = data / "payload.hold"
            while not stop.is_set():
                try:
                    os.replace(target, hold)
                    os.symlink(secret, target)
                    exchange_count += 1
                    exchanged_once.set()
                    target.unlink(missing_ok=True)
                    os.replace(hold, target)
                except FileNotFoundError:
                    continue

        thread = threading.Thread(target=attack, daemon=True)
        thread.start()
        try:
            self.assertTrue(exchanged_once.wait(timeout=2), "attacker never exchanged the file")
            successful = 0
            return_codes: list[int] = []
            for index in range(20):
                output = self.repo / f".codex/project-workflow/race/file-{index}.json"
                result = self.create(output, expected=(0, 2))
                return_codes.append(result.returncode)
                if result.returncode != 0:
                    continue
                successful += 1
                evidence = json.loads(output.read_text(encoding="utf-8"))
                for record in evidence["files"]:
                    self.assertNotEqual(secret_digest, record.get("sha256"))
            self.assertEqual(20, len(return_codes))
            self.assertGreater(exchange_count, 0)
            if successful == 0:
                self.assertEqual({2}, set(return_codes), "all rejected probes must fail closed")
        finally:
            stop.set()
            thread.join(timeout=2)

    def test_parent_directory_swap_never_traverses_external_tree(self) -> None:
        """Hold directory identity while an attacker substitutes an external symlink."""
        data = self.repo / "data"
        data.mkdir()
        (data / "public.txt").write_text("public", encoding="utf-8")
        secret = self.external / "secret.txt"
        secret.write_text("parent-race-secret", encoding="utf-8")
        secret_digest = hashlib.sha256(secret.read_bytes()).hexdigest()
        hold = self.repo / "data.hold"
        stop = threading.Event()

        def attack() -> None:
            while not stop.is_set():
                try:
                    os.replace(data, hold)
                    os.symlink(self.external, data)
                    data.unlink(missing_ok=True)
                    os.replace(hold, data)
                except FileNotFoundError:
                    continue

        thread = threading.Thread(target=attack, daemon=True)
        thread.start()
        try:
            successful = 0
            for index in range(20):
                output = self.repo / f".codex/project-workflow/race/parent-{index}.json"
                result = self.create(output, expected=(0, 2))
                if result.returncode != 0:
                    continue
                successful += 1
                evidence = json.loads(output.read_text(encoding="utf-8"))
                paths = {record["path"] for record in evidence["files"]}
                self.assertNotIn("data/secret.txt", paths)
                for record in evidence["files"]:
                    self.assertNotEqual(secret_digest, record.get("sha256"))
            self.assertGreater(successful, 0, "parent race probe never reached a snapshot")
        finally:
            stop.set()
            thread.join(timeout=2)

    def test_fifo_fails_closed_without_overwriting_old_evidence(self) -> None:
        """Never block on or serialize a FIFO."""
        self.baseline.parent.mkdir(parents=True)
        old = b'{"trusted":"old-evidence"}\n'
        self.baseline.write_bytes(old)

        fifo = self.repo / "input.fifo"
        os.mkfifo(fifo)
        self.create(expected=2)
        self.assertEqual(old, self.baseline.read_bytes())
        fifo.unlink()

    def test_socket_fails_closed_without_overwriting_old_evidence(self) -> None:
        """Never serialize a process-bound Unix socket."""
        self.baseline.parent.mkdir(parents=True)
        old = b'{"trusted":"old-evidence"}\n'
        self.baseline.write_bytes(old)
        socket_path = self.repo / "service.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        try:
            server.bind(str(socket_path))
        except OSError as error:
            self.skipTest(f"Unix socket unavailable: {error}")
        self.create(expected=2)
        self.assertEqual(old, self.baseline.read_bytes())

    def test_device_node_fails_closed_when_platform_allows_fixture(self) -> None:
        """Reject device nodes; skip only when the host forbids constructing the fixture."""
        device = self.repo / "device-node"
        try:
            os.mknod(device, stat.S_IFCHR | 0o600, os.makedev(1, 3))
        except (AttributeError, PermissionError) as error:
            self.skipTest(f"device fixture unavailable: {error}")
        except OSError as error:
            if error.errno in {errno.EPERM, errno.EACCES, errno.ENOTSUP}:
                self.skipTest(f"device fixture unavailable: {error}")
            raise
        self.create(expected=2)

    def test_directory_mode_is_evidence_and_legacy_baseline_remains_readable(self) -> None:
        """Expose new directory modes without inventing them for old evidence."""
        source = self.repo / "src"
        source.mkdir(mode=0o755)
        (source / "main.txt").write_text("content", encoding="utf-8")
        self.create()
        baseline = json.loads(self.baseline.read_text(encoding="utf-8"))
        directory = next(record for record in baseline["files"] if record["path"] == "src")
        self.assertEqual("directory", directory["type"])

        source.chmod(0o700)
        changed = self.run_snapshot(
            "compare", "--repo", str(self.repo), "--baseline", str(self.baseline), "--report-only"
        )
        self.assertIn("src", json.loads(changed.stdout)["modified"])

        legacy = dict(baseline)
        legacy.pop("directory_records", None)
        legacy["files"] = [
            {key: value for key, value in record.items() if key != "mode"}
            for record in baseline["files"]
            if record.get("type") != "directory"
        ]
        self.baseline.write_text(json.dumps(legacy), encoding="utf-8")
        source.chmod(0o755)
        compatible = self.run_snapshot(
            "compare", "--repo", str(self.repo), "--baseline", str(self.baseline), "--report-only"
        )
        result = json.loads(compatible.stdout)
        self.assertEqual([], result["added"])
        self.assertEqual([], result["modified"])

    def test_symlinked_output_parent_is_rejected_without_external_write(self) -> None:
        """Resolve output through held in-repository directories only."""
        state_root = self.repo / ".codex/project-workflow"
        state_root.mkdir(parents=True)
        redirected = state_root / "redirected"
        redirected.symlink_to(self.external, target_is_directory=True)
        result = self.create(redirected / "baseline.json", expected=2)
        self.assertTrue(result.stderr)
        self.assertFalse((self.external / "baseline.json").exists())


if __name__ == "__main__":
    unittest.main()
