#!/usr/bin/env python3
"""Install Project Workflow from an isolated cache-busted staging copy."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


PLUGIN_NAME = "project-workflow"
MARKETPLACE_NAME = "project-workflow-local"
MANIFEST_RELATIVE_PATH = Path(".codex-plugin/plugin.json")
MARKETPLACE_RELATIVE_PATH = Path(".agents/plugins/marketplace.json")
SEMVER_PATTERN = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)


def parse_args() -> argparse.Namespace:
    """Parse the local installation arguments."""
    parser = argparse.ArgumentParser(
        description=(
            "Install Project Workflow from a temporary copy so the repository manifest "
            "keeps its release version."
        )
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Project Workflow repository root",
    )
    parser.add_argument(
        "--cachebuster",
        help="Optional lowercase cache token; defaults to a UTC timestamp",
    )
    parser.add_argument(
        "--codex-bin",
        default="codex",
        help="Codex executable used for installation",
    )
    return parser.parse_args()


def sanitize_cachebuster(value: str) -> str:
    """Return a SemVer build-metadata-safe cache token."""
    sanitized = re.sub(r"[^a-z0-9-]+", "-", value.strip().lower())
    sanitized = re.sub(r"-{2,}", "-", sanitized).strip("-")
    if not sanitized:
        raise ValueError("Cachebuster must contain at least one letter or digit.")
    return sanitized


def default_cachebuster() -> str:
    """Return a collision-resistant, SemVer-safe local installation token."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{timestamp}-{secrets.token_hex(4)}"


def load_json(path: Path) -> dict[str, object]:
    """Load a JSON object from the requested path."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must contain a JSON object.")
    return payload


def release_version(manifest: dict[str, object], path: Path) -> str:
    """Validate and return the clean repository release version."""
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError(f"{path} must contain a non-empty string 'version'.")
    if "+" in version:
        raise ValueError(
            f"{path} must keep a clean release version without build metadata: {version}"
        )
    if SEMVER_PATTERN.fullmatch(version) is None:
        raise ValueError(f"{path} must contain a valid SemVer release version: {version}")
    return version


def create_staging_marketplace(
    repo_root: Path,
    staging_root: Path,
    cachebuster: str,
) -> str:
    """Copy the marketplace and add cache metadata only to the staged manifest."""
    source_plugin = repo_root / "plugins" / PLUGIN_NAME
    source_marketplace = repo_root / MARKETPLACE_RELATIVE_PATH
    source_manifest = source_plugin / MANIFEST_RELATIVE_PATH
    if not source_plugin.is_dir():
        raise FileNotFoundError(f"missing plugin directory: {source_plugin}")
    if not source_marketplace.is_file():
        raise FileNotFoundError(f"missing marketplace: {source_marketplace}")
    if not source_manifest.is_file():
        raise FileNotFoundError(f"missing plugin manifest: {source_manifest}")

    staged_plugin = staging_root / "plugins" / PLUGIN_NAME
    staged_marketplace = staging_root / MARKETPLACE_RELATIVE_PATH
    shutil.copytree(source_plugin, staged_plugin)
    staged_marketplace.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_marketplace, staged_marketplace)

    manifest = load_json(staged_plugin / MANIFEST_RELATIVE_PATH)
    version = release_version(manifest, source_manifest)
    staged_version = f"{version}+codex.{cachebuster}"
    if SEMVER_PATTERN.fullmatch(staged_version) is None:
        raise ValueError(f"generated staged version is not valid SemVer: {staged_version}")
    manifest["version"] = staged_version
    (staged_plugin / MANIFEST_RELATIVE_PATH).write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    return staged_version


def run_codex(codex_bin: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run one Codex plugin command and capture text output."""
    return subprocess.run(
        [codex_bin, *arguments],
        check=True,
        capture_output=True,
        text=True,
    )


def configured_marketplace_root(codex_bin: str) -> Path:
    """Return the configured source root for the Project Workflow marketplace."""
    result = run_codex(codex_bin, "plugin", "marketplace", "list")
    for line in result.stdout.splitlines():
        columns = line.split(maxsplit=1)
        if len(columns) == 2 and columns[0] == MARKETPLACE_NAME:
            return Path(columns[1]).expanduser().resolve()
    raise RuntimeError(f"Marketplace is not configured: {MARKETPLACE_NAME}")


def install_staged_plugin(
    codex_bin: str,
    staging_root: Path,
    repo_root: Path,
) -> None:
    """Install from staging and restore the original marketplace in all outcomes."""
    repo_root = repo_root.expanduser().resolve()
    configured_root = configured_marketplace_root(codex_bin)
    if configured_root != repo_root:
        raise RuntimeError(
            f"{MARKETPLACE_NAME} points to {configured_root}, expected {repo_root}"
        )

    original_removed = False
    staging_added = False
    operation_error: Optional[BaseException] = None
    try:
        run_codex(
            codex_bin,
            "plugin",
            "marketplace",
            "remove",
            MARKETPLACE_NAME,
        )
        original_removed = True
        run_codex(codex_bin, "plugin", "marketplace", "add", str(staging_root))
        staging_added = True
        result = run_codex(
            codex_bin,
            "plugin",
            "add",
            f"{PLUGIN_NAME}@{MARKETPLACE_NAME}",
        )
        if result.stdout:
            print(result.stdout, end="")
    except BaseException as exc:
        operation_error = exc

    cleanup_error: Optional[BaseException] = None
    restore_error: Optional[BaseException] = None
    if staging_added:
        try:
            run_codex(
                codex_bin,
                "plugin",
                "marketplace",
                "remove",
                MARKETPLACE_NAME,
            )
        except BaseException as exc:
            cleanup_error = exc
    if original_removed:
        try:
            run_codex(codex_bin, "plugin", "marketplace", "add", str(repo_root))
        except BaseException as exc:
            restore_error = exc

    if restore_error is not None:
        message = "failed to restore the original Project Workflow marketplace"
        if operation_error is not None:
            message = f"plugin installation failed and {message}"
        raise RuntimeError(message) from restore_error
    if operation_error is not None:
        if cleanup_error is not None:
            raise operation_error.with_traceback(operation_error.__traceback__) from cleanup_error
        raise operation_error.with_traceback(operation_error.__traceback__)
    if cleanup_error is not None:
        raise RuntimeError("plugin installed but temporary marketplace cleanup failed") from cleanup_error


def main() -> None:
    """Create a disposable marketplace, install it, and remove the staging files."""
    args = parse_args()
    repo_root = args.repo_root.expanduser().resolve()
    cachebuster = sanitize_cachebuster(args.cachebuster or default_cachebuster())
    with tempfile.TemporaryDirectory(prefix="project-workflow-install-") as temp_dir:
        staging_root = Path(temp_dir)
        staged_version = create_staging_marketplace(
            repo_root,
            staging_root,
            cachebuster,
        )
        install_staged_plugin(args.codex_bin, staging_root, repo_root)
    print(f"Installed {PLUGIN_NAME} {staged_version}; source manifest was not modified.")


if __name__ == "__main__":
    main()
