"""Black-box user contract tests for localized task-state UX."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
TASK_STATE = PLUGIN_ROOT / "scripts/task_state.py"


class StateUxContractTest(unittest.TestCase):
    """Exercise only public CLI behavior and generated plan documents."""

    def create_plan(self, root: Path, plan_id: str, marker: str) -> Path:
        """Create one historical plan fixture with user-authored prose."""
        plan = root / "docs/plan/plan.md"
        plan.parent.mkdir(parents=True)
        plan.write_text(
            f"""---
workflow: "project-workflow/v1"
policy_contract: "v0.4"
plan_id: "{plan_id}"
revision: 1
phase: "IN_PROGRESS"
approved_revision: 1
approved_at: "2026-08-31T00:00:00+00:00"
confirmation_record: "approved"
execution_mode: "SINGLE_AGENT"
---

# User plan

This sentence must stay byte-for-byte unchanged.

## T01 Build

- Status: [{marker}]
- Depends-On: none
- Acceptance:
  - [ ] user-owned checkbox
""",
            encoding="utf-8",
        )
        return plan

    def run_cli(self, *arguments: object) -> subprocess.CompletedProcess[str]:
        """Run the public task helper and require success."""
        result = subprocess.run(
            [sys.executable, str(TASK_STATE), *(str(item) for item in arguments)],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, result.returncode, result.stderr or result.stdout)
        return result

    def test_chinese_and_english_views_share_icons_and_preserve_user_text(self) -> None:
        """Render the two supported locales without changing free-form plan content."""
        expectations = (
            ("zh-CN", "实现状态：✅ 已完成", "验收状态：✅ 已通过"),
            ("en-US", "Implementation：✅ Completed", "Verification：✅ Passed"),
        )
        for index, (language, implementation, verification) in enumerate(expectations):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as temporary:
                repo = Path(temporary)
                plan = self.create_plan(repo, f"ux-{index}", "x")
                self.run_cli(
                    "migrate",
                    plan,
                    "--repo",
                    repo,
                    "--display-language",
                    language,
                )
                content = plan.read_text(encoding="utf-8")
                self.assertIn(implementation, content)
                self.assertIn(verification, content)
                self.assertIn("This sentence must stay byte-for-byte unchanged.", content)
                self.assertIn("  - [ ] user-owned checkbox", content)
                self.assertFalse(any(plan.parent.glob(".*.md.lock")))

    def test_unsupported_language_falls_back_and_legacy_progress_is_conservative(self) -> None:
        """Fall back to English and never infer verification from an active legacy task."""
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            plan = self.create_plan(repo, "ux-fallback", "~")
            result = self.run_cli(
                "migrate",
                plan,
                "--repo",
                repo,
                "--display-language",
                "ja-JP",
            )
            state = json.loads(result.stdout)
            self.assertEqual("en-US", state["display_language"])
            self.assertEqual("IN_PROGRESS", state["tasks"][0]["implementation_status"])
            self.assertEqual("NOT_STARTED", state["tasks"][0]["verification_status"])
            self.assertIn("Verification：⚪ Not started", plan.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
