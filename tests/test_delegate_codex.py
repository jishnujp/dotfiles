"""Integration tests: real detached workers, a local fake Codex, no network."""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/bin/delegate-codex"
FAKE = r'''
import json
import os
from pathlib import Path
import signal
import sys
import time

prompt = sys.stdin.buffer.read()
mode = Path("mode").read_text()
print(json.dumps({"type": "thread.started", "thread_id": "fake-thread",
                  "argv": sys.argv[1:], "cwd": os.getcwd(), "path": os.environ["PATH"],
                  "env_keys": sorted(os.environ), "bytes": len(prompt),
                  "pid": os.getpid(), "sid": os.getsid(0)}), flush=True)
print("fake stderr", file=sys.stderr, flush=True)
if mode == "message":
    print(json.dumps({"type": "item.completed", "item": {
        "type": "agent_message", "text": "working on it"}}), flush=True)
if mode == "wait":
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    child = os.fork()
    if child == 0:
        while True:
            time.sleep(0.1)
    Path("child.pid").write_text(str(child))
    while True:
        time.sleep(0.1)
if mode == "fail":
    sys.exit(9)
if mode != "missing-result":
    Path(sys.argv[sys.argv.index("-o") + 1]).write_text("fake result\n")
'''


class DelegateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "jobs"
        self.cwd = self.base / "working directory"
        self.cwd.mkdir()
        self.fake = self.base / "fake-codex"
        self.fake.write_text("#!" + sys.executable + "\n" + FAKE)
        self.fake.chmod(0o755)
        self.env = dict(os.environ, DELEGATE_JOB_ROOT=str(self.root),
                        DELEGATE_SECRET="inherited-secret-must-not-leak")
        self.jobs = []

    def tearDown(self):
        # Join every launched worker before removing its files, even on failures.
        for job in self.jobs:
            self.run_cli("cancel", job, "--timeout", "6")
        self.temp.cleanup()

    def run_cli(self, *args, prompt=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], input=prompt,
                              text=True, capture_output=True, env=self.env, timeout=12)

    def launch(self, mode="success", prompt="test task", *options):
        (self.cwd / "mode").write_text(mode)
        result = self.run_cli("launch", "--cwd", str(self.cwd), "--codex", str(self.fake),
                              "--max-runtime", "8", *options, prompt=prompt)
        self.assertEqual(result.returncode, 0, result.stderr)
        job = result.stdout.strip()
        self.jobs.append(job)
        return job

    def state(self, job):
        result = self.run_cli("inspect", job)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def stored(self, job):
        return json.loads((self.root / job / "state.json").read_text())

    def wait_ready(self, job):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if (self.cwd / "child.pid").exists():
                return self.state(job)
            time.sleep(0.02)
        self.fail("fake Codex never became ready")

    def assert_stopped(self, pid):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            stat = Path(f"/proc/{pid}/stat")
            if stat.exists() and stat.read_text().split(")", 1)[1].split()[0] == "Z":
                return  # Container PID 1 may delay reaping an orphan zombie.
            time.sleep(0.02)
        self.fail(f"process {pid} still running")

    def test_success_and_interface(self):
        job = self.launch("success", "task", "--label", "fable_test",
                          "--model", "test-model")
        result = self.run_cli("join", job, "--timeout", "5")
        self.assertEqual(result.returncode, 0, result.stderr)
        state = json.loads(result.stdout)
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["label"], "fable_test")
        for key in ("created_at", "updated_at", "started_at", "finished_at",
                    "worker_pid", "codex_pid"):
            self.assertIsNotNone(state[key])
        event = json.loads((self.root / job / "events.jsonl").read_text())
        argv = event["argv"]
        self.assertEqual(argv[0], "exec")
        self.assertEqual(argv[-1], "-")
        self.assertIn("--json", argv)
        self.assertNotIn("--ephemeral", argv)
        self.assertIn("model_reasoning_effort=high", argv)
        self.assertIn('sandbox_mode="workspace-write"', argv)
        self.assertEqual(argv[argv.index("--model") + 1], "test-model")
        self.assertEqual(state["thread_id"], "fake-thread")
        self.assertEqual(argv[argv.index("-C") + 1], str(self.cwd))
        self.assertEqual(argv[argv.index("-o") + 1], str(self.root / job / "result.md"))
        self.assertEqual(event["cwd"], str(self.cwd))
        self.assertEqual(event["sid"], state["codex_pid"])
        self.assertEqual(self.run_cli("result", job).stdout, "fake result\n")
        self.assertEqual(json.loads(self.run_cli("list").stdout)[0]["job_id"], job)
        self.assertIn("fake stderr", (self.root / job / "stderr.log").read_text())
        self.assertEqual((self.root / job).stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.root / job / "state.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.run_cli("cancel", job).returncode, 0)
        self.assertEqual(self.stored(job), state)

    def test_join_multiple_jobs(self):
        first = self.launch("success")
        second = self.launch("success")
        result = self.run_cli("join", first, second, "--timeout", "5")
        self.assertEqual(result.returncode, 0, result.stderr)
        states = json.loads(result.stdout)
        self.assertEqual({state["job_id"] for state in states}, {first, second})
        self.assertTrue(all(state["status"] == "succeeded" for state in states))

    def test_timeout_kills_entire_group(self):
        job = self.launch("wait", "task", "--max-runtime", "0.7")
        state = self.wait_ready(job)
        result = self.run_cli("join", job, "--timeout", "6")
        self.assertEqual(result.returncode, 87, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "timed_out")
        self.assert_stopped(state["codex_pid"])
        self.assert_stopped(int((self.cwd / "child.pid").read_text()))

    def test_cancel_and_bounded_join(self):
        job = self.launch("wait")
        state = self.wait_ready(job)
        start = time.monotonic()
        self.assertEqual(self.run_cli("join", job, "--timeout", "0.1").returncode, 75)
        self.assertLess(time.monotonic() - start, 2)
        self.assertEqual(self.run_cli("result", job).returncode, 75)
        result = self.run_cli("cancel", job, "--timeout", "6")
        self.assertEqual(result.returncode, 130, result.stderr)
        final = json.loads(result.stdout)
        self.assertEqual(final["status"], "cancelled")
        self.assert_stopped(state["codex_pid"])
        self.assert_stopped(int((self.cwd / "child.pid").read_text()))
        self.assertEqual(self.run_cli("cancel", job).returncode, 130)
        self.assertEqual(self.stored(job), final)

    def test_prompt_and_environment_secrecy(self):
        secret = "prompt-secret-8b4ba7"
        prompt = secret * 10000  # Larger than a pipe's buffer.
        job = self.launch("wait", prompt)
        state = self.wait_ready(job)
        event = json.loads((self.root / job / "events.jsonl").read_text())
        self.assertEqual(event["bytes"], len(prompt))
        self.assertNotIn("DELEGATE_SECRET", event["env_keys"])
        self.assertNotIn("DELEGATE_JOB_ROOT", event["env_keys"])
        for pid in (state["worker_pid"], state["codex_pid"]):
            for name in ("cmdline", "environ"):
                path = Path(f"/proc/{pid}/{name}")
                if path.exists():
                    self.assertNotIn(secret.encode(), path.read_bytes())
                    self.assertNotIn(b"inherited-secret-must-not-leak", path.read_bytes())
        self.assertEqual(self.run_cli("cancel", job, "--timeout", "6").returncode, 130)
        for path in self.root.rglob("*"):
            if path.is_file():
                self.assertNotIn(secret.encode(), path.read_bytes())
                self.assertNotIn(b"inherited-secret-must-not-leak", path.read_bytes())

    def test_path_and_named_environment_are_forwarded(self):
        self.env.update(PATH="/opt/delegate-tools:" + os.environ["PATH"], DELEGATE_EXTRA="x")
        job = self.launch("success", "task", "--pass-env", "DELEGATE_EXTRA",
                          "--pass-env", "DELEGATE_UNSET")
        self.assertEqual(self.run_cli("join", job, "--timeout", "5").returncode, 0)
        event = json.loads((self.root / job / "events.jsonl").read_text())
        self.assertTrue(event["path"].startswith("/opt/delegate-tools:"))
        # No --model: the cheap default, never Codex's own (most expensive) default.
        self.assertEqual(event["argv"][event["argv"].index("--model") + 1], "gpt-5.6-sol")
        self.assertIn("DELEGATE_EXTRA", event["env_keys"])
        self.assertNotIn("DELEGATE_SECRET", event["env_keys"])
        self.assertNotIn("DELEGATE_UNSET", event["env_keys"])

    def test_resume_continues_the_thread(self):
        first = self.launch("success", "task", "--sandbox", "read-only", "--model", "m1")
        self.assertEqual(self.run_cli("join", first, "--timeout", "5").returncode, 0)
        result = self.run_cli("launch", "--resume", first, "--codex", str(self.fake),
                              "--max-runtime", "8", prompt="follow up")
        self.assertEqual(result.returncode, 0, result.stderr)
        second = result.stdout.strip()
        self.jobs.append(second)
        self.assertEqual(self.run_cli("join", second, "--timeout", "5").returncode, 0)
        argv = json.loads((self.root / second / "events.jsonl").read_text())["argv"]
        self.assertEqual(argv[:3], ["exec", "resume", "fake-thread"])
        self.assertNotIn("-C", argv)
        self.assertIn('sandbox_mode="read-only"', argv)
        self.assertEqual(argv[argv.index("--model") + 1], "m1")
        state = self.stored(second)
        self.assertEqual((state["resumed_from"], state["cwd"]), (first, str(self.cwd)))

    def test_resume_rejects_live_and_ephemeral_jobs(self):
        live = self.launch("wait")
        self.wait_ready(live)
        gone = self.launch("success", "task", "--ephemeral")
        self.assertEqual(self.run_cli("join", gone, "--timeout", "5").returncode, 0)
        self.assertIn("--ephemeral", json.loads((self.root / gone / "events.jsonl").read_text())["argv"])
        for job in (live, gone):
            result = self.run_cli("launch", "--resume", job, "--codex", str(self.fake), prompt="x")
            self.assertEqual(result.returncode, 125)
            self.assertEqual(result.stdout, "")
        result = self.run_cli("launch", "--codex", str(self.fake), prompt="x")
        self.assertEqual(result.returncode, 2)  # No --cwd and no --resume.

    def test_idle_timeout_stops_a_silent_run(self):
        job = self.launch("wait", "task", "--idle-timeout", "0.7")
        state = self.wait_ready(job)
        result = self.run_cli("join", job, "--timeout", "6")
        self.assertEqual(result.returncode, 87, result.stderr)
        final = json.loads(result.stdout)
        self.assertEqual((final["status"], final["timeout_reason"]), ("timed_out", "idle"))
        self.assert_stopped(state["codex_pid"])

    def test_killed_worker_is_reported_lost(self):
        job = self.launch("wait")
        state = self.wait_ready(job)
        os.kill(state["worker_pid"], signal.SIGKILL)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            result = self.run_cli("join", job, "--timeout", "0.5")
            if result.returncode != 75:
                break
        self.assertEqual(result.returncode, 125)
        self.assertEqual(json.loads(result.stdout)["status"], "lost")
        os.killpg(state["codex_pid"], signal.SIGKILL)  # The wrapper cannot reap this.
        # The thread id comes from the event log, so a lost job is still resumable.
        (self.cwd / "mode").write_text("success")
        result = self.run_cli("launch", "--resume", job, "--codex", str(self.fake),
                              "--max-runtime", "8", prompt="carry on")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.jobs.append(result.stdout.strip())
        self.assertEqual(self.run_cli("join", self.jobs[-1], "--timeout", "5").returncode, 0)

    def test_list_skips_a_stateless_directory(self):
        job = self.launch("success")
        self.assertEqual(self.run_cli("join", job, "--timeout", "5").returncode, 0)
        (self.root / "halfmade").mkdir()
        listed = self.run_cli("list")
        self.assertEqual(listed.returncode, 0, listed.stderr)
        self.assertEqual([state["job_id"] for state in json.loads(listed.stdout)], [job])

    def test_inspect_reports_progress(self):
        job = self.launch("message")
        self.assertEqual(self.run_cli("join", job, "--timeout", "5").returncode, 0)
        state = self.state(job)
        self.assertEqual(state["last_message"], "working on it")
        self.assertIsNotNone(state["last_event_at"])

    def test_invalid_job_label_and_duration(self):
        for command in ("inspect", "join", "result", "cancel"):
            self.assertEqual(self.run_cli(command, "../escape").returncode, 2)
            self.assertEqual(self.run_cli(command, "unknown").returncode, 125)
        for options in (("--label", "../escape"), ("--label", "bad label"),
                        ("--max-runtime", "nan"), ("--max-runtime", "inf"),
                        ("--max-runtime", "0"), ("--idle-timeout", "-1"),
                        ("--pass-env", "BAD-NAME")):
            result = self.run_cli("launch", "--cwd", str(self.cwd), *options, prompt="task")
            self.assertEqual(result.returncode, 2)
        self.root.mkdir()
        (self.root / "linked").symlink_to(self.cwd, target_is_directory=True)
        self.assertEqual(self.run_cli("inspect", "linked").returncode, 125)
        self.assertEqual(json.loads(self.run_cli("list").stdout), [])

    def test_codex_failure(self):
        job = self.launch("fail")
        result = self.run_cli("join", job, "--timeout", "5")
        self.assertEqual(result.returncode, 9)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")
        self.assertEqual(self.run_cli("result", job).returncode, 9)

    def test_runner_failure(self):
        self.fake.write_text("#!/no/such/interpreter\n")
        job = self.launch()
        result = self.run_cli("join", job, "--timeout", "5")
        self.assertEqual(result.returncode, 125)
        self.assertEqual(json.loads(result.stdout)["status"], "failed")

    def test_missing_result_is_runner_failure(self):
        job = self.launch("missing-result")
        self.assertEqual(self.run_cli("join", job, "--timeout", "5").returncode, 125)

    def test_defaults_and_help(self):
        # Inspect the parser without starting a real Codex process.
        import runpy
        module = runpy.run_path(str(SCRIPT), run_name="delegate_codex_test")
        args = module["parser"]().parse_args(["launch", "--cwd", str(self.cwd)])
        self.assertEqual(args.max_runtime, 14400)
        self.assertIsNone(args.sandbox)  # Resolved at launch: parent job's, else workspace-write.
        self.assertEqual(args.idle_timeout, 1800)
        self.assertFalse(args.ephemeral)
        self.assertEqual(args.reasoning, "high")
        self.assertIsNone(args.model)
        result = self.run_cli("--help")
        self.assertEqual(result.returncode, 0)
        self.assertNotIn("_worker", result.stdout)


if __name__ == "__main__":
    unittest.main()
