#!/usr/bin/env python3
"""SessionStart hook — loads learnings and unread messages from hivemind.

Injects relevant learnings (corrections, preferences, patterns) and any
messages from other agents into the session context.
"""

import json
import sys
import os
import sqlite3
import uuid

DB_PATH = os.path.expanduser("~/hivemind.db")


def main():
    if not os.path.exists(DB_PATH):
        print(json.dumps({}))
        sys.exit(0)

    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        session_id = str(uuid.uuid4())[:8]

        # Register this session as an agent
        hostname = os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "unknown"))
        conn.execute(
            """INSERT OR IGNORE INTO agents (agent_id, name, role, status, pid, working_dir, last_heartbeat)
            VALUES (?, ?, 'worker', 'active', ?, ?, CURRENT_TIMESTAMP)""",
            (f"session:{session_id}", f"{hostname}:{session_id}", os.getpid(), os.getcwd())
        )
        # Update existing agent heartbeat for this device
        conn.execute(
            """UPDATE agents SET last_heartbeat=CURRENT_TIMESTAMP, status='active', pid=?
            WHERE LOWER(device)=LOWER(?) AND agent_id NOT LIKE 'session:%'""",
            (os.getpid(), hostname)
        )

        # Load top learnings (most confident, most applied)
        learnings = conn.execute(
            """SELECT category, rule FROM learnings
            WHERE active=1
            ORDER BY confidence DESC, times_applied DESC
            LIMIT 15"""
        ).fetchall()

        # Load unread messages for this agent
        messages = conn.execute(
            """SELECT sender, content, created_at FROM messages
            WHERE read_at IS NULL AND (recipient='*' OR recipient=?)
            ORDER BY priority DESC, created_at DESC
            LIMIT 10""",
            (f"session:{session_id}",)
        ).fetchall()

        # Mark messages as read
        if messages:
            conn.execute(
                """UPDATE messages SET read_at=CURRENT_TIMESTAMP
                WHERE read_at IS NULL AND (recipient='*' OR recipient=?)""",
                (f"session:{session_id}",)
            )

        # Check for active agents on other devices
        other_agents = conn.execute(
            """SELECT name, role, working_dir, last_heartbeat FROM agents
            WHERE status='active' AND agent_id != ?
            AND last_heartbeat > datetime('now', '-5 minutes')""",
            (f"session:{session_id}",)
        ).fetchall()

        conn.commit()
        conn.close()

        # Build context injection
        parts = []

        if learnings:
            parts.append("HIVEMIND LEARNINGS (apply these):")
            for cat, rule in learnings:
                parts.append(f"  [{cat}] {rule}")

        if messages:
            parts.append("\nHIVEMIND MESSAGES (from other agents):")
            for sender, content, ts in messages:
                parts.append(f"  [{sender} @ {ts}] {content}")

        if other_agents:
            parts.append("\nACTIVE HIVEMIND AGENTS:")
            for name, role, wdir, hb in other_agents:
                parts.append(f"  {name} ({role}) — {wdir} — last seen {hb}")
            parts.append("  Use /hivemind send [message] to communicate with them.")

        if parts:
            result = {"systemMessage": "\n".join(parts)}
        else:
            result = {"systemMessage": f"Hivemind connected. Session {session_id}. No pending learnings or messages."}

        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({"systemMessage": f"Hivemind connect error: {e}"}))

    sys.exit(0)


if __name__ == "__main__":
    main()
