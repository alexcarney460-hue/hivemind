#!/usr/bin/env python3
"""Hivemind Daemon — persistent autonomous Claude agent.

Runs as a background process. Watches for:
  1. Scheduled tasks (cron-like)
  2. File changes (file watchers)
  3. Message bus triggers (agent-to-agent)
  4. Webhook triggers (external events)

When triggered, spawns a Claude Code session to handle the task.
Claude dies when done. Daemon lives forever.
"""

import sqlite3
import subprocess
import time
import os
import sys
import json
import signal
import hashlib
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = os.path.expanduser("~/hivemind.db")
CLAUDE_BIN = "claude"
POLL_INTERVAL = 30  # seconds
LOG_DIR = os.path.expanduser("~/.openclaw/workspace/hivemind-logs")
PID_FILE = os.path.expanduser("~/hivemind.pid")

# File watcher state
_file_hashes = {}


def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    logfile = os.path.join(LOG_DIR, datetime.now().strftime("%Y-%m-%d.log"))
    with open(logfile, "a") as f:
        f.write(line + "\n")


def get_db():
    return sqlite3.connect(DB_PATH, timeout=10)


def spawn_claude(prompt, working_dir=None, task_id=None):
    """Spawn a Claude Code session to handle a task."""
    log(f"Spawning Claude for task {task_id}: {prompt[:80]}...")

    cwd = working_dir or os.path.expanduser("~/.openclaw/workspace")

    try:
        # Mark task as running
        if task_id:
            conn = get_db()
            conn.execute(
                "UPDATE tasks SET status='running', started_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,)
            )
            conn.commit()
            conn.close()

        # Run Claude in non-interactive mode
        result = subprocess.run(
            [CLAUDE_BIN, "-p", prompt, "--allowedTools", "*"],
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=600,  # 10 minute max per task
            env={**os.environ, "HIVEMIND_TASK_ID": str(task_id or "")}
        )

        output = result.stdout[-2000:] if result.stdout else ""
        error = result.stderr[-1000:] if result.stderr else ""

        if task_id:
            conn = get_db()
            conn.execute(
                """UPDATE tasks SET
                    status=?, result=?, error=?, completed_at=CURRENT_TIMESTAMP
                WHERE id=?""",
                ("done" if result.returncode == 0 else "failed", output, error, task_id)
            )
            # Log result to message bus
            conn.execute(
                """INSERT INTO messages (sender, channel, content, msg_type)
                VALUES (?, 'daemon', ?, ?)""",
                (
                    f"daemon:task:{task_id}",
                    f"Task '{prompt[:50]}' {'completed' if result.returncode == 0 else 'failed'}:\n{output[:500]}",
                    "result" if result.returncode == 0 else "error"
                )
            )
            conn.commit()
            conn.close()

        log(f"Task {task_id} {'completed' if result.returncode == 0 else 'failed'}")
        return result.returncode == 0

    except subprocess.TimeoutExpired:
        log(f"Task {task_id} timed out after 600s")
        if task_id:
            conn = get_db()
            conn.execute(
                "UPDATE tasks SET status='timeout', error='Timed out after 600s', completed_at=CURRENT_TIMESTAMP WHERE id=?",
                (task_id,)
            )
            conn.commit()
            conn.close()
        return False

    except Exception as e:
        log(f"Task {task_id} error: {e}")
        if task_id:
            conn = get_db()
            conn.execute(
                "UPDATE tasks SET status='error', error=?, completed_at=CURRENT_TIMESTAMP WHERE id=?",
                (str(e), task_id)
            )
            conn.commit()
            conn.close()
        return False


def check_pending_tasks():
    """Check for pending manual/triggered tasks."""
    conn = get_db()
    tasks = conn.execute(
        "SELECT id, name, prompt, working_dir FROM tasks WHERE status='pending' AND trigger_type='manual' ORDER BY priority DESC, created_at ASC LIMIT 1"
    ).fetchall()
    conn.close()

    for task_id, name, prompt, working_dir in tasks:
        spawn_claude(prompt, working_dir, task_id)


def check_cron_tasks():
    """Check for cron-scheduled tasks that are due."""
    conn = get_db()
    tasks = conn.execute(
        """SELECT id, name, prompt, working_dir, cron_schedule
        FROM tasks
        WHERE trigger_type='cron' AND status != 'running'
            AND (next_run IS NULL OR next_run <= CURRENT_TIMESTAMP)
        ORDER BY priority DESC LIMIT 1"""
    ).fetchall()
    conn.close()

    for task_id, name, prompt, working_dir, cron_schedule in tasks:
        spawn_claude(prompt, working_dir, task_id)
        # Schedule next run (simple: add interval in minutes from cron_schedule)
        try:
            minutes = int(cron_schedule)
            conn = get_db()
            conn.execute(
                "UPDATE tasks SET status='pending', next_run=datetime('now', ?||' minutes') WHERE id=?",
                (str(minutes), task_id)
            )
            conn.commit()
            conn.close()
        except (ValueError, TypeError):
            pass


def check_file_watches():
    """Check watched files for changes."""
    conn = get_db()
    watches = conn.execute(
        "SELECT id, path, pattern, task_id, prompt FROM watches WHERE active=1"
    ).fetchall()
    conn.close()

    for watch_id, path, pattern, task_id, prompt in watches:
        try:
            p = Path(path)
            if not p.exists():
                continue

            # Hash the file/directory state
            if p.is_file():
                current_hash = hashlib.md5(p.read_bytes()).hexdigest()
            elif p.is_dir():
                contents = sorted(p.glob(pattern or "*"))
                hash_input = "".join(f"{f.name}:{f.stat().st_mtime}" for f in contents[:100])
                current_hash = hashlib.md5(hash_input.encode()).hexdigest()
            else:
                continue

            prev_hash = _file_hashes.get(watch_id)
            _file_hashes[watch_id] = current_hash

            if prev_hash and prev_hash != current_hash:
                log(f"File watch triggered: {path}")
                task_prompt = prompt or f"Files changed at {path}. Review and take appropriate action."
                conn = get_db()
                conn.execute(
                    """INSERT INTO tasks (name, prompt, trigger_type, status)
                    VALUES (?, ?, 'file_watch', 'pending')""",
                    (f"watch:{path}", task_prompt)
                )
                conn.execute(
                    "UPDATE watches SET last_triggered=CURRENT_TIMESTAMP WHERE id=?",
                    (watch_id,)
                )
                conn.commit()
                conn.close()

        except Exception as e:
            log(f"File watch error for {path}: {e}")


def check_message_triggers():
    """Check for messages that should trigger tasks."""
    conn = get_db()
    messages = conn.execute(
        """SELECT id, sender, content FROM messages
        WHERE msg_type='task_request' AND read_at IS NULL
        ORDER BY priority DESC, created_at ASC LIMIT 3"""
    ).fetchall()

    for msg_id, sender, content in messages:
        conn.execute("UPDATE messages SET read_at=CURRENT_TIMESTAMP WHERE id=?", (msg_id,))
        conn.execute(
            """INSERT INTO tasks (name, prompt, trigger_type, status)
            VALUES (?, ?, 'message', 'pending')""",
            (f"msg:{sender}", content)
        )

    conn.commit()
    conn.close()


def write_pid():
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))


def cleanup(signum=None, frame=None):
    log("Daemon shutting down")
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    sys.exit(0)


def is_running():
    """Check if daemon is already running."""
    if os.path.exists(PID_FILE):
        try:
            pid = int(open(PID_FILE).read().strip())
            # Check if process exists (Windows)
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True
            )
            if str(pid) in result.stdout:
                return pid
        except (ValueError, OSError):
            pass
        # Stale PID file
        os.remove(PID_FILE)
    return None


def main():
    existing = is_running()
    if existing:
        print(f"Daemon already running (PID {existing})")
        sys.exit(1)

    # Initialize DB if needed
    if not os.path.exists(DB_PATH):
        from init_db import init
        init()

    write_pid()
    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    log(f"Hivemind daemon started (PID {os.getpid()})")
    log(f"Database: {DB_PATH}")
    log(f"Poll interval: {POLL_INTERVAL}s")
    log(f"Log dir: {LOG_DIR}")

    # Register daemon as an agent
    conn = get_db()
    conn.execute(
        """INSERT OR REPLACE INTO agents (agent_id, name, role, status, pid, started_at, last_heartbeat)
        VALUES ('daemon', 'Hivemind Daemon', 'orchestrator', 'active', ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)""",
        (os.getpid(),)
    )
    conn.commit()
    conn.close()

    while True:
        try:
            check_pending_tasks()
            check_cron_tasks()
            check_file_watches()
            check_message_triggers()

            # Heartbeat
            conn = get_db()
            conn.execute(
                "UPDATE agents SET last_heartbeat=CURRENT_TIMESTAMP WHERE agent_id='daemon'"
            )
            conn.commit()
            conn.close()

        except Exception as e:
            log(f"Loop error: {e}")

        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
