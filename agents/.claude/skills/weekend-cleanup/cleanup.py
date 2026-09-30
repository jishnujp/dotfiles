#!/usr/bin/env python3
"""Survey and remove finished T3 worktrees; audit Claude memory directories.

  cleanup.py worktrees          report every worktree of every T3 project with a verdict
  cleanup.py worktrees --apply  stash dirty work, stop stale processes, remove REMOVE rows
  cleanup.py memory             report index/link problems and entry ages per memory dir

Read-only unless --apply is given. Stdlib only.
"""

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

HOME = Path.home()
T3_DB = HOME / ".t3/userdata/state.sqlite"
T3_WORKTREES = HOME / ".t3/worktrees"
MEMORY_ROOT = HOME / ".claude/projects"
STALE_PROCESS_HOURS = 24
STASH_LABEL = f"worktree-cleanup {date.today().isoformat()}"


def run(cmd, cwd=None, timeout=60):
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return 1, ""
    return r.returncode, r.stdout.strip()


# ---------- facts ----------

def t3_projects_and_threads():
    """Project roots, and thread states keyed by worktree path ('active' or 'settled')."""
    if not T3_DB.exists():
        return [], {}
    db = sqlite3.connect(f"file:{T3_DB}?mode=ro", uri=True)
    roots = [r[0] for r in db.execute(
        "select workspace_root from projection_projects where deleted_at is null")]
    threads = {}
    for path, title, archived, deleted, settled_at, unsettled_at, override in db.execute(
            "select worktree_path, title, archived_at, deleted_at, settled_at, unsettled_at,"
            " settled_override from projection_threads where worktree_path is not null"):
        settled = bool(archived or deleted or override == "settled"
                       or (settled_at and not (unsettled_at and unsettled_at > settled_at)))
        threads.setdefault(path, []).append({"title": title, "settled": settled})
    return roots, threads


def compose_dirs():
    """Map compose working_dir -> set of compose project names, from running containers."""
    fmt = '{{.Label "com.docker.compose.project"}}\t{{.Label "com.docker.compose.project.working_dir"}}'
    code, out = run(["docker", "ps", "--format", fmt], timeout=30)
    if code != 0:
        code, out = run(["sg", "docker", "-c", f"docker ps --format '{fmt}'"], timeout=30)
    dirs = {}
    for line in out.splitlines():
        if "\t" in line:
            proj, wd = line.split("\t", 1)
            if wd:
                dirs.setdefault(wd, set()).add(proj)
    return dirs


def processes():
    """(pid, age_hours, cwd, cmdline) for every readable process."""
    boot = time.time() - float(Path("/proc/uptime").read_text().split()[0])
    hz = os.sysconf("SC_CLK_TCK")
    out = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit() or int(p.name) == os.getpid():
            continue
        try:
            cwd = os.readlink(p / "cwd")
            cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            start = int((p / "stat").read_text().rsplit(")", 1)[1].split()[19]) / hz
        except OSError:
            continue
        out.append((int(p.name), (time.time() - boot - start) / 3600, cwd, cmd))
    return out


def pr_info(repo, branch):
    code, out = run(["gh", "pr", "list", "--head", branch, "--state", "all",
                     "--json", "number,state,headRefOid"], cwd=repo, timeout=45)
    return json.loads(out) if code == 0 and out else []


@dataclass
class Worktree:
    path: str
    repo: str
    branch: str | None
    head: str
    dirty: int = 0
    head_reachable: bool = False
    prs: list = field(default_factory=list)
    threads: list = field(default_factory=list)
    compose: list = field(default_factory=list)
    procs: list = field(default_factory=list)  # (pid, age_hours, cmd)
    verdict: str = ""
    reason: str = ""


def list_worktrees(repo):
    code, out = run(["git", "-C", repo, "worktree", "list", "--porcelain"])
    if code != 0:
        return []
    items, cur = [], {}
    for line in out.splitlines() + [""]:
        if not line:
            if cur:
                items.append(cur)
            cur = {}
        elif " " in line:
            k, v = line.split(" ", 1)
            cur[k] = v
        else:
            cur[line] = True
    return items[1:]  # the first entry is the main checkout


# ---------- verdict ----------

def decide(wt, under_t3):
    """Set wt.verdict to REMOVE, BLOCKED, REVIEW or KEEP with a one-line reason."""
    merged = [p for p in wt.prs if p["state"] == "MERGED"]
    open_prs = [p for p in wt.prs if p["state"] == "OPEN"]
    settled = bool(wt.threads) and all(t["settled"] for t in wt.threads)
    if not under_t3:
        return "KEEP", "outside ~/.t3/worktrees; not managed here"
    if open_prs:
        return "KEEP", f"open PR #{open_prs[0]['number']}"
    if merged:
        if not any(p["headRefOid"] == wt.head for p in merged) and wt.head_reachable is False:
            return "REVIEW", f"PR #{merged[0]['number']} merged but HEAD has commits after it"
        why = f"PR #{merged[0]['number']} merged"
    elif settled:
        why = "T3 thread settled"
    elif not wt.threads and wt.branch is None and wt.head_reachable:
        why = "detached, no thread, HEAD is on another branch"
    elif wt.threads:
        return "KEEP", "active T3 thread"
    else:
        return "REVIEW", "no T3 thread and no PR"
    if wt.compose:
        return "BLOCKED", f"{why}; compose project {', '.join(wt.compose)} runs from it"
    live = [p for p in wt.procs if p[1] < STALE_PROCESS_HOURS]
    if live:
        return "BLOCKED", f"{why}; {len(live)} live process(es), e.g. pid {live[0][0]}"
    stash = f"; stash {wt.dirty} dirty file(s)" if wt.dirty else ""
    stale = f"; stop {len(wt.procs)} stale process(es)" if wt.procs else ""
    return "REMOVE", why + stash + stale


def survey():
    roots, threads = t3_projects_and_threads()
    compose = compose_dirs()
    procs = processes()
    result, registered = [], set()
    for repo in roots:
        if not (Path(repo) / ".git").exists():
            continue
        run(["git", "-C", repo, "fetch", "-q", "--prune", "origin"], timeout=90)
        for item in list_worktrees(repo):
            path = item["worktree"]
            registered.add(path)
            branch = item.get("branch", "").removeprefix("refs/heads/") or None
            wt = Worktree(path=path, repo=repo, branch=branch, head=item.get("HEAD", ""))
            if not Path(path).exists():
                wt.verdict, wt.reason = "REMOVE", "directory already gone (prune)"
                result.append(wt)
                continue
            _, st = run(["git", "-C", path, "status", "--porcelain"])
            wt.dirty = len(st.splitlines())
            # reachable from a remote branch, or from another local branch when detached
            _, refs = run(["git", "-C", path, "for-each-ref", "--contains", wt.head,
                           "--format=%(refname)", "refs/remotes"])
            wt.head_reachable = bool(refs)
            if branch is None and not refs:
                _, refs = run(["git", "-C", path, "branch", "--contains", wt.head])
                wt.head_reachable = bool(refs)
            wt.prs = pr_info(repo, branch) if branch else []
            wt.threads = threads.get(path, [])
            wt.compose = sorted(p for d, ps in compose.items()
                                if d == path or d.startswith(path + "/") for p in ps)
            wt.procs = [(pid, age, cmd[:90]) for pid, age, cwd, cmd in procs
                        if cwd == path or cwd.startswith(path + "/") or path + "/" in cmd]
            under = Path(path).is_relative_to(T3_WORKTREES)
            wt.verdict, wt.reason = decide(wt, under)
            result.append(wt)
    orphans = [str(d) for proj in T3_WORKTREES.glob("*") for d in proj.glob("*")
               if d.is_dir() and str(d) not in registered] if T3_WORKTREES.exists() else []
    return result, orphans


def apply(result):
    for wt in result:
        if wt.verdict != "REMOVE":
            continue
        if not Path(wt.path).exists():
            run(["git", "-C", wt.repo, "worktree", "prune"])
            print(f"pruned   {wt.path}")
            continue
        for pid, age, cmd in wt.procs:
            try:
                os.kill(pid, 15)
            except ProcessLookupError:
                pass
        if wt.procs:
            time.sleep(2)
            for pid, _, _ in wt.procs:
                if Path(f"/proc/{pid}").exists():
                    os.kill(pid, 9)
        if wt.dirty:
            label = f"{STASH_LABEL}: uncommitted work from {Path(wt.path).name} ({wt.branch or wt.head[:8]})"
            code, _ = run(["git", "-C", wt.path, "stash", "push", "-u", "-q", "-m", label])
            _, left = run(["git", "-C", wt.path, "status", "--porcelain"])
            if code != 0 or left:
                print(f"SKIPPED  {wt.path}: stash failed, left in place")
                continue
            print(f"stashed  {wt.path} -> '{label}' in {wt.repo}")
        code, _ = run(["git", "-C", wt.repo, "worktree", "remove", "--force", wt.path], timeout=300)
        print(("removed  " if code == 0 else "FAILED   ") + wt.path)
    for repo in {wt.repo for wt in result}:
        run(["git", "-C", repo, "worktree", "prune"])


def cmd_worktrees(args):
    result, orphans = survey()
    order = {"REMOVE": 0, "BLOCKED": 1, "REVIEW": 2, "KEEP": 3}
    for wt in sorted(result, key=lambda w: (order[w.verdict], w.path)):
        titles = "; ".join(t["title"] for t in wt.threads)[:60]
        print(f"{wt.verdict:8} {wt.path}\n         branch={wt.branch or 'DETACHED'} dirty={wt.dirty}"
              f" | {wt.reason}" + (f" | thread: {titles}" if titles else ""))
        for pid, age, cmd in wt.procs:
            print(f"         proc {pid} age {age:.0f}h: {cmd}")
    for o in orphans:
        print(f"ORPHAN   {o} (directory not registered as a git worktree; check, then rm by hand)")
    if args.apply:
        print("\n--- applying REMOVE rows ---")
        apply(result)
        _, df = run(["df", "-h", str(HOME)])
        print(df.splitlines()[-1] if df else "")


# ---------- memory ----------

LINK = re.compile(r"\[\[([^\]]+)\]\]")
INDEX_ENTRY = re.compile(r"\]\(([^)]+\.md)\)")


def audit_memory(mem):
    """Problems and per-file facts for one memory directory."""
    index = mem / "MEMORY.md"
    files = {p.name for p in mem.glob("*.md") if p.name != "MEMORY.md"}
    listed = set(INDEX_ENTRY.findall(index.read_text())) if index.exists() else set()
    problems = [f"index lists missing file {f}" for f in sorted(listed - files)]
    problems += [f"file not in index: {f}" for f in sorted(files - listed)]
    names = {f[:-3] for f in files}
    for f in sorted(files):
        for link in sorted(set(LINK.findall((mem / f).read_text()))):
            if link not in names:
                problems.append(f"{f}: dangling link [[{link}]]")
    rows = []
    for f in sorted(files):
        p = mem / f
        text = p.read_text()
        typ = re.search(r"^\s*type:\s*(\S+)", text, re.M)
        rows.append((f, typ.group(1) if typ else "?", int((time.time() - p.stat().st_mtime) / 86400),
                     len(text)))
    size = index.stat().st_size if index.exists() else 0
    return problems, rows, size


def cmd_memory(args):
    dirs = [d for d in sorted(MEMORY_ROOT.glob("*/memory")) if (d / "MEMORY.md").exists()]
    for mem in dirs:
        problems, rows, size = audit_memory(mem)
        print(f"== {mem}  (MEMORY.md {size} bytes, {len(rows)} entries)")
        for p in problems:
            print(f"   PROBLEM {p}")
        for f, typ, age, n in sorted(rows, key=lambda r: -r[2]):
            print(f"   {age:3d}d  {typ:9} {n:6d}B  {f}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("worktrees")
    w.add_argument("--apply", action="store_true", help="stash, stop stale processes, remove REMOVE rows")
    w.set_defaults(fn=cmd_worktrees)
    sub.add_parser("memory").set_defaults(fn=cmd_memory)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
