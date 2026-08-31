"""Black-box contract tests for documented Project Workflow commands."""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPOSITORY_ROOT / "plugins/project-workflow"
WORKFLOW_STATE = PLUGIN_ROOT / "scripts/workflow_state.py"
ORCHESTRATION_STATE = PLUGIN_ROOT / "scripts/orchestration_state.py"
DOCTOR = PLUGIN_ROOT / "scripts/project_workflow_doctor.py"
FILESYSTEM_SNAPSHOT = PLUGIN_ROOT / "scripts/filesystem_snapshot.py"
TASK_STATE = PLUGIN_ROOT / "scripts/task_state.py"
PUBLIC_DOCUMENTS = (
    REPOSITORY_ROOT / "README.md",
    REPOSITORY_ROOT / "README.zh-CN.md",
    PLUGIN_ROOT / "skills/index/SKILL.md",
    PLUGIN_ROOT / "skills/plan/SKILL.md",
    PLUGIN_ROOT / "skills/execute/SKILL.md",
)
SCRIPT_BY_NAME = {
    WORKFLOW_STATE.name: WORKFLOW_STATE,
    ORCHESTRATION_STATE.name: ORCHESTRATION_STATE,
    DOCTOR.name: DOCTOR,
    FILESYSTEM_SNAPSHOT.name: FILESYSTEM_SNAPSHOT,
    TASK_STATE.name: TASK_STATE,
}


class DocumentedCommandsTest(unittest.TestCase):
    """Keep public command examples aligned with the argparse surface."""

    @staticmethod
    def run_help(script: Path, subcommand: str | None = None) -> str:
        """Return public help for a script or one of its subcommands."""
        command = [sys.executable, str(script)]
        if subcommand:
            command.append(subcommand)
        command.append("--help")
        result = subprocess.run(command, check=False, capture_output=True, text=True)
        if result.returncode != 0:
            raise AssertionError(result.stderr or result.stdout)
        return result.stdout

    @staticmethod
    def documented_commands(document: Path) -> list[list[str]]:
        """Extract Python helper invocations from Markdown code blocks."""
        text = document.read_text(encoding="utf-8")
        commands: list[list[str]] = []
        for block in re.findall(r"```(?:bash|sh)?\s*\n(.*?)```", text, re.DOTALL):
            logical_lines = block.replace("\\\n", " ").splitlines()
            for line in logical_lines:
                line = line.strip()
                if not line.startswith("python3 ") or "/scripts/" not in line:
                    continue
                commands.append(shlex.split(line))
        return commands

    def test_canonical_lifecycle_and_doctor_commands_are_documented(self) -> None:
        """Expose stable compound commands as the primary v0.4 public contract."""
        for readme in PUBLIC_DOCUMENTS[:2]:
            text = readme.read_text(encoding="utf-8")
            self.assertIn("workflow_state.py start-execution", text, readme)
            self.assertIn("workflow_state.py complete", text, readme)
            self.assertIn("workflow_state.py experience", text, readme)
            self.assertIn("project_workflow_doctor.py --repo", text, readme)

        plan_skill = PUBLIC_DOCUMENTS[3].read_text(encoding="utf-8")
        execute_skill = PUBLIC_DOCUMENTS[4].read_text(encoding="utf-8")
        self.assertIn("project_workflow_doctor.py --repo", plan_skill)
        self.assertIn("workflow_state.py experience", plan_skill)
        self.assertIn("workflow_state.py experience", execute_skill)
        self.assertIn("workflow_state.py start-execution", execute_skill)
        self.assertIn("workflow_state.py create-baseline", execute_skill)
        self.assertIn("workflow_state.py complete", execute_skill)

    def test_filesystem_snapshot_commands_are_documented(self) -> None:
        """Publish both deterministic NONE-mode evidence commands."""
        for document in (*PUBLIC_DOCUMENTS[:2], PUBLIC_DOCUMENTS[4]):
            text = document.read_text(encoding="utf-8")
            self.assertIn("filesystem_snapshot.py create", text, document)
            self.assertIn("filesystem_snapshot.py compare", text, document)

    def test_recovery_and_snapshot_safety_contracts_are_documented(self) -> None:
        """Keep recovery, CAS, and explicit snapshot overrides visible."""
        readmes = [path.read_text(encoding="utf-8") for path in PUBLIC_DOCUMENTS[:2]]
        execute_skill = PUBLIC_DOCUMENTS[4].read_text(encoding="utf-8")
        for text in readmes:
            self.assertIn("workflow_state.py resume", text)
            self.assertIn("workflow_state.py create-baseline", text)
            self.assertIn("--replace-if-sha256", text)
            self.assertIn("--expected-version", text)
            self.assertIn("--stopped-evidence", text)
            self.assertIn("--report-only", text)
            self.assertIn("--json-details", text)
        self.assertIn("workflow_state.py resume", execute_skill)
        self.assertIn("--spawn-failed", execute_skill)
        self.assertIn("--stopped-evidence", execute_skill)

    def test_final_gate_topology_and_plan_cas_are_documented(self) -> None:
        """Keep the release-critical lifecycle and topology semantics explicit."""
        plan_skill = PUBLIC_DOCUMENTS[3].read_text(encoding="utf-8")
        execute_skill = PUBLIC_DOCUMENTS[4].read_text(encoding="utf-8")
        readmes = [path.read_text(encoding="utf-8") for path in PUBLIC_DOCUMENTS[:2]]
        self.assertIn("SINGLE_AGENT", plan_skill)
        self.assertIn("agent_topology: SHARED_WORKSPACE", plan_skill)
        self.assertNotIn("agent_topology: coordinator-only", plan_skill)
        self.assertIn("--expected-sha256", execute_skill)
        self.assertIn("accepted `state_version`", execute_skill)
        for text in readmes:
            self.assertIn("--expected-sha256", text)
            self.assertIn("--repo", text)
            self.assertIn("--final", text)

    def test_confirmation_skip_exits_and_native_icons_are_not_faked(self) -> None:
        """Do not weaken approval or claim plugin-owned agent artwork."""
        index_skill = PUBLIC_DOCUMENTS[2].read_text(encoding="utf-8")
        execute_skill = PUBLIC_DOCUMENTS[4].read_text(encoding="utf-8")
        self.assertIn("exit this workflow", index_skill)
        self.assertNotIn("Treat planning as skipped", index_skill)
        self.assertIn("icons are rendered by Codex", execute_skill)
        self.assertIn("does not reference or configure image assets", execute_skill)

    def test_documented_options_exist_in_argparse_help(self) -> None:
        """Reject misspelled options such as the historical positional ``--to`` drift."""
        commands_found = 0
        for document in PUBLIC_DOCUMENTS:
            for tokens in self.documented_commands(document):
                commands_found += 1
                script_name = Path(tokens[1]).name
                self.assertIn(script_name, SCRIPT_BY_NAME, (document, tokens))
                script = SCRIPT_BY_NAME[script_name]
                subcommand = None
                if script != DOCTOR and len(tokens) > 2 and not tokens[2].startswith("-"):
                    subcommand = tokens[2]
                top_help = self.run_help(script)
                if subcommand:
                    self.assertIn(subcommand, top_help, (document, tokens))
                command_help = self.run_help(script, subcommand)
                for token in tokens[2 if script == DOCTOR else 3 :]:
                    if token.startswith("--"):
                        self.assertIn(token, command_help, (document, tokens))

        self.assertGreater(commands_found, 0)

    def test_compound_command_positional_contract_is_stable(self) -> None:
        """Require PLAN to remain positional and confirmation to remain an option."""
        start_help = self.run_help(WORKFLOW_STATE, "start-execution")
        complete_help = self.run_help(WORKFLOW_STATE, "complete")
        experience_help = self.run_help(WORKFLOW_STATE, "experience")
        self.assertRegex(start_help, r"start-execution .*--confirmation CONFIRMATION")
        self.assertRegex(start_help, r"\n\s+plan\n")
        self.assertNotIn("--to", start_help)
        self.assertRegex(complete_help, r"\n\s+plan\n")
        self.assertRegex(experience_help, r"\n\s+plan\n")

    def test_doctor_help_exposes_only_portable_location_inputs(self) -> None:
        """Keep cache recovery internal and repository-relative inputs public."""
        help_text = self.run_help(DOCTOR)
        self.assertIn("--repo REPO", help_text)
        self.assertIn("--plan PLAN", help_text)
        self.assertIn("--orchestration ORCHESTRATION", help_text)
        self.assertIn("--json", help_text)
        self.assertNotIn("--plugin-root", help_text)

    def test_native_title_and_bounded_heartbeat_are_execution_invariants(self) -> None:
        """Keep the two user-facing long-task safeguards in the loaded skills."""
        plan_skill = PUBLIC_DOCUMENTS[3].read_text(encoding="utf-8")
        execute_skill = PUBLIC_DOCUMENTS[4].read_text(encoding="utf-8")
        self.assertIn("conversation_title", plan_skill)
        self.assertIn("progress_heartbeat_minutes", plan_skill)
        self.assertIn("set_thread_title", execute_skill)
        self.assertIn("progress_heartbeat_minutes", execute_skill)
        self.assertIn("completed/total task count", execute_skill)
        self.assertIn("next checkpoint", execute_skill)
        self.assertIn("do not use computer control", execute_skill.lower())

    def test_user_facing_plan_confirmation_is_localized(self) -> None:
        """Keep stable identifiers secondary to localized user-facing language."""
        plan_skill = " ".join(PUBLIC_DOCUMENTS[3].read_text(encoding="utf-8").split())
        self.assertIn("current conversation language", plan_skill)
        self.assertIn("secondary parenthetical", plan_skill)
        self.assertIn("natural-language feature title", plan_skill)
        self.assertIn("must not be presented as text the user has to copy", plan_skill)

    def test_public_documents_do_not_embed_plugin_cache_paths(self) -> None:
        """Prevent stale machine-specific plugin cache hints from entering sessions."""
        cache_path = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\\\).*?[.]codex[/\\\\]plugins[/\\\\]cache")
        for document in PUBLIC_DOCUMENTS:
            self.assertIsNone(cache_path.search(document.read_text(encoding="utf-8")), document)

    def test_full_release_plan_contains_its_required_migration_matrix(self) -> None:
        """Require this FULL persisted-state upgrade to enumerate recovery mappings."""
        plan = REPOSITORY_ROOT / "docs/plan/004-Project-Workflow-v0.4.0实施计划.md"
        text = plan.read_text(encoding="utf-8")
        self.assertRegex(text, r"workflow_profile:\s*[\"']?FULL")
        self.assertIn("迁移状态矩阵", text)
        for required_boundary in (
            "RUNNING",
            "缺失租约",
            "过期租约",
            "孤儿",
            "未知状态",
            "重复迁移",
            "回滚",
            "崩溃重入",
        ):
            self.assertIn(required_boundary, text, required_boundary)


if __name__ == "__main__":
    unittest.main()
