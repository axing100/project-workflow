#!/usr/bin/env python3
"""Manage durable Project Workflow state stored in Markdown frontmatter."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


WORKFLOW = "project-workflow/v1"
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
    "BLOCKED": {"IN_PROGRESS", "AWAITING_CONFIRMATION"},
    "COMPLETED": set(),
}


class WorkflowError(ValueError):
    """Report invalid workflow state or an unsafe transition."""


def decode_value(value: str) -> object:
    """Decode a supported frontmatter scalar without external YAML packages."""
    value = value.strip()
    if not value:
        return ""
    if value.startswith('"'):
        try:
            return json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkflowError(f"invalid quoted frontmatter value: {value}") from exc
    if value.isdigit():
        return int(value)
    return value


def encode_value(value: object) -> str:
    """Encode a scalar in the restricted frontmatter format."""
    if value is None or value == "":
        return ""
    if isinstance(value, int):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def parse_document(path: Path) -> Tuple[Dict[str, object], List[str], str]:
    """Return metadata, key order, and the untouched Markdown body."""
    if not path.is_file():
        raise WorkflowError(f"plan file does not exist: {path}")
    text = path.read_text(encoding="utf-8")
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


def require_common(metadata: Dict[str, object]) -> Tuple[int, str]:
    """Validate fields shared by approval, execution, and transitions."""
    missing = [key for key in REQUIRED_FIELDS if key not in metadata]
    if missing:
        raise WorkflowError(f"missing required fields: {', '.join(missing)}")
    if metadata["workflow"] != WORKFLOW:
        raise WorkflowError(f"unsupported workflow: {metadata['workflow']}")
    if not str(metadata["plan_id"]).strip():
        raise WorkflowError("plan_id must not be empty")
    revision = metadata["revision"]
    if not isinstance(revision, int) or revision < 1:
        raise WorkflowError("revision must be a positive integer")
    phase = str(metadata["phase"])
    if phase not in VALID_PHASES:
        raise WorkflowError(f"invalid phase: {phase}")
    return revision, phase


def command_inspect(args: argparse.Namespace) -> None:
    """Print normalized workflow state as JSON."""
    metadata, _, _ = parse_document(args.plan)
    require_common(metadata)
    print(json.dumps(metadata, ensure_ascii=False, indent=2))


def command_init(args: argparse.Namespace) -> None:
    """Initialize a new or draft plan at the confirmation boundary."""
    metadata, order, body = parse_document(args.plan)
    existing_phase = str(metadata.get("phase", "DRAFT"))
    if existing_phase not in {"DRAFT", "AWAITING_CONFIRMATION"}:
        raise WorkflowError(f"cannot initialize plan in phase {existing_phase}")
    revision = metadata.get("revision", 1)
    if not isinstance(revision, int) or revision < 1:
        raise WorkflowError("revision must be a positive integer")
    existing_plan_id = str(metadata.get("plan_id", "")).strip()
    plan_id = args.plan_id.strip() or existing_plan_id
    if not plan_id:
        raise WorkflowError("plan_id must not be empty")
    metadata.update(
        {
            "workflow": WORKFLOW,
            "plan_id": plan_id,
            "revision": revision,
            "phase": "AWAITING_CONFIRMATION",
            "approved_revision": "",
            "approved_at": "",
            "confirmation_record": "",
        }
    )
    write_document(args.plan, metadata, order, body)
    print(f"initialized {plan_id} revision {revision} at AWAITING_CONFIRMATION")


def command_approve(args: argparse.Namespace) -> None:
    """Record explicit approval for the current revision."""
    confirmation = args.confirmation.strip()
    if not confirmation:
        raise WorkflowError("confirmation must contain the explicit user message")
    metadata, order, body = parse_document(args.plan)
    revision, phase = require_common(metadata)
    if phase != "AWAITING_CONFIRMATION":
        raise WorkflowError(f"approval requires AWAITING_CONFIRMATION, found {phase}")
    approved_at = args.at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    metadata.update(
        {
            "phase": "APPROVED",
            "approved_revision": revision,
            "approved_at": approved_at,
            "confirmation_record": confirmation,
        }
    )
    write_document(args.plan, metadata, order, body)
    print(f"approved revision {revision} at {approved_at}")


def command_check_execute(args: argparse.Namespace) -> None:
    """Fail unless the plan has a current, explicit approval record."""
    metadata, _, _ = parse_document(args.plan)
    revision, phase = require_common(metadata)
    if phase not in {"APPROVED", "IN_PROGRESS"}:
        raise WorkflowError(f"execution requires APPROVED or IN_PROGRESS, found {phase}")
    if metadata["approved_revision"] != revision:
        raise WorkflowError(
            f"approved_revision {metadata['approved_revision']} does not match revision {revision}"
        )
    if not str(metadata["approved_at"]).strip():
        raise WorkflowError("approved_at must not be empty")
    if not str(metadata["confirmation_record"]).strip():
        raise WorkflowError("confirmation_record must not be empty")
    print(f"execution allowed for {metadata['plan_id']} revision {revision} in {phase}")


def command_transition(args: argparse.Namespace) -> None:
    """Apply a legal workflow phase transition."""
    metadata, order, body = parse_document(args.plan)
    revision, phase = require_common(metadata)
    target = args.phase
    if target not in ALLOWED_TRANSITIONS[phase]:
        raise WorkflowError(f"illegal transition: {phase} -> {target}")
    if target == "APPROVED":
        raise WorkflowError("use the approve command to enter APPROVED")
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

    init_parser = subparsers.add_parser("init", help="initialize a plan for confirmation")
    init_parser.add_argument("plan", type=Path)
    init_parser.add_argument("--plan-id", required=True)
    init_parser.set_defaults(handler=command_init)

    approve_parser = subparsers.add_parser("approve", help="record explicit user approval")
    approve_parser.add_argument("plan", type=Path)
    approve_parser.add_argument("--confirmation", required=True)
    approve_parser.add_argument("--at", help="ISO-8601 approval time; defaults to current UTC")
    approve_parser.set_defaults(handler=command_approve)

    check_parser = subparsers.add_parser("check-execute", help="validate execution eligibility")
    check_parser.add_argument("plan", type=Path)
    check_parser.set_defaults(handler=command_check_execute)

    transition_parser = subparsers.add_parser("transition", help="apply a legal phase transition")
    transition_parser.add_argument("plan", type=Path)
    transition_parser.add_argument("phase", choices=sorted(VALID_PHASES))
    transition_parser.add_argument("--increment-revision", action="store_true")
    transition_parser.set_defaults(handler=command_transition)
    return parser


def main() -> int:
    """Run the workflow state command."""
    parser = build_parser()
    args = parser.parse_args()
    try:
        args.handler(args)
    except (OSError, WorkflowError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
