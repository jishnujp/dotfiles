"""Unit tests for delegation-ledger against synthetic copies of the three log formats."""

import importlib.machinery
import importlib.util
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/bin/delegation-ledger"
loader = importlib.machinery.SourceFileLoader("ledger", str(SCRIPT))  # no .py suffix on the script
spec = importlib.util.spec_from_loader("ledger", loader)
ledger = importlib.util.module_from_spec(spec)
loader.exec_module(ledger)


def write_jsonl(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def codex_session(session_id, model, effort, sandbox, prompt, usages, limits, source="exec",
                  started="2026-09-20T10:00:00.000Z"):
    events = [{"timestamp": started, "type": "session_meta",
               "payload": {"session_id": session_id, "id": session_id, "timestamp": started,
                           "cwd": "/repo", "originator": "codex_exec", "source": source,
                           "cli_version": "0.156.1", "git": {"branch": "main"}}},
              {"timestamp": started, "type": "response_item",
               "payload": {"type": "message", "role": "user",
                           "content": [{"type": "input_text", "text": "<environment_context>...</environment_context>"}]}},
              {"timestamp": started, "type": "turn_context",
               "payload": {"model": model, "effort": effort, "sandbox_policy": {"type": sandbox}}},
              {"timestamp": started, "type": "event_msg", "payload": {"type": "user_message", "message": prompt}}]
    minute = 1
    for usage, pct in zip(usages, limits):
        ts = f"2026-09-20T10:{minute:02d}:00.000Z"
        events.append({"timestamp": ts, "type": "token_usage_record", "payload": {"usage": usage}})
        events.append({"timestamp": ts, "type": "response_item", "payload": {"type": "custom_tool_call"}})
        events.append({"timestamp": ts, "type": "event_msg",
                       "payload": {"type": "token_count", "rate_limits": {
                           "primary": {"used_percent": pct, "resets_at": 1790264304, "window_minutes": 10080},
                           "plan_type": "prolite"}}})
        minute += 1
    events.append({"timestamp": f"2026-09-20T10:{minute:02d}:00.000Z", "type": "event_msg",
                   "payload": {"type": "task_complete"}})
    return events


def claude_lines(session_id, model, effort, prompt, usages, sidechain=False, agent_id=None):
    lines = [{"type": "user", "timestamp": "2026-09-19T08:00:00.000Z", "sessionId": session_id,
              "cwd": "/repo", "gitBranch": "main", "version": "2.1.280", "isSidechain": sidechain,
              "message": {"role": "user", "content": [{"type": "text", "text": prompt}]}}]
    if agent_id:
        lines[0]["agentId"] = agent_id
    for index, usage in enumerate(usages):
        for block in range(2):  # the transcript repeats usage on every content block
            line = {"type": "assistant", "timestamp": f"2026-09-19T08:{index + 1:02d}:00.000Z",
                    "sessionId": session_id, "effort": effort, "isSidechain": sidechain,
                    "requestId": f"req{index}", "apiBlockIndex": block,
                    "message": {"id": f"msg{index}", "model": model, "usage": usage,
                                "content": [{"type": "tool_use"}] if block == 1 else [{"type": "text", "text": "x"}]}}
            if agent_id:
                line["agentId"] = agent_id
            lines.append(line)
    return lines


class Fixture:
    def __init__(self, root):
        self.root = Path(root)
        self.codex = self.root / "codex"
        self.claude = self.root / "claude"
        self.jobs = self.root / "jobs"
        for directory in (self.codex / "sessions/2026/09/20", self.claude / "projects/-repo", self.jobs):
            directory.mkdir(parents=True)

    def add_codex(self, session_id, **kwargs):
        write_jsonl(self.codex / f"sessions/2026/09/20/rollout-2026-09-20T10-00-00-{session_id}.jsonl",
                    codex_session(session_id, **kwargs))

    def add_job(self, job_id, thread_id, label, model, reasoning, sandbox, exit_code=0):
        path = self.jobs / job_id
        path.mkdir()
        state = {"job_id": job_id, "label": label, "status": "succeeded" if exit_code == 0 else "failed",
                 "cwd": "/repo", "sandbox": sandbox, "reasoning": reasoning, "model": model,
                 "thread_id": thread_id, "created_at": "2026-09-20T10:00:00+00:00",
                 "started_at": "2026-09-20T10:00:00+00:00", "finished_at": "2026-09-20T10:30:00+00:00",
                 "exit_code": exit_code}
        (path / "state.json").write_text(json.dumps(state))
        write_jsonl(path / "events.jsonl", [
            {"type": "thread.started", "thread_id": thread_id},
            {"type": "item.completed", "item": {"type": "command_execution"}},
            {"type": "item.completed", "item": {"type": "file_change"}},
            {"type": "turn.completed", "usage": {"input_tokens": 1000, "cached_input_tokens": 600,
                                                  "cache_write_input_tokens": 0, "output_tokens": 50,
                                                  "reasoning_output_tokens": 10}}])

    def add_claude(self, session_id, **kwargs):
        write_jsonl(self.claude / f"projects/-repo/{session_id}.jsonl", claude_lines(session_id, **kwargs))

    def add_subagent(self, session_id, agent_id, **kwargs):
        write_jsonl(self.claude / f"projects/-repo/{session_id}/subagents/agent-{agent_id}.jsonl",
                    claude_lines(session_id, sidechain=True, agent_id=agent_id, **kwargs))

    def build(self, output, *extra):
        return ledger.main(["build", "-o", str(output), "--job-root", str(self.jobs), "--codex-home",
                            str(self.codex), "--claude-dir", str(self.claude), *extra])


CODEX_USAGE = {"input_tokens": 10_000, "cached_input_tokens": 8_000, "cache_write_input_tokens": 0,
               "output_tokens": 500, "reasoning_output_tokens": 200}
CLAUDE_USAGE = {"input_tokens": 10, "cache_read_input_tokens": 20_000, "cache_creation_input_tokens": 5_000,
                "output_tokens": 300, "output_tokens_details": {"thinking_tokens": 100},
                "cache_creation": {"ephemeral_1h_input_tokens": 5_000, "ephemeral_5m_input_tokens": 0}}


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.fixture = Fixture(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def rows(self, *extra):
        output = Path(self.tmp.name) / "ledger.jsonl"
        self.assertEqual(self.fixture.build(output, *extra), 0)
        return [json.loads(line) for line in output.read_text().splitlines()]

    def test_codex_session_tokens_limits_and_prompt(self):
        self.fixture.add_codex("s1", model="gpt-6-sol", effort="high", sandbox="workspace-write",
                               prompt="Implement the parser and add tests.",
                               usages=[CODEX_USAGE, CODEX_USAGE], limits=[40.0, 41.5])
        (row,) = self.rows()
        self.assertEqual(row["source"], "codex")
        self.assertEqual(row["model"], "gpt-6-sol")
        self.assertEqual(row["effort"], "high")
        self.assertEqual(row["sandbox"], "workspace-write")
        self.assertEqual(row["tokens"], {"input_uncached": 4_000, "cache_read": 16_000, "cache_write": 0,
                                         "output": 1_000, "reasoning": 400, "total": 21_000})
        self.assertEqual(row["limit_meter_delta_pct"], 1.5)
        self.assertEqual(row["plan_type"], "prolite")
        self.assertEqual(row["task_type"], "implementation")
        self.assertTrue(row["prompt_head"].startswith("Implement the parser"))
        self.assertEqual(row["tool_calls"], 2)
        self.assertEqual(row["turns"], 1)
        self.assertEqual(row["duration_s"], 180)
        # 4000*2 + 16000*0.2 + 1000*10 per million
        self.assertAlmostEqual(row["est_cost_usd"], (8_000 + 3_200 + 10_000) / 1e6, places=6)

    def test_limit_reset_mid_run_leaves_pct_blank(self):
        events = codex_session("s2", "gpt-6-luna", "medium", "read-only", "Explore the code.",
                               [CODEX_USAGE, CODEX_USAGE], [90.0, 2.0])
        for event in events:
            if event["type"] == "event_msg" and event["payload"].get("type") == "token_count":
                if event["payload"]["rate_limits"]["primary"]["used_percent"] == 2.0:
                    event["payload"]["rate_limits"]["primary"]["resets_at"] = 1790869104
        write_jsonl(self.fixture.codex / "sessions/2026/09/20/rollout-s2.jsonl", events)
        (row,) = self.rows()
        self.assertIsNone(row["limit_meter_delta_pct"])
        self.assertEqual(row["task_type"], "exploration")

    def test_delegate_job_joins_its_codex_session(self):
        self.fixture.add_codex("thread-a", model="gpt-5.6-sol", effort="high", sandbox="workspace-write",
                               prompt="Wire the new endpoint.", usages=[CODEX_USAGE], limits=[10.0])
        self.fixture.add_job("job-a", "thread-a", "endpoint-wiring", "gpt-5.6-sol", "high", "workspace-write")
        rows = self.rows()
        self.assertEqual(len(rows), 1, "the job and its session must collapse into one row")
        row = rows[0]
        self.assertEqual(row["source"], "delegate-codex")
        self.assertEqual(row["label"], "endpoint-wiring")
        self.assertEqual(row["exit_code"], 0)
        self.assertEqual(row["tokens"]["total"], 10_500)

    def test_job_without_session_file_falls_back_to_events(self):
        self.fixture.add_job("job-b", "thread-missing", "orphan-review", "gpt-6-astra", "xhigh", "read-only", exit_code=1)
        (row,) = self.rows()
        self.assertEqual(row["source"], "delegate-codex")
        self.assertEqual(row["model"], "gpt-6-astra")
        self.assertEqual(row["task_type"], "review")
        self.assertEqual(row["tokens"]["cache_read"], 600)
        self.assertEqual(row["tool_calls"], 2)
        self.assertEqual(row["duration_s"], 1800)
        self.assertEqual(row["exit_code"], 1)

    def test_claude_transcript_dedupes_blocks_and_finds_subagents(self):
        self.fixture.add_claude("sess-1", model="claude-fable-5-1", effort="high",
                                prompt="Review the diff for correctness.", usages=[CLAUDE_USAGE, CLAUDE_USAGE])
        self.fixture.add_subagent("sess-1", "agent1", model="claude-opus-5", effort="medium",
                                  prompt="Find where the config is loaded.", usages=[CLAUDE_USAGE])
        rows = self.rows()
        main = next(row for row in rows if row["source"] == "claude-code")
        sub = next(row for row in rows if row["source"] == "claude-subagent")
        self.assertEqual(main["api_calls"], 2)
        self.assertEqual(main["tokens"], {"input_uncached": 20, "cache_read": 40_000, "cache_write": 10_000,
                                          "output": 600, "reasoning": 200, "total": 50_620})
        self.assertEqual(main["tool_calls"], 2)
        self.assertEqual(main["task_type"], "review")
        self.assertAlmostEqual(main["est_cost_usd"], (20 * 10 + 40_000 * 0.25 + 10_000 * 20 + 600 * 50) / 1e6, places=6)
        self.assertEqual(sub["parent_id"], "sess-1")
        self.assertEqual(sub["id"], "agent1")
        self.assertEqual(sub["model"], "claude-opus-5")
        self.assertEqual(sub["task_type"], "exploration")

    def test_paginated_rollouts_merge_into_one_session(self):
        main = codex_session("s9", "gpt-6-sol", "high", "workspace-write", "Implement the thing.",
                             [CODEX_USAGE], [10.0])
        window = codex_session("s9", "gpt-6-sol", "high", "workspace-write", "internal window prompt",
                               [CODEX_USAGE, CODEX_USAGE], [11.0, 12.0], started="2026-09-20T10:05:00.000Z")
        window[0]["payload"]["thread_source"] = "subagent"
        write_jsonl(self.fixture.codex / "sessions/2026/09/20/rollout-a-s9.jsonl", main)
        write_jsonl(self.fixture.codex / "sessions/2026/09/20/rollout-b-s9x.jsonl", window)
        self.fixture.add_job("job-9", "s9", "merge-me", "gpt-6-sol", "high", "workspace-write")
        (row,) = self.rows()
        self.assertEqual(row["windows"], 2)
        self.assertEqual(row["subagent_windows"], 1)
        self.assertEqual(row["tokens"]["total"], 31_500)
        self.assertEqual(row["tool_calls"], 3)
        self.assertEqual(row["limit_meter_delta_pct"], 2.0)
        self.assertTrue(row["prompt_head"].startswith("Implement the thing"))
        self.assertEqual(row["label"], "merge-me")

    def test_active_time_caps_idle_gaps(self):
        base = datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)
        stamps = [base, base + timedelta(minutes=1), base + timedelta(hours=5), base + timedelta(hours=5, minutes=2)]
        self.assertEqual(ledger.active_seconds(stamps), 60 + 15 * 60 + 120)
        self.assertEqual(ledger.active_seconds([base]), 0)

    def test_copied_claude_transcript_keeps_fullest_copy(self):
        self.fixture.add_claude("sess-2", model="claude-opus-5", effort="high", prompt="Fix the build.",
                                usages=[CLAUDE_USAGE])
        other = self.fixture.claude / "projects/-repo--worktree/sess-2.jsonl"
        write_jsonl(other, claude_lines("sess-2", model="claude-opus-5", effort="high", prompt="Fix the build.",
                                        usages=[CLAUDE_USAGE, CLAUDE_USAGE]))
        (row,) = self.rows()
        self.assertEqual(row["api_calls"], 2)
        self.assertEqual(row["copies"], 2)
        self.assertEqual(row["tokens"]["output"], 600)

    def test_copies_with_different_messages_are_unioned(self):
        first = claude_lines("sess-3", model="claude-opus-5", effort="high", prompt="Fix it.", usages=[CLAUDE_USAGE])
        second = claude_lines("sess-3", model="claude-opus-5", effort="high", prompt="Fix it.", usages=[CLAUDE_USAGE])
        for line in second:
            if line["type"] == "assistant":
                line["message"]["id"] = "msg-other"
        write_jsonl(self.fixture.claude / "projects/-repo/sess-3.jsonl", first)
        write_jsonl(self.fixture.claude / "projects/-repo--wt/sess-3.jsonl", second)
        (row,) = self.rows()
        self.assertEqual(row["api_calls"], 2, "distinct message ids from both copies are kept")
        self.assertEqual(row["turns"], 1, "the same prompt in both copies is one prompt")

    def test_subagent_without_parent_transcript_is_kept(self):
        self.fixture.add_subagent("gone-session", "orphan", model="claude-sonnet-5", effort="low",
                                  prompt="Find the config loader.", usages=[CLAUDE_USAGE])
        (row,) = self.rows()
        self.assertEqual(row["source"], "claude-subagent")
        self.assertEqual(row["parent_id"], "gone-session")
        self.assertEqual(row["id"], "orphan")

    def test_mixed_model_session_is_priced_per_model(self):
        lines = claude_lines("sess-4", model="claude-opus-5", effort="high", prompt="Fix it.",
                             usages=[CLAUDE_USAGE, CLAUDE_USAGE])
        lines[-1]["message"]["model"] = "claude-haiku-4-5"
        lines[-2]["message"]["model"] = "claude-haiku-4-5"
        write_jsonl(self.fixture.claude / "projects/-repo/sess-4.jsonl", lines)
        (row,) = self.rows()
        self.assertEqual(row["models"], ["claude-haiku-4-5", "claude-opus-5"])
        opus = (10 * 5 + 20_000 * 0.5 + 5_000 * 10 + 300 * 25) / 1e6
        haiku = (10 * 1 + 20_000 * 0.1 + 5_000 * 2 + 300 * 5) / 1e6
        self.assertAlmostEqual(row["est_cost_usd"], round(opus + haiku, 4), places=4)

    def test_resumed_thread_keeps_first_label_and_last_outcome(self):
        self.fixture.add_codex("thread-r", model="gpt-6-sol", effort="high", sandbox="workspace-write",
                               prompt="Implement it.", usages=[CODEX_USAGE], limits=[1.0])
        self.fixture.add_job("job-r1", "thread-r", "first-attempt", "gpt-6-sol", "high", "workspace-write", exit_code=1)
        self.fixture.add_job("job-r2", "thread-r", "retry-with-feedback", "gpt-6-sol", "high", "workspace-write")
        (self.fixture.jobs / "job-r2/state.json").write_text(json.dumps(
            json.loads((self.fixture.jobs / "job-r2/state.json").read_text()) | {"created_at": "2026-09-20T11:00:00+00:00"}))
        (row,) = self.rows()
        self.assertEqual(row["label"], "first-attempt")
        self.assertEqual(row["exit_code"], 0)
        self.assertEqual(row["resumes"], 1)
        self.assertEqual(row["job_ids"], ["job-r1", "job-r2"])
        self.assertEqual(row["tokens"]["total"], 10_500, "usage comes from the rollout once, not from both jobs' events")

    def test_bad_dates_and_missing_ledgers_fail_loudly(self):
        with self.assertRaises(SystemExit):
            ledger.main(["build", "-o", str(Path(self.tmp.name) / "x.jsonl"), "--since", "yesterday",
                         "--job-root", str(self.fixture.jobs), "--codex-home", str(self.fixture.codex),
                         "--claude-dir", str(self.fixture.claude)])
        with self.assertRaises(SystemExit):
            ledger.main(["query", str(Path(self.tmp.name) / "does-not-exist.jsonl")])

    def test_codex_subagent_records_parent(self):
        source = {"subagent": {"thread_spawn": {"parent_thread_id": "parent-1", "agent_nickname": "Newton"}}}
        self.fixture.add_codex("child-1", model="gpt-6-sol", effort="medium", sandbox="read-only",
                               prompt="Summarise the tests.", usages=[CODEX_USAGE], limits=[5.0],
                               source=source)
        (row,) = self.rows()
        self.assertEqual(row["originator"], "codex_subagent")
        self.assertEqual(row["parent_id"], "parent-1")
        self.assertEqual(row["agent_name"], "Newton")

    def test_build_filters_by_date_and_size(self):
        self.fixture.add_codex("s1", model="gpt-6-sol", effort="low", sandbox="read-only",
                               prompt="Explain the build.", usages=[CODEX_USAGE], limits=[1.0])
        self.assertEqual(len(self.rows("--since", "2026-09-21")), 0)
        self.assertEqual(len(self.rows("--until", "2026-09-19")), 0)
        self.assertEqual(len(self.rows("--since", "2026-09-20", "--until", "2026-09-20")), 1)
        self.assertEqual(len(self.rows("--min-tokens", "99999")), 0)

    def test_query_filters_and_groups(self):
        self.fixture.add_codex("s1", model="gpt-6-sol", effort="high", sandbox="workspace-write",
                               prompt="Implement it.", usages=[CODEX_USAGE], limits=[1.0])
        self.fixture.add_codex("s2", model="gpt-5.6-sol", effort="high", sandbox="workspace-write",
                               prompt="Implement it again.", usages=[CODEX_USAGE, CODEX_USAGE], limits=[1.0, 2.0])
        self.fixture.add_claude("c1", model="claude-fable-5-1", effort="high", prompt="Review this.",
                                usages=[CLAUDE_USAGE])
        output = Path(self.tmp.name) / "ledger.jsonl"
        self.fixture.build(output)
        result = subprocess.run([sys.executable, str(SCRIPT), "query", str(output), "--task-type", "implementation",
                                 "--model", "gpt-6-sol", "--format", "csv"], capture_output=True, text=True, check=True)
        lines = result.stdout.strip().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("gpt-6-sol", lines[1])
        result = subprocess.run([sys.executable, str(SCRIPT), "query", str(output), "--min-tokens", "20000",
                                 "--group-by", "task_type,model"], capture_output=True, text=True, check=True)
        self.assertIn("| implementation | gpt-5.6-sol | 1 |", result.stdout)
        self.assertIn("| review | claude-fable-5-1 | 1 |", result.stdout)
        self.assertNotIn("gpt-6-sol", result.stdout)
        result = subprocess.run([sys.executable, str(SCRIPT), "query", str(output), "--group-by", "colour"],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)

    def test_report_compares_snapshots(self):
        self.fixture.add_codex("s1", model="gpt-5.6-sol", effort="high", sandbox="workspace-write",
                               prompt="Implement it.", usages=[CODEX_USAGE], limits=[1.0])
        before = Path(self.tmp.name) / "before.jsonl"
        self.fixture.build(before)
        after_rows = [json.loads(line) for line in before.read_text().splitlines()]
        after_rows[0]["model"] = "gpt-6-sol"
        after_rows[0]["snapshot"] = "after"
        after = Path(self.tmp.name) / "after.jsonl"
        write_jsonl(after, after_rows)
        result = subprocess.run([sys.executable, str(SCRIPT), "report", str(before), str(after)],
                                capture_output=True, text=True, check=True)
        self.assertIn("2 snapshot(s): after, before", result.stdout)
        self.assertIn("| implementation | after | gpt-6-sol | high | 1 |", result.stdout)
        self.assertIn("| implementation | before | gpt-5.6-sol | high | 1 |", result.stdout)
        self.assertIn("## How to read this ledger", result.stdout)

    def test_classify_and_normalize(self):
        self.assertEqual(ledger.classify("Please add a flag", "read-only"), "implementation")
        self.assertEqual(ledger.classify("Second opinion on this design", None), "review")
        self.assertEqual(ledger.classify(None, "read-only"), "exploration")
        self.assertEqual(ledger.classify(None, None, label="db-migration-fix"), "implementation")
        self.assertEqual(ledger.classify(None, None, label="net-probe"), "other")
        self.assertEqual(ledger.classify("How does the cache work?", "workspace-write"), "exploration")
        self.assertEqual(ledger.normalize_model("claude-opus-5-5[1m]"), "claude-opus-5-5")
        self.assertEqual(ledger.normalize_model("claude-sonnet-4-6-20260101"), "claude-sonnet-4-6")
        self.assertEqual(ledger.normalize_model("gpt-6-sol-2026-09-22"), "gpt-6-sol")
        self.assertEqual(ledger.normalize_model("mystery-model"), "mystery-model")
        self.assertIsNone(ledger.cost_usd("mystery-model", ledger.empty_tokens()))


if __name__ == "__main__":
    unittest.main()
