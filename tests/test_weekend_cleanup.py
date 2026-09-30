"""Unit tests for the weekend-cleanup verdict rules and memory audit."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "agents/.claude/skills/weekend-cleanup/cleanup.py"
spec = importlib.util.spec_from_file_location("cleanup", SCRIPT)
cleanup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cleanup)


def wt(**kw):
    base = dict(path="/w", repo="/r", branch="b", head="abc", head_reachable=True)
    base.update(kw)
    return cleanup.Worktree(**base)


MERGED = [{"number": 7, "state": "MERGED", "headRefOid": "abc"}]


class Decide(unittest.TestCase):
    def verdict(self, w, under=True):
        return cleanup.decide(w, under)[0]

    def test_merged_pr_is_removed(self):
        self.assertEqual(self.verdict(wt(prs=MERGED)), "REMOVE")

    def test_settled_thread_is_removed(self):
        self.assertEqual(self.verdict(wt(threads=[{"title": "t", "settled": True}])), "REMOVE")

    def test_active_thread_is_kept(self):
        self.assertEqual(self.verdict(wt(threads=[{"title": "t", "settled": False}])), "KEEP")

    def test_one_active_thread_keeps_a_shared_worktree(self):
        threads = [{"title": "a", "settled": True}, {"title": "b", "settled": False}]
        self.assertEqual(self.verdict(wt(threads=threads)), "KEEP")

    def test_open_pr_is_kept(self):
        self.assertEqual(self.verdict(wt(prs=[{"number": 8, "state": "OPEN", "headRefOid": "abc"}])), "KEEP")

    def test_outside_t3_is_kept(self):
        self.assertEqual(self.verdict(wt(prs=MERGED), under=False), "KEEP")

    def test_compose_stack_blocks(self):
        self.assertEqual(self.verdict(wt(prs=MERGED, compose=["maatprod"])), "BLOCKED")

    def test_young_process_blocks_but_stale_one_does_not(self):
        self.assertEqual(self.verdict(wt(prs=MERGED, procs=[(1, 2.0, "bash")])), "BLOCKED")
        self.assertEqual(self.verdict(wt(prs=MERGED, procs=[(1, 100.0, "pytest")])), "REMOVE")

    def test_unpushed_commits_after_merge_need_review(self):
        self.assertEqual(self.verdict(wt(prs=MERGED, head="def", head_reachable=False)), "REVIEW")

    def test_no_thread_no_pr_needs_review(self):
        self.assertEqual(self.verdict(wt()), "REVIEW")

    def test_detached_copy_on_another_branch_is_removed(self):
        self.assertEqual(self.verdict(wt(branch=None)), "REMOVE")


class MemoryAudit(unittest.TestCase):
    def test_reports_missing_unindexed_and_dangling(self):
        with tempfile.TemporaryDirectory() as d:
            mem = Path(d)
            (mem / "MEMORY.md").write_text("- [A](a.md) — x\n- [Gone](gone.md) — y\n")
            (mem / "a.md").write_text("---\nmetadata:\n  type: project\n---\nsee [[b]] and [[nope]]\n")
            (mem / "b.md").write_text("---\nmetadata:\n  type: feedback\n---\nbody\n")
            problems, rows, _ = cleanup.audit_memory(mem)
        self.assertIn("index lists missing file gone.md", problems)
        self.assertIn("file not in index: b.md", problems)
        self.assertIn("a.md: dangling link [[nope]]", problems)
        self.assertNotIn("a.md: dangling link [[b]]", problems)
        self.assertEqual({r[0]: r[1] for r in rows}, {"a.md": "project", "b.md": "feedback"})


if __name__ == "__main__":
    unittest.main()
