"""Tests for deterministic VCS NONE file-system evidence."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "filesystem_snapshot.py"
sys.path.insert(0, str(SCRIPT.parent))
SPEC = importlib.util.spec_from_file_location("filesystem_snapshot", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
SNAPSHOT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SNAPSHOT)


class FilesystemSnapshotTest(unittest.TestCase):
    """Verify content changes, scope enforcement, exclusions, and atomic writes."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.repo = Path(self.temporary_directory.name) / "workspace"
        self.repo.mkdir()
        self.baseline = self.repo / ".codex/project-workflow/test/filesystem-baseline.json"

    def run_command(self, *arguments: str, expected: int = 0) -> dict[str, object]:
        """Run the snapshot CLI and decode its JSON result."""
        result = subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(expected, result.returncode, result.stderr or result.stdout)
        return json.loads(result.stdout) if result.stdout else {}

    def create_baseline(self, *extra: str) -> dict[str, object]:
        """Create the standard internal baseline for this workspace."""
        return self.run_command(
            "create",
            "--repo",
            str(self.repo),
            "--output",
            str(self.baseline),
            "--json-details",
            *extra,
        )

    def test_create_and_compare_added_modified_deleted_and_scope(self) -> None:
        (self.repo / "src").mkdir()
        (self.repo / "src/modify.txt").write_text("before", encoding="utf-8")
        (self.repo / "delete.txt").write_text("delete", encoding="utf-8")
        baseline = self.create_baseline()
        self.assertEqual(
            ["delete.txt", "src", "src/modify.txt"],
            [record["path"] for record in baseline["files"]],
        )

        (self.repo / "src/modify.txt").write_text("after", encoding="utf-8")
        (self.repo / "delete.txt").unlink()
        (self.repo / "outside.txt").write_text("new", encoding="utf-8")
        result = self.run_command(
            "compare",
            "--repo",
            str(self.repo),
            "--baseline",
            str(self.baseline),
            "--write-scope",
            "src",
            "--report-only",
        )
        self.assertEqual(["outside.txt"], result["added"])
        self.assertEqual(["src/modify.txt"], result["modified"])
        self.assertEqual(["delete.txt"], result["deleted"])
        self.assertEqual(["delete.txt", "outside.txt"], result["out_of_scope"])

    @unittest.skipIf(os.name == "nt", "POSIX mode bits; Windows uses ACLs and readonly attributes")
    def test_snapshot_records_directory_mode_and_detects_chmod(self) -> None:
        """A new baseline must make directory permission changes visible."""
        source = self.repo / "src"
        source.mkdir(mode=0o755)
        (source / "main.txt").write_text("content", encoding="utf-8")
        baseline = self.create_baseline()
        directory = next(item for item in baseline["files"] if item["path"] == "src")
        self.assertEqual("directory", directory["type"])
        self.assertEqual(0o755, directory["mode"])

        source.chmod(0o700)
        result = self.run_command(
            "compare", "--repo", str(self.repo), "--baseline", str(self.baseline),
            "--report-only",
        )
        self.assertEqual(["src"], result["modified"])

    def test_old_baseline_without_directory_records_ignores_directories(self) -> None:
        """Directory evidence is enabled only after writing a new-format baseline."""
        source = self.repo / "src"
        source.mkdir(mode=0o755)
        (source / "main.txt").write_text("content", encoding="utf-8")
        old = SNAPSHOT.build_snapshot(self.repo)
        old.pop("directory_records")
        old["files"] = [item for item in old["files"] if item["type"] != "directory"]
        self.baseline.parent.mkdir(parents=True)
        self.baseline.write_text(json.dumps(old), encoding="utf-8")

        source.chmod(0o700)
        result = self.run_command(
            "compare", "--repo", str(self.repo), "--baseline", str(self.baseline),
            "--report-only",
        )
        self.assertEqual([], result["added"])
        self.assertEqual([], result["modified"])

    def test_compare_fails_on_out_of_scope_unless_report_only(self) -> None:
        (self.repo / "inside.txt").write_text("before", encoding="utf-8")
        self.create_baseline()
        (self.repo / "outside.txt").write_text("outside", encoding="utf-8")

        failed = self.run_command(
            "compare", "--repo", str(self.repo), "--baseline", str(self.baseline),
            "--write-scope", "inside.txt", expected=3,
        )
        self.assertEqual(["outside.txt"], failed["out_of_scope"])
        reported = self.run_command(
            "compare", "--repo", str(self.repo), "--baseline", str(self.baseline),
            "--write-scope", "inside.txt", "--report-only",
        )
        self.assertEqual(failed, reported)

    def test_snapshot_is_deterministic_and_excludes_internal_state_and_caches(self) -> None:
        (self.repo / "b.txt").write_text("b", encoding="utf-8")
        (self.repo / ".env").write_text("placeholder", encoding="utf-8")
        (self.repo / "__pycache__").mkdir()
        (self.repo / "__pycache__/ignored.pyc").write_bytes(b"cache")
        first = SNAPSHOT.build_snapshot(self.repo)
        second = SNAPSHOT.build_snapshot(self.repo)
        self.assertEqual(first, second)
        self.assertEqual([".env", "b.txt"], [record["path"] for record in first["files"]])

    def test_ide_directories_are_included_and_repeatable_excludes_are_persisted(self) -> None:
        (self.repo / ".idea").mkdir()
        (self.repo / ".idea/workspace.xml").write_text("idea", encoding="utf-8")
        (self.repo / ".vscode").mkdir()
        (self.repo / ".vscode/settings.json").write_text("vscode", encoding="utf-8")
        (self.repo / "generated").mkdir()
        (self.repo / "generated/result.txt").write_text("result", encoding="utf-8")
        baseline = self.create_baseline("--exclude", "generated", "--exclude", ".vscode")
        self.assertEqual([".vscode", "generated"], baseline["excludes"])
        self.assertEqual(
            [".idea", ".idea/workspace.xml"],
            [item["path"] for item in baseline["files"]],
        )

        (self.repo / "generated/result.txt").write_text("changed", encoding="utf-8")
        result = self.run_command(
            "compare", "--repo", str(self.repo), "--baseline", str(self.baseline),
            "--report-only",
        )
        self.assertEqual([], result["modified"])

    def test_old_baseline_keeps_legacy_ide_exclusions_and_missing_modes_are_compatible(self) -> None:
        (self.repo / ".idea").mkdir()
        (self.repo / ".idea/workspace.xml").write_text("idea", encoding="utf-8")
        script = self.repo / "run.sh"
        script.write_text("echo ok\n", encoding="utf-8")
        old = SNAPSHOT.build_snapshot(self.repo)
        old.pop("excludes")
        old.pop("directory_records")
        old["files"] = [
            record for record in old["files"]
            if record["type"] != "directory" and not record["path"].startswith(".idea/")
        ]
        for record in old["files"]:
            record.pop("mode", None)
        self.baseline.parent.mkdir(parents=True)
        self.baseline.write_text(json.dumps(old), encoding="utf-8")

        result = self.run_command(
            "compare", "--repo", str(self.repo), "--baseline", str(self.baseline),
            "--report-only",
        )
        self.assertEqual([], result["added"])
        self.assertEqual([], result["modified"])

    @unittest.skipIf(os.name == "nt", "POSIX executable mode bits do not exist on Windows")
    def test_mode_change_is_detected(self) -> None:
        script = self.repo / "run.sh"
        script.write_text("echo ok\n", encoding="utf-8")
        script.chmod(0o644)
        baseline = self.create_baseline()
        self.assertEqual(0o644, baseline["files"][0]["mode"])
        script.chmod(0o755)
        result = self.run_command(
            "compare", "--repo", str(self.repo), "--baseline", str(self.baseline),
            "--report-only",
        )
        self.assertEqual(["run.sh"], result["modified"])

    def test_create_prints_summary_unless_json_details_requested(self) -> None:
        (self.repo / "a.txt").write_text("a", encoding="utf-8")
        summary = self.run_command(
            "create", "--repo", str(self.repo),
            "--output", ".codex/project-workflow/baseline.json",
        )
        self.assertEqual(1, summary["file_count"])
        self.assertNotIn("files", summary)
        persisted = json.loads(
            (self.repo / ".codex/project-workflow/baseline.json").read_text(encoding="utf-8")
        )
        self.assertEqual(["a.txt"], [record["path"] for record in persisted["files"]])

    def test_create_refuses_to_overwrite_existing_baseline(self) -> None:
        """A repeated public create must not silently reset historical evidence."""
        (self.repo / "a.txt").write_text("before", encoding="utf-8")
        self.create_baseline()
        original = self.baseline.read_bytes()
        (self.repo / "a.txt").write_text("after", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "create",
                "--repo",
                str(self.repo),
                "--output",
                str(self.baseline),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("already exists", result.stderr)
        self.assertEqual(original, self.baseline.read_bytes())

    def test_create_recovery_requires_matching_old_digest(self) -> None:
        """Explicit baseline recovery is a digest-CAS replacement, not a force flag."""
        (self.repo / "a.txt").write_text("before", encoding="utf-8")
        self.create_baseline()
        original = self.baseline.read_bytes()
        old_digest = SNAPSHOT.canonical_json_sha256(json.loads(original))
        (self.repo / "a.txt").write_text("after", encoding="utf-8")

        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "create",
                "--repo",
                str(self.repo),
                "--output",
                str(self.baseline),
                "--replace-if-sha256",
                "0" * 64,
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("digest conflict", result.stderr)
        self.assertEqual(original, self.baseline.read_bytes())

        self.run_command(
            "create",
            "--repo",
            str(self.repo),
            "--output",
            str(self.baseline),
            "--replace-if-sha256",
            old_digest,
        )
        self.assertNotEqual(original, self.baseline.read_bytes())

    def test_competing_recovery_cas_has_exactly_one_winner(self) -> None:
        """The target-relative lock closes the read/replace digest-CAS race."""
        (self.repo / "a.txt").write_text("before", encoding="utf-8")
        baseline = self.create_baseline()
        old_digest = SNAPSHOT.canonical_json_sha256(baseline)
        (self.repo / "a.txt").write_text("after", encoding="utf-8")
        command = [
            sys.executable,
            str(SCRIPT),
            "create",
            "--repo",
            str(self.repo),
            "--output",
            str(self.baseline),
            "--replace-if-sha256",
            old_digest,
        ]
        processes = [
            subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            for _ in range(2)
        ]
        results = [process.communicate() + (process.returncode,) for process in processes]
        self.assertEqual([0, 2], sorted(result[2] for result in results))
        self.assertTrue(any("digest conflict" in result[1] for result in results))

    def test_relative_baseline_and_output_paths_resolve_from_repo(self) -> None:
        (self.repo / "a.txt").write_text("a", encoding="utf-8")
        self.run_command(
            "create", "--repo", str(self.repo),
            "--output", ".codex/project-workflow/relative.json",
        )
        result = self.run_command(
            "compare", "--repo", str(self.repo),
            "--baseline", ".codex/project-workflow/relative.json",
            "--output", ".codex/project-workflow/diff.json",
            "--report-only",
        )
        self.assertEqual([], result["modified"])
        self.assertTrue((self.repo / ".codex/project-workflow/diff.json").is_file())

    def test_escape_symlink_is_hashed_without_reading_external_content(self) -> None:
        external = Path(self.temporary_directory.name) / "secret.txt"
        external.write_text("first secret", encoding="utf-8")
        os.symlink(str(external), str(self.repo / "external-link"))
        first = SNAPSHOT.build_snapshot(self.repo)
        external.write_text("changed secret", encoding="utf-8")
        second = SNAPSHOT.build_snapshot(self.repo)
        self.assertEqual(first, second)
        self.assertEqual("symlink", first["files"][0]["type"])
        self.assertNotIn("secret", json.dumps(first))

    def test_regular_file_is_opened_without_following_a_swapped_symlink(self) -> None:
        """A file replaced after discovery must not expose its external target."""
        target = self.repo / "target.txt"
        target.write_text("safe", encoding="utf-8")
        external = Path(self.temporary_directory.name) / "secret.txt"
        external.write_text("secret", encoding="utf-8")
        if os.name == "nt":
            import windows_io
            original_open = windows_io._open
        else:
            original_open = SNAPSHOT.os.open
        swapped = False

        def swap_before_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal swapped
            reading_content = os.name != "nt" or flags == windows_io.GENERIC_READ
            if not swapped and reading_content and os.fspath(path) in {str(target), target.name}:
                swapped = True
                target.unlink()
                os.symlink(str(external), str(target))
            return original_open(path, flags, *args, **kwargs)

        hook = "windows_io._open" if os.name == "nt" else "os.open"
        with mock.patch(hook, side_effect=swap_before_open):
            with self.assertRaisesRegex(SNAPSHOT.SnapshotError, "cannot safely read|cannot inspect workspace"):
                SNAPSHOT.build_snapshot(self.repo)
        self.assertTrue(swapped)

    def test_regular_file_identity_change_while_reading_fails_closed(self) -> None:
        """A changed descriptor identity must invalidate the snapshot evidence."""
        target = self.repo / "target.txt"
        target.write_text("safe", encoding="utf-8")
        real_fstat = SNAPSHOT.os.fstat
        calls = 0

        def changed_fstat(descriptor: int) -> os.stat_result:
            nonlocal calls
            calls += 1
            result = real_fstat(descriptor)
            # Windows metadata discovery itself is now descriptor-based; inject
            # on the final content fstat, not that earlier no-follow stat call.
            if calls == (3 if os.name == "nt" else 2):
                values = list(result)
                values[stat.ST_MTIME] += 1
                return os.stat_result(values)
            return result

        with mock.patch.object(SNAPSHOT.os, "fstat", side_effect=changed_fstat):
            with self.assertRaisesRegex(SNAPSHOT.SnapshotError, "changed while reading"):
                SNAPSHOT.hash_file(target)

    def test_parent_symlink_swap_cannot_redirect_file_read(self) -> None:
        """A held walk descriptor must keep file reads inside the discovered directory."""
        source = self.repo / "src"
        source.mkdir()
        (source / "target.txt").write_text("safe", encoding="utf-8")
        held_source = self.repo / "held-src"
        external = Path(self.temporary_directory.name) / "external-src"
        external.mkdir()
        (external / "target.txt").write_text("secret", encoding="utf-8")
        original_hash = SNAPSHOT._hash_regular_file
        swapped = False

        def swap_parent(path: Path, dir_fd: int | None = None) -> tuple[int, str, int]:
            nonlocal swapped
            if not swapped and os.fspath(path) == "target.txt":
                swapped = True
                source.rename(held_source)
                os.symlink(str(external), str(source))
            return original_hash(path, dir_fd)

        with mock.patch.object(SNAPSHOT, "_hash_regular_file", side_effect=swap_parent):
            snapshot = SNAPSHOT.build_snapshot(self.repo)
        record = next(item for item in snapshot["files"] if item["path"] == "src/target.txt")
        self.assertEqual(hashlib.sha256(b"safe").hexdigest(), record["sha256"])

    @unittest.skipIf(os.name == "nt", "POSIX FIFO/socket fixtures; Windows rejects device paths in native backend tests")
    def test_fifo_and_socket_are_rejected(self) -> None:
        """Unsupported workspace entry types must never be silently omitted."""
        fifo = self.repo / "events.fifo"
        os.mkfifo(str(fifo))
        with self.assertRaisesRegex(SNAPSHOT.SnapshotError, "unsupported.*events.fifo"):
            SNAPSHOT.build_snapshot(self.repo)
        fifo.unlink()

        socket_path = self.repo / "events.sock"
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.addCleanup(server.close)
        try:
            server.bind(str(socket_path))
        except PermissionError:
            self.skipTest("sandbox does not permit creating Unix-domain sockets")
        with self.assertRaisesRegex(SNAPSHOT.SnapshotError, "unsupported.*events.sock"):
            SNAPSHOT.build_snapshot(self.repo)

    def test_failed_atomic_replace_preserves_old_baseline(self) -> None:
        self.baseline.parent.mkdir(parents=True)
        self.baseline.write_text("old baseline", encoding="utf-8")
        target = "windows_io._rename" if os.name == "nt" else "os.replace"
        with mock.patch(target, side_effect=OSError("replace failed")):
            with self.assertRaises(OSError):
                SNAPSHOT.atomic_write_json(self.baseline, {"schema": "test"})
        self.assertEqual("old baseline", self.baseline.read_text(encoding="utf-8"))
        self.assertEqual([], list(self.baseline.parent.glob(f".{self.baseline.name}.*")))

    def test_atomic_write_fsyncs_file_and_parent_directory(self) -> None:
        """Durable replacement must sync both content and its directory entry."""
        self.baseline.parent.mkdir(parents=True)
        with mock.patch.object(SNAPSHOT.os, "fsync", wraps=os.fsync) as sync:
            SNAPSHOT.atomic_write_json(self.baseline, {"schema": "test"})
        self.assertGreaterEqual(sync.call_count, 1 if os.name == "nt" else 2)

    def test_atomic_write_uses_held_directory_when_parent_is_swapped(self) -> None:
        """A parent symlink swap must not redirect the atomic replacement."""
        if os.name == "nt":
            import windows_io
            real_rename = windows_io._rename

            def guarded_rename(*args, **kwargs):
                """Attempt the redirect exactly at the native commit boundary."""
                with self.assertRaises(OSError):
                    self.baseline.parent.rename(self.baseline.parent.with_name("moved"))
                return real_rename(*args, **kwargs)

            with mock.patch("windows_io._rename", side_effect=guarded_rename) as commit:
                SNAPSHOT.atomic_write_json(self.baseline, {"schema": "test"}, self.repo)
            self.assertTrue(commit.called)
            self.assertEqual({"schema": "test"}, json.loads(self.baseline.read_text(encoding="utf-8")))
            return
        parent = self.baseline.parent
        parent.mkdir(parents=True)
        held_parent = parent.with_name("held-parent")
        external = Path(self.temporary_directory.name) / "external-state"
        external.mkdir()
        original_replace = SNAPSHOT.os.replace
        swapped = False

        def swap_before_replace(*args: object, **kwargs: object) -> None:
            nonlocal swapped
            if not swapped:
                swapped = True
                parent.rename(held_parent)
                os.symlink(str(external), str(parent))
            original_replace(*args, **kwargs)

        with mock.patch.object(SNAPSHOT.os, "replace", side_effect=swap_before_replace):
            SNAPSHOT.atomic_write_json(self.baseline, {"schema": "test"}, self.repo)
        self.assertFalse((external / self.baseline.name).exists())
        self.assertEqual(
            {"schema": "test"},
            json.loads((held_parent / self.baseline.name).read_text(encoding="utf-8")),
        )

    def test_internal_json_read_uses_held_parent_directory(self) -> None:
        """Evidence reads must not follow a parent swapped after validation."""
        self.baseline.parent.mkdir(parents=True)
        self.baseline.write_text(json.dumps({"source": "trusted"}), encoding="utf-8")
        held_parent = self.baseline.parent.with_name("held-parent")
        external = Path(self.temporary_directory.name) / "external-state"
        external.mkdir()
        (external / self.baseline.name).write_text(
            json.dumps({"source": "external"}), encoding="utf-8"
        )
        original_open = windows_io._open if os.name == "nt" else SNAPSHOT.os.open
        swapped = False

        def swap_before_file_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            nonlocal swapped
            if not swapped and os.fspath(path) in {str(self.baseline), self.baseline.name}:
                swapped = True
                if os.name == "nt":
                    with self.assertRaises(OSError):
                        self.baseline.parent.rename(held_parent)
                else:
                    self.baseline.parent.rename(held_parent)
                    os.symlink(str(external), str(self.baseline.parent))
            return original_open(path, flags, *args, **kwargs)

        patch_target = windows_io if os.name == "nt" else SNAPSHOT.os
        patch_name = "_open" if os.name == "nt" else "open"
        with mock.patch.object(patch_target, patch_name, side_effect=swap_before_file_open):
            payload = SNAPSHOT.read_json_document(self.baseline, self.repo)
        self.assertTrue(swapped)
        self.assertEqual({"source": "trusted"}, payload)

    def test_invalid_snapshot_has_stable_cli_error_without_traceback(self) -> None:
        self.baseline.parent.mkdir(parents=True)
        self.baseline.write_text("{}", encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "compare",
                "--repo",
                str(self.repo),
                "--baseline",
                str(self.baseline),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("unsupported filesystem snapshot schema", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_snapshot_output_outside_internal_state(self) -> None:
        outside = Path(self.temporary_directory.name) / "outside.json"
        result = subprocess.run(
            [
                sys.executable,
                str(SCRIPT),
                "create",
                "--repo",
                str(self.repo),
                "--output",
                str(outside),
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("must stay under .codex/project-workflow", result.stderr)
        self.assertFalse(outside.exists())

    def test_cli_rejects_symlinked_state_directory_and_nested_parent(self) -> None:
        outside = Path(self.temporary_directory.name) / "external-state"
        outside.mkdir()
        (self.repo / ".codex").mkdir()
        os.symlink(str(outside), str(self.repo / ".codex/project-workflow"))
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "create", "--repo", str(self.repo),
             "--output", ".codex/project-workflow/baseline.json"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("symbolic link", result.stderr)
        self.assertFalse((outside / "baseline.json").exists())

        (self.repo / ".codex/project-workflow").unlink()
        (self.repo / ".codex/project-workflow").mkdir()
        os.symlink(str(outside), str(self.repo / ".codex/project-workflow/nested"))
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "create", "--repo", str(self.repo),
             "--output", ".codex/project-workflow/nested/baseline.json"],
            check=False, capture_output=True, text=True,
        )
        self.assertEqual(2, result.returncode)
        self.assertIn("symbolic link", result.stderr)
        self.assertFalse((outside / "baseline.json").exists())


if __name__ == "__main__":
    unittest.main()
