"""独立公开 CLI 契约验收，不导入或读取生产实现。

@author chenjiaxing
@since 2026-09-05
"""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class WindowsContractTest(unittest.TestCase):
    """跨平台黑盒契约与原生 Windows 专属边界。

    @author chenjiaxing
    @since 2026-09-05
    """

    def setUp(self):
        """为每个用例隔离工作区和外部哨兵。"""
        self.temp = tempfile.TemporaryDirectory(prefix="workflow-contract-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "中文 空格 workspace"
        self.root.mkdir()
        self.plan = self.root / "plan.md"
        self.baseline = ".codex/project-workflow/contract/filesystem-baseline.json"

    def command(self, script, *args):
        """仅通过公开进程入口调用被测产品。"""
        return [sys.executable, str(SCRIPTS / (script + ".py")), *map(str, args)]

    def cli(self, script, *args, ok=True):
        """执行有超时的 CLI，并保留失败诊断。"""
        result = subprocess.run(self.command(script, *args), cwd=self.root,
                                capture_output=True, text=True, encoding="utf-8",
                                timeout=30)
        detail = result.stdout + result.stderr
        if ok:
            self.assertEqual(result.returncode, 0, detail)
        else:
            self.assertNotEqual(result.returncode, 0, detail)
        return result

    def fixture(self, mode="NONE"):
        """使用公开 frontmatter 与旧任务标记创建可迁移计划。"""
        if mode == "GIT":
            if not shutil.which("git"):
                self.skipTest("GIT 生命周期需要原生 Git")
            subprocess.run(["git", "init", str(self.root)], check=True,
                           capture_output=True)
        self.plan.write_text(
            "---\nworkflow: project-workflow/v1\nplan_id: contract\n"
            "revision: 1\nphase: AWAITING_CONFIRMATION\nworkflow_profile: STANDARD\n"
            "approved_revision:\napproved_at:\nconfirmation_record:\n"
            f"vcs_mode: {mode}\nresolved_vcs_mode: {mode}\n"
            'rollback_required: "false"\nfilesystem_write_scopes: ["payload.txt", "plan.md"]\n'
            'filesystem_snapshot_scopes: []\nfilesystem_snapshot_excludes: []\n'
            "---\n# 独立验收\n\n## T01 Contract task\n\n- Status: [ ]\n"
            "- Write-Scope: payload.txt\n", encoding="utf-8")
        self.cli("task_state", "migrate", self.plan, "--repo", self.root)

    def start(self):
        """模拟明确确认的公开调用，不宣称自然语言真实性被密码学验证。"""
        return self.cli("workflow_state", "start-execution", self.plan,
                        "--repo", self.root, "--confirmation", "我批准 contract revision 1")

    def snap(self, *args, ok=True):
        """创建独立快照。"""
        return self.cli("filesystem_snapshot", "create", "--repo", self.root,
                        "--output", self.baseline, *args, ok=ok)

    def test_all_public_help(self):
        """五个公开入口必须在当前原生 Python 下启动。"""
        for script in ("workflow_state", "task_state", "orchestration_state",
                       "filesystem_snapshot", "project_workflow_doctor"):
            with self.subTest(script=script):
                self.assertIn("usage:", self.cli(script, "--help").stdout)

    def test_unapproved_execution_rejected(self):
        """未批准计划不能直接进入执行且不能部分写入。"""
        self.fixture()
        before = self.plan.read_bytes()
        self.cli("workflow_state", "transition", self.plan, "IN_PROGRESS",
                 "--repo", self.root, ok=False)
        self.assertEqual(self.plan.read_bytes(), before)

    def test_empty_confirmation_rejected(self):
        """空确认不能改变审批字段。"""
        self.fixture()
        before = self.plan.read_bytes()
        self.cli("workflow_state", "start-execution", self.plan, "--repo", self.root,
                 "--confirmation", "", ok=False)
        self.assertEqual(self.plan.read_bytes(), before)

    def test_old_revision_rejected(self):
        """旧 revision 审批 CAS 必须无写入失败。"""
        self.fixture()
        before = self.plan.read_bytes()
        self.cli("workflow_state", "start-execution", self.plan, "--repo", self.root,
                 "--confirmation", "批准旧版", "--expected-revision", "0", ok=False)
        self.assertEqual(self.plan.read_bytes(), before)

    def test_cross_process_plan_cas(self):
        """真实独立进程同时使用旧摘要时只能有一个写入者成功。"""
        self.fixture()
        digest = hashlib.sha256(self.plan.read_bytes()).hexdigest()
        command = self.command("workflow_state", "start-execution", self.plan,
                               "--repo", self.root, "--confirmation", "批准 contract",
                               "--expected-sha256", digest)
        workers = [subprocess.Popen(command, cwd=self.root, stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE) for _ in range(6)]
        outputs = [worker.communicate(timeout=45) for worker in workers]
        self.assertEqual(sum(worker.returncode == 0 for worker in workers), 1, outputs)
        self.cli("workflow_state", "validate", self.plan)

    def test_task_stale_version_rejected(self):
        """任务旧版本 CAS 不能覆盖较新状态。"""
        self.fixture()
        self.start()
        path = self.root / ".codex/project-workflow/contract/state.json"
        version = json.loads(path.read_text(encoding="utf-8"))["state_version"]
        self.cli("task_state", "start-implementation", self.plan, "T01", "--repo",
                 self.root, "--expected-version", version)
        before = path.read_bytes()
        self.cli("task_state", "complete-implementation", self.plan, "T01", "--repo",
                 self.root, "--expected-version", version, "--evidence", "done", ok=False)
        self.assertEqual(path.read_bytes(), before)

    def test_failed_verification_blocks_completion(self):
        """实现完成不能掩盖验收失败。"""
        self.fixture()
        self.start()
        for action, extra in (("start-implementation", []),
                              ("complete-implementation", ["--evidence", "done"]),
                              ("start-verification", []),
                              ("fail-verification", ["--evidence", "contract failed"])):
            self.cli("task_state", action, self.plan, "T01", "--repo", self.root, *extra)
        before = self.plan.read_bytes()
        state = self.cli("task_state", "inspect", self.plan, "--repo", self.root)
        self.assertIn("FAILED", state.stdout)
        self.cli("workflow_state", "complete", self.plan, "--repo", self.root, ok=False)
        self.assertEqual(self.plan.read_bytes(), before)

    def lifecycle(self, mode):
        """覆盖批准、实现、验收、完成的完整串行生命周期。"""
        self.fixture(mode)
        self.start()
        for action, extra in (("start-implementation", []),
                              ("complete-implementation", ["--evidence", "done"]),
                              ("start-verification", []),
                              ("pass-verification", ["--evidence", "black-box passed"])):
            self.cli("task_state", action, self.plan, "T01", "--repo", self.root, *extra)
        self.cli("workflow_state", "complete", self.plan, "--repo", self.root)
        self.assertIn("COMPLETED", self.cli("workflow_state", "inspect", self.plan).stdout)

    def test_none_full_lifecycle(self):
        """无 Git 生命周期不删减验收门禁。"""
        self.lifecycle("NONE")

    def test_missing_task_state_blocks_completion(self):
        """迁移后的任务状态丢失不能降级为无任务门禁完成。"""
        self.fixture()
        self.start()
        state = self.root / ".codex/project-workflow/contract/state.json"
        self.assertTrue(state.is_file())
        state.unlink()
        before = self.plan.read_bytes()
        self.cli("workflow_state", "complete", self.plan, "--repo", self.root, ok=False)
        self.assertEqual(self.plan.read_bytes(), before)
        self.assertFalse(state.exists())

    def test_git_full_lifecycle(self):
        """Git 生命周期保留完整门禁。"""
        self.lifecycle("GIT")

    def test_corrupt_task_state_preserved(self):
        """损坏与未知版本必须拒绝且保留原字节。"""
        self.fixture()
        path = self.root / ".codex/project-workflow/contract/state.json"
        for payload in (b"{broken", b'{"schema":"future/v999"}'):
            with self.subTest(payload=payload):
                path.write_bytes(payload)
                self.cli("task_state", "migrate", self.plan, "--repo", self.root, ok=False)
                self.assertEqual(path.read_bytes(), payload)

    def test_snapshot_create_only_and_failed_recovery(self):
        """普通重复创建和错误恢复摘要均不得覆盖基线。"""
        self.snap()
        path = self.root / self.baseline
        before = path.read_bytes()
        (self.root / "payload.txt").write_text("new", encoding="utf-8")
        self.snap(ok=False)
        self.snap("--replace-if-sha256", "0" * 64, ok=False)
        self.assertEqual(path.read_bytes(), before)

    def test_snapshot_scope_and_unicode(self):
        """Unicode/空格路径差异必须可读且字面量范围越界失败。"""
        self.snap()
        (self.root / "中文 文件.txt").write_text("内容", encoding="utf-8")
        self.cli("filesystem_snapshot", "compare", "--repo", self.root,
                 "--baseline", self.baseline, "--write-scope", "payload.txt", ok=False)
        result = self.cli("filesystem_snapshot", "compare", "--repo", self.root,
                          "--baseline", self.baseline, "--write-scope", "中文 文件.txt")
        self.assertIn("中文 文件.txt", result.stdout)

    def test_snapshot_outside_output_rejected(self):
        """外部输出不得创建或覆盖外部文件。"""
        outside = Path(self.temp.name) / "outside.json"
        outside.write_text("sentinel", encoding="utf-8")
        self.cli("filesystem_snapshot", "create", "--repo", self.root,
                 "--output", outside, ok=False)
        self.assertEqual(outside.read_text(), "sentinel")

    def test_long_nested_path_snapshot(self):
        """总长度超过传统 MAX_PATH 的合法路径必须完整取证。"""
        nested = self.root.joinpath(*(["长目录-" + "x" * 30] * 9))
        nested.mkdir(parents=True)
        (nested / "file.txt").write_text("evidence", encoding="utf-8")
        self.snap()
        self.cli("filesystem_snapshot", "compare", "--repo", self.root,
                 "--baseline", self.baseline)

    def test_doctor_none_is_read_only(self):
        """Doctor NONE 预检不创建内部状态。"""
        before = sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*"))
        result = self.cli("project_workflow_doctor", "--repo", self.root,
                          "--vcs-mode", "NONE", "--json")
        self.assertEqual(json.loads(result.stdout)["version_control"]["resolved"], "NONE")
        self.assertEqual(before, sorted(str(path.relative_to(self.root)) for path in self.root.rglob("*")))

    def scheduler(self):
        """用公开 JSON task 参数创建允许委派的调度夹具。"""
        self.fixture("GIT")
        self.state = self.root / ".codex/project-workflow/contract/orchestration.json"
        content = self.plan.read_text(encoding="utf-8").replace(
            "---\n", "---\n"
            "execution_mode: AUTO_MULTI_AGENT\nmax_workers: 2\n"
            "agent_topology: SHARED_WORKSPACE\n"
            "orchestration_state: .codex/project-workflow/contract/orchestration.json\n", 1)
        self.plan.write_text(content, encoding="utf-8")
        task = json.dumps({"id": "T01", "display_name": "Contract", "depends_on": [],
                           "write_scope": ["payload.txt"], "agent_eligible": True})
        self.cli("orchestration_state", "init", self.state, "--plan", self.plan,
                 "--repo", self.root, "--task", task)
        self.start()
        self.cli("orchestration_state", "assign", self.state, "T01", "--plan", self.plan,
                 "--repo", self.root, "--owner", "contract-worker")

    def test_pending_worker_cannot_complete(self):
        """未绑定真实运行时的预留任务不得被冒充完成。"""
        self.scheduler()
        before = self.state.read_bytes()
        self.cli("orchestration_state", "complete", self.state, "T01", "--plan",
                 self.plan, "--repo", self.root, "--runtime-agent-id", "fabricated",
                 "--evidence", "forged completion", ok=False)
        self.assertEqual(self.state.read_bytes(), before)

    def test_scheduler_stale_cas(self):
        """调度状态旧版本无写入失败。"""
        self.scheduler()
        before = self.state.read_bytes()
        self.cli("orchestration_state", "release", self.state, "T01", "--plan",
                 self.plan, "--repo", self.root, "--spawn-failed",
                 "--expected-version", "0", ok=False)
        self.assertEqual(self.state.read_bytes(), before)

    def test_mismatched_runtime_completion(self):
        """结构绑定后的不同身份不能完成；此用例不声称绑定 ID 真实。"""
        self.scheduler()
        self.cli("orchestration_state", "activate", self.state, "T01", "--plan",
                 self.plan, "--repo", self.root, "--runtime-agent-id", "fixture-agent",
                 "--runtime-task-name", "/root/contract-worker")
        before = self.state.read_bytes()
        self.cli("orchestration_state", "complete", self.state, "T01", "--plan",
                 self.plan, "--repo", self.root, "--runtime-agent-id", "different-agent",
                 "--evidence", "forged completion", ok=False)
        self.assertEqual(self.state.read_bytes(), before)

    def test_unknown_orchestration_preserved(self):
        """未知调度 schema 不能被普通 init 覆盖。"""
        self.scheduler()
        payload = b'{"schema":"project-workflow/orchestration/v999"}'
        self.state.write_bytes(payload)
        self.cli("orchestration_state", "init", self.state, "--plan", self.plan,
                 "--repo", self.root, "--task", '{"id":"T01"}', ok=False)
        self.assertEqual(self.state.read_bytes(), payload)

    def test_bilingual_render_idempotent(self):
        """中英渲染后再次同语言渲染不改变计划。"""
        self.fixture()
        for locale in ("zh-CN", "en-US"):
            self.cli("task_state", "migrate", self.plan, "--repo", self.root,
                     "--display-language", locale)
            self.cli("task_state", "render", self.plan, "--repo", self.root)
            before = self.plan.read_bytes()
            self.cli("task_state", "render", self.plan, "--repo", self.root)
            self.assertEqual(self.plan.read_bytes(), before)

    def test_unknown_plan_phase_preserved(self):
        """未知工作流状态不得被初始化覆盖。"""
        self.fixture()
        content = self.plan.read_text(encoding="utf-8").replace("AWAITING_CONFIRMATION", "FUTURE_PHASE")
        self.plan.write_text(content, encoding="utf-8")
        before = self.plan.read_bytes()
        self.cli("workflow_state", "init", self.plan, "--plan-id", "contract",
                 "--repo", self.root, "--vcs-mode", "NONE", ok=False)
        self.assertEqual(self.plan.read_bytes(), before)

    @unittest.skipUnless(os.name == "nt", "仅原生 Windows 能验证保留设备名与 ADS")
    def test_windows_reserved_outputs_rejected(self):
        """Windows 设备名和 ADS 不得被接受为普通证据文件。"""
        for output in ("NUL", "CON.json", "file.txt:stream"):
            with self.subTest(output=output):
                self.cli("filesystem_snapshot", "create", "--repo", self.root,
                         "--output", output, ok=False)

    @unittest.skipUnless(os.name == "nt", "仅原生 Windows 能验证 junction 拒绝行为")
    def test_windows_junction_output_rejected(self):
        """junction 输出路径不得逃逸至工作区外。"""
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        link = self.root / "redirect"
        result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)],
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.addCleanup(lambda: os.rmdir(link) if link.exists() else None)
        self.cli("filesystem_snapshot", "create", "--repo", self.root,
                 "--output", "redirect/baseline.json", ok=False)
        self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
