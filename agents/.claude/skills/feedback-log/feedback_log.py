#!/usr/bin/env python3
"""Append-only log of feedback on agent sessions: what went wrong and what went well.

  feedback_log.py add --kind K --summary S --user-said Q [--what-happened W]
                      [--why W] [--lesson L] [--cost X]
  feedback_log.py list [--days N] [--project P] [--kind K] [--all]
  feedback_log.py show ID
  feedback_log.py resolve ID --note N

Entries go to ~/.claude/feedback-log/YYYY-MM.jsonl (override with FEEDBACK_LOG_DIR).
`add` records the session context itself: time, cwd, git repo and branch, the
Claude session id and transcript path, the T3 thread, and an excerpt of the last
few messages, because Claude Code prunes transcripts after about 30 days.
"""
import argparse, glob, json, os, re, sqlite3, subprocess, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

LOG_DIR = Path(os.environ.get("FEEDBACK_LOG_DIR", Path.home() / ".claude" / "feedback-log"))
PROBLEMS = ["redo", "approach", "assumption", "ignored-instruction", "tool-failure", "quality"]
KINDS = PROBLEMS + ["win"]
SECRET = re.compile(
    r"(AKIA[0-9A-Z]{16}|gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9_-]{20,}|xox[abp]-[A-Za-z0-9-]+"
    r"|(?i:bearer|basic)\s+[A-Za-z0-9._~+/=-]{8,}|://[^/\s:@]+:[^/\s@]+@|(?i:x-amz-signature|sig|signature)=[^&\s]+"
    r"|(?i:(password|passwd|secret|token|api[_-]?key)\s*[=:]\s*)\S+)"
)


def redact(text):
    return SECRET.sub("[REDACTED]", text or "")


def clip(text, n):
    text = redact(text).strip()
    return text if len(text) <= n else text[:n] + " …"


def git(cwd, *args):
    try:
        out = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None if out.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired):
        return None


def transcript_path(session_id):
    if not session_id:
        return None
    hits = glob.glob(str(Path.home() / ".claude" / "projects" / "*" / f"{session_id}.jsonl"))
    return hits[0] if hits else None


def t3_thread(session_id):
    db = Path.home() / ".t3" / "userdata" / "state.sqlite"
    if not session_id or not db.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=5)
        row = con.execute(
            "SELECT t.thread_id, t.title FROM provider_session_runtime r "
            "JOIN projection_threads t ON t.thread_id = r.thread_id "
            "WHERE r.resume_cursor_json LIKE ? LIMIT 1",
            (f'%"{session_id}"%',),
        ).fetchone()
        return {"id": row[0], "title": row[1]} if row else None
    except sqlite3.Error:
        return None


def excerpt(path, per_role=3):
    """The last few user messages, assistant replies, tool calls and tool errors, in order."""
    if not path:
        return []
    items = []
    try:
        with open(path, errors="replace") as fh:
            for raw in fh:
                try:
                    e = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(e, dict) or e.get("type") not in ("user", "assistant") or e.get("isMeta"):
                    continue
                role = e["type"]
                msg = e.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
                for b in blocks if isinstance(blocks, list) else []:
                    if not isinstance(b, dict):
                        continue
                    if b.get("type") == "text" and isinstance(b.get("text"), str) and b["text"].strip():
                        text = b["text"]
                        if text.startswith(("<system-reminder>", "<task-notification", "<local-command")):
                            continue
                        items.append({"role": role, "text": clip(text, 600)})
                    elif b.get("type") == "tool_use":
                        # Name and target only: a command or payload can carry a secret.
                        inp = b.get("input") if isinstance(b.get("input"), dict) else {}
                        target = inp.get("description") or inp.get("file_path") or ""
                        items.append({"role": "tool", "text": clip(f"{b.get('name')} {target}", 200)})
                    elif b.get("type") == "tool_result" and b.get("is_error"):
                        c = b.get("content")
                        c = " ".join(x.get("text", "") for x in c if isinstance(x, dict)) if isinstance(c, list) else str(c)
                        items.append({"role": "tool-error", "text": clip(c, 300)})
    except OSError:
        return []
    keep = set()
    for role in ("user", "assistant", "tool", "tool-error"):
        keep.update([i for i, it in enumerate(items) if it["role"] == role][-per_role:])
    return [items[i] for i in sorted(keep)]


def read_all():
    entries, resolutions = {}, {}
    for f in sorted(LOG_DIR.glob("*.jsonl")):
        for n, raw in enumerate(f.open(), 1):
            try:
                e = json.loads(raw)
            except ValueError:
                e = None
            if not isinstance(e, dict) or "id" not in e or "at" not in e:
                print(f"skipping malformed line {f}:{n}", file=sys.stderr)
                continue
            if e.get("type") == "resolve":
                resolutions[e["id"]] = e
            elif "kind" in e:
                entries[e["id"]] = e
    for i, r in resolutions.items():
        if i in entries:
            entries[i]["resolved"] = {"at": r["at"], "note": r["note"]}
    return list(entries.values())


def append(record):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    path = LOG_DIR / f"{datetime.now(timezone.utc):%Y-%m}.jsonl"
    with path.open("a") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def cmd_add(a):
    cwd = os.getcwd()
    sid = a.session or os.environ.get("CLAUDE_CODE_SESSION_ID")
    tpath = transcript_path(sid)
    root = git(cwd, "rev-parse", "--show-toplevel")
    record = {
        "id": uuid.uuid4().hex[:8],
        "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "kind": a.kind,
        "summary": redact(a.summary),
        "user_said": redact(a.user_said),
        "what_happened": redact(a.what_happened),
        "why": redact(a.why),
        "lesson": redact(a.lesson),
        "cost": redact(a.cost),
        "project": {
            "cwd": cwd,
            "repo": root,
            "branch": git(cwd, "rev-parse", "--abbrev-ref", "HEAD") if root else None,
            "head": git(cwd, "rev-parse", "--short", "HEAD") if root else None,
        },
        "session": {"id": sid, "transcript": tpath, "t3_thread": t3_thread(sid)},
        "excerpt": excerpt(tpath),
    }
    path = append(record)
    print(f"logged {record['id']} to {path}")


def cmd_list(a):
    since = datetime.now(timezone.utc) - timedelta(days=a.days)
    rows = [
        e for e in read_all()
        if datetime.fromisoformat(e["at"]) >= since
        and (a.all or "resolved" not in e)
        and (not a.kind or e["kind"] == a.kind or (a.kind == "problems" and e["kind"] in PROBLEMS))
        and (not a.project or any(a.project in (v or "") for v in (e.get("project") or {}).values()))
    ]
    for e in sorted(rows, key=lambda e: e["at"]):
        proj = e.get("project") or {}
        where = Path(proj.get("repo") or proj.get("cwd") or "?").name
        done = "resolved" in e
        state = ("kept" if done else "new") if e["kind"] == "win" else ("resolved" if done else "open")
        print(f"{e['id']}  {e['at'][:16]}  {state:8}  {e['kind']:19}  {where:20}  {e.get('summary', '')}")
    print(f"{len(rows)} entries", file=sys.stderr)


def cmd_show(a):
    for e in read_all():
        if e["id"] == a.id:
            print(json.dumps(e, indent=2, ensure_ascii=False))
            return
    sys.exit(f"no entry {a.id}")


def cmd_resolve(a):
    entry = next((e for e in read_all() if e["id"] == a.id), None)
    if not entry:
        sys.exit(f"no entry {a.id}")
    if "resolved" in entry:
        sys.exit(f"{a.id} already resolved: {entry['resolved']['note']}")
    append({"type": "resolve", "id": a.id, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "note": a.note})
    print(f"resolved {a.id}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    add = sub.add_parser("add")
    add.add_argument("--kind", required=True, choices=KINDS)
    add.add_argument("--summary", required=True, help="one line: what went wrong, or what went well")
    add.add_argument("--user-said", default="", help="the user's words, quoted")
    add.add_argument("--what-happened", default="", help="what the agent did")
    add.add_argument("--why", default="", help="root cause, or why it worked")
    add.add_argument("--lesson", default="", help="the instruction or tool change to make, or the practice to keep")
    add.add_argument("--cost", default="", help="for problems, rough waste: turns, tool calls, minutes")
    add.add_argument("--session", help="session id (default: $CLAUDE_CODE_SESSION_ID)")
    ls = sub.add_parser("list")
    ls.add_argument("--days", type=int, default=30)
    ls.add_argument("--project")
    ls.add_argument("--kind", choices=KINDS + ["problems"], help="a kind, or `problems` for everything but wins")
    ls.add_argument("--all", action="store_true", help="include resolved entries")
    show = sub.add_parser("show")
    show.add_argument("id")
    res = sub.add_parser("resolve")
    res.add_argument("id")
    res.add_argument("--note", required=True, help="what was done about it, e.g. the rule and the file it went into")
    a = p.parse_args()
    {"add": cmd_add, "list": cmd_list, "show": cmd_show, "resolve": cmd_resolve}[a.cmd](a)


if __name__ == "__main__":
    main()
