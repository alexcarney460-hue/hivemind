#!/usr/bin/env python3
"""Hivemind Sync — merges messages, orders, and learnings between two hivemind.db instances.

SQLite doesn't handle concurrent writes from multiple machines via cloud sync.
Instead, each device keeps its own hivemind.db. This script syncs data between them
via a shared folder (OneDrive, Syncthing, USB, etc).

How it works:
  1. Export new rows from local db to a JSON exchange file in the shared folder
  2. Import new rows from other devices' exchange files into local db
  3. Each row has a globally unique ID (device:timestamp:random) to prevent duplicates

Usage:
  python3 sync.py export              # Push local changes to shared folder
  python3 sync.py import              # Pull remote changes into local db
  python3 sync.py sync                # Both (export then import)
  python3 sync.py --shared /path      # Override shared folder location
"""

import sqlite3
import json
import os
import sys
import hashlib
from datetime import datetime
from pathlib import Path

DB_PATH = os.path.expanduser("~/hivemind.db")
HOSTNAME = os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "unknown"))

# Default shared folder — override with --shared
DEFAULT_SHARED = os.path.expanduser("~/OneDrive/hivemind-sync")


def get_shared_dir():
    for i, arg in enumerate(sys.argv):
        if arg == "--shared" and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return DEFAULT_SHARED


def row_hash(table, row_dict):
    """Generate a unique hash for a row to prevent duplicates."""
    key = f"{table}:{json.dumps(row_dict, sort_keys=True, default=str)}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def export_data(db_path, shared_dir):
    """Export new messages, orders, learnings, and agent updates to shared folder."""
    os.makedirs(shared_dir, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.text_factory = lambda b: b.decode("utf-8", errors="replace")
    conn.row_factory = sqlite3.Row

    export = {
        "source": HOSTNAME,
        "timestamp": datetime.now().isoformat(),
        "messages": [],
        "orders": [],
        "learnings": [],
        "agents": [],
    }

    # Export messages
    rows = conn.execute("SELECT * FROM messages ORDER BY created_at DESC LIMIT 100").fetchall()
    for r in rows:
        export["messages"].append(dict(r))

    # Export orders
    rows = conn.execute("SELECT * FROM orders ORDER BY created_at DESC LIMIT 50").fetchall()
    for r in rows:
        export["orders"].append(dict(r))

    # Export learnings
    rows = conn.execute("SELECT * FROM learnings WHERE active=1 ORDER BY created_at DESC LIMIT 100").fetchall()
    for r in rows:
        export["learnings"].append(dict(r))

    # Export agent registry
    rows = conn.execute("SELECT * FROM agents").fetchall()
    for r in rows:
        export["agents"].append(dict(r))

    conn.close()

    # Write to device-specific file
    outfile = os.path.join(shared_dir, f"{HOSTNAME}.json")
    with open(outfile, "w") as f:
        json.dump(export, f, indent=2, default=str)

    print(f"Exported to {outfile}")
    print(f"  {len(export['messages'])} messages, {len(export['orders'])} orders, {len(export['learnings'])} learnings, {len(export['agents'])} agents")


def import_data(db_path, shared_dir):
    """Import data from other devices' exchange files."""
    if not os.path.exists(shared_dir):
        print(f"Shared dir not found: {shared_dir}")
        return

    conn = sqlite3.connect(db_path)
    total_imported = {"messages": 0, "orders": 0, "learnings": 0, "agents": 0}

    for fname in os.listdir(shared_dir):
        if not fname.endswith(".json"):
            continue
        source_device = fname.replace(".json", "")
        if source_device.lower() == HOSTNAME.lower():
            continue  # Skip our own export

        filepath = os.path.join(shared_dir, fname)
        try:
            with open(filepath) as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"  Skipping {fname}: {e}")
            continue

        print(f"Importing from {source_device}...")

        # Import messages — dedupe by sender+content+created_at
        for msg in data.get("messages", []):
            existing = conn.execute(
                "SELECT id FROM messages WHERE sender=? AND content=? AND created_at=?",
                (msg.get("sender"), msg.get("content"), msg.get("created_at"))
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO messages (sender, recipient, channel, content, msg_type, priority, created_at, read_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (msg.get("sender"), msg.get("recipient"), msg.get("channel"),
                     msg.get("content"), msg.get("msg_type"), msg.get("priority", 0),
                     msg.get("created_at"), msg.get("read_at"), msg.get("expires_at"))
                )
                total_imported["messages"] += 1

        # Import orders — dedupe by issued_by+objective+created_at
        for order in data.get("orders", []):
            existing = conn.execute(
                "SELECT id FROM orders WHERE issued_by=? AND objective=? AND created_at=?",
                (order.get("issued_by"), order.get("objective"), order.get("created_at"))
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO orders (issued_by, assigned_to, order_type, priority, objective, details, constraints, deadline, status, accepted_at, completed_at, report, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (order.get("issued_by"), order.get("assigned_to"), order.get("order_type"),
                     order.get("priority"), order.get("objective"), order.get("details"),
                     order.get("constraints"), order.get("deadline"), order.get("status"),
                     order.get("accepted_at"), order.get("completed_at"), order.get("report"),
                     order.get("created_at"))
                )
                total_imported["orders"] += 1

        # Import learnings — dedupe by rule+category
        for learning in data.get("learnings", []):
            existing = conn.execute(
                "SELECT id FROM learnings WHERE rule=? AND category=?",
                (learning.get("rule"), learning.get("category"))
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO learnings (category, rule, context, source_session, confidence, times_applied, times_helpful, created_at, active)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (learning.get("category"), learning.get("rule"), learning.get("context"),
                     learning.get("source_session"), learning.get("confidence", 0.5),
                     learning.get("times_applied", 0), learning.get("times_helpful", 0),
                     learning.get("created_at"), learning.get("active", 1))
                )
                total_imported["learnings"] += 1

        # Import/update agents — upsert by callsign
        for agent in data.get("agents", []):
            callsign = agent.get("callsign")
            if not callsign:
                continue
            existing = conn.execute(
                "SELECT id FROM agents WHERE callsign=?", (callsign,)
            ).fetchone()
            if existing:
                # Update heartbeat and status from remote
                conn.execute(
                    """UPDATE agents SET last_heartbeat=MAX(last_heartbeat, ?), status=?
                    WHERE callsign=?""",
                    (agent.get("last_heartbeat"), agent.get("status"), callsign)
                )
            else:
                conn.execute(
                    """INSERT INTO agents (agent_id, name, callsign, rank, rank_level, division, specialization, device, status, reports_to, tasks_completed, tasks_failed)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (agent.get("agent_id"), agent.get("name"), callsign,
                     agent.get("rank"), agent.get("rank_level"), agent.get("division"),
                     agent.get("specialization"), agent.get("device"), agent.get("status"),
                     agent.get("reports_to"), agent.get("tasks_completed", 0), agent.get("tasks_failed", 0))
                )
                total_imported["agents"] += 1

    conn.commit()
    conn.close()

    print(f"Imported: {total_imported['messages']} messages, {total_imported['orders']} orders, {total_imported['learnings']} learnings, {total_imported['agents']} agents")


def main():
    shared_dir = get_shared_dir()
    action = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else "sync"

    if action == "export":
        export_data(DB_PATH, shared_dir)
    elif action == "import":
        import_data(DB_PATH, shared_dir)
    elif action == "sync":
        export_data(DB_PATH, shared_dir)
        import_data(DB_PATH, shared_dir)
    else:
        print(f"Usage: sync.py [export|import|sync] [--shared /path]")
        sys.exit(1)


if __name__ == "__main__":
    main()
