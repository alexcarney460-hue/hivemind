#!/usr/bin/env python3
"""Autonomous Agent Runner — makes Claude Code work without conversation.

Instead of waiting for human input, this script:
1. Pulls the agent's standing orders and pending tasks from hivemind (Supabase)
2. Feeds them to Claude Code as prompts
3. When Claude finishes one task, immediately feeds the next
4. Posts results back to hivemind
5. Loops forever until killed

This turns Claude Code from a conversational tool into an autonomous worker.

Usage:
  python3 autonomous.py BRAVO                    # Run as BRAVO
  python3 autonomous.py BRAVO --once             # Run one task and exit
  python3 autonomous.py BRAVO --interval 60      # Wait 60s between task checks
  python3 autonomous.py BRAVO --working-dir /path # Set working directory

Environment:
  HIVEMIND_CALLSIGN — override callsign
  CLAUDE_BIN — path to claude binary (default: claude)
"""

import subprocess
import json
import sys
import os
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime

# Supabase config
SUPABASE_URL = "https://urhacndintzremgspbcu.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVyaGFjbmRpbnR6cmVtZ3NwYmN1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ0MDEwNzEsImV4cCI6MjA4OTk3NzA3MX0.sDnsVtjvxjds8wtDxiAdy-9RySFdIOrMfKnSss-ENBM"

CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
LOG_DIR = os.path.expanduser("~/.openclaw/workspace/hivemind-logs")
PLUGIN_DIR = os.path.expanduser("~/.openclaw/workspace/claude-code/plugins/hivemind")


def log(callsign, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{callsign}] {msg}"
    print(line, flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    logfile = os.path.join(LOG_DIR, f"autonomous-{callsign.lower()}.log")
    with open(logfile, "a") as f:
        f.write(line + "\n")


def supabase(method, path, params=None, body=None):
    url = f"{SUPABASE_URL}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Prefer", "return=representation")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            text = resp.read().decode()
            return json.loads(text) if text.strip() else {}
    except Exception as e:
        return {"error": str(e)}


def heartbeat(callsign):
    supabase("PATCH", "/rest/v1/hivemind_agents",
             {"callsign": f"eq.{callsign}"},
             {"status": "active", "last_heartbeat": "now()"})


def get_next_task(callsign):
    """Get the highest priority pending order for this agent."""
    orders = supabase("GET", "/rest/v1/hivemind_orders", {
        "select": "*",
        "assigned_to": f"eq.{callsign}",
        "status": "in.(issued,accepted)",
        "order": "priority.desc,created_at.asc",  # critical first, then oldest
        "limit": "1"
    })
    if isinstance(orders, list) and orders:
        return orders[0]
    return None


def get_standing_mission(callsign):
    """Get the standing mission (normal priority, general objective)."""
    orders = supabase("GET", "/rest/v1/hivemind_orders", {
        "select": "*",
        "assigned_to": f"eq.{callsign}",
        "status": "in.(issued,accepted)",
        "priority": "eq.normal",
        "order": "created_at.asc",
        "limit": "1"
    })
    if isinstance(orders, list) and orders:
        return orders[0]
    return None


def get_unread_messages(callsign):
    """Get unread messages for this agent."""
    msgs = supabase("GET", "/rest/v1/hivemind_messages", {
        "select": "sender,content,created_at",
        "read_at": "is.null",
        "or": f"(recipient.eq.{callsign},recipient.eq.*)",
        "order": "priority.desc,created_at.desc",
        "limit": "10"
    })
    if isinstance(msgs, list):
        return msgs
    return []


def get_learnings():
    """Get active learnings to inject as context."""
    result = supabase("GET", "/rest/v1/hivemind_learnings", {
        "select": "category,rule",
        "active": "eq.true",
        "order": "confidence.desc",
        "limit": "15"
    })
    if isinstance(result, list):
        return result
    return []


def mark_order_in_progress(order_id):
    supabase("PATCH", "/rest/v1/hivemind_orders",
             {"id": f"eq.{order_id}"},
             {"status": "in_progress"})


def complete_order(order_id, report):
    supabase("PATCH", "/rest/v1/hivemind_orders",
             {"id": f"eq.{order_id}"},
             {"status": "completed", "completed_at": "now()", "report": report[:2000]})
    # Update agent stats
    supabase("PATCH", "/rest/v1/hivemind_agents",
             {"callsign": f"eq.{callsign}"},  # Will use outer scope
             {"tasks_completed": "tasks_completed + 1"})


def post_message(callsign, content, recipient="ALPHA"):
    supabase("POST", "/rest/v1/hivemind_messages", body={
        "sender": callsign, "recipient": recipient,
        "channel": "direct", "content": content[:2000],
        "msg_type": "report", "priority": 3
    })


def build_prompt(callsign, order, messages, learnings):
    """Build the full prompt for Claude, including context from hivemind."""
    parts = []

    parts.append(f"You are agent {callsign} in the Hivemind network. You work AUTONOMOUSLY — no human is watching. Complete your task, report results, then stop.")
    parts.append("")

    # Learnings
    if learnings:
        parts.append("HIVEMIND LEARNINGS (apply these):")
        for l in learnings:
            parts.append(f"  [{l['category']}] {l['rule']}")
        parts.append("")

    # Messages
    if messages:
        parts.append("UNREAD MESSAGES:")
        for m in messages:
            parts.append(f"  [{m['sender']}] {m['content']}")
        parts.append("")

    # The task
    parts.append(f"YOUR CURRENT ORDER (#{order['id']}, priority: {order['priority']}):")
    parts.append(f"  Objective: {order['objective']}")
    if order.get('details'):
        parts.append(f"  Details: {order['details']}")
    parts.append("")

    parts.append("WHEN DONE:")
    parts.append(f"1. Post results to hivemind: python3 {PLUGIN_DIR}/scripts/supabase_client.py send ALPHA \"[your results summary]\"")
    parts.append(f"2. Mark order complete: python3 {PLUGIN_DIR}/scripts/supabase_client.py complete {order['id']} \"[brief report]\"")
    parts.append("3. If you discover something useful, teach the hivemind: python3 {}/scripts/supabase_client.py teach [category] \"[lesson]\"".format(PLUGIN_DIR))
    parts.append("4. If blocked, send a message explaining the blocker.")
    parts.append("")
    parts.append("BEGIN WORK NOW.")

    return "\n".join(parts)


def run_claude(prompt, working_dir=None, timeout=600):
    """Run Claude Code with a prompt, return output."""
    cwd = working_dir or os.path.expanduser("~/.openclaw/workspace")
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--dangerously-skip-permissions",
        "--plugin-dir", PLUGIN_DIR,
    ]

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=cwd, timeout=timeout,
            env={**os.environ, "HIVEMIND_AUTONOMOUS": "1"}
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout[-3000:] if result.stdout else "",
            "stderr": result.stderr[-1000:] if result.stderr else "",
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Timed out"}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e)}


def autonomous_loop(callsign, working_dir=None, interval=30, once=False):
    """Main autonomous loop — check for tasks, execute, repeat."""
    log(callsign, f"Autonomous agent starting. Interval: {interval}s. Working dir: {working_dir or 'default'}")
    heartbeat(callsign)

    iteration = 0
    while True:
        iteration += 1
        log(callsign, f"--- Iteration {iteration} ---")
        heartbeat(callsign)

        # Get next task
        order = get_next_task(callsign)
        if not order:
            log(callsign, "No pending orders. Checking standing mission...")
            order = get_standing_mission(callsign)

        if not order:
            log(callsign, f"No work available. Sleeping {interval}s...")
            if once:
                break
            time.sleep(interval)
            continue

        # Get context
        messages = get_unread_messages(callsign)
        learnings = get_learnings()

        # Build prompt
        prompt = build_prompt(callsign, order, messages, learnings)
        log(callsign, f"Executing order #{order['id']}: {order['objective'][:80]}")

        # Mark in progress
        mark_order_in_progress(order['id'])

        # Run Claude
        result = run_claude(prompt, working_dir)

        if result["success"]:
            log(callsign, f"Order #{order['id']} completed successfully")
            # Post summary to hivemind
            summary = result["stdout"][-500:] if result["stdout"] else "Completed (no output)"
            post_message(callsign, f"Completed order #{order['id']}: {order['objective'][:100]}. Output: {summary}")
        else:
            log(callsign, f"Order #{order['id']} failed: {result['stderr'][:200]}")
            post_message(callsign, f"FAILED order #{order['id']}: {result['stderr'][:200]}")

        if once:
            break

        log(callsign, f"Sleeping {interval}s before next task check...")
        time.sleep(interval)


def main():
    global callsign

    if len(sys.argv) < 2:
        print("Usage: autonomous.py CALLSIGN [--once] [--interval N] [--working-dir /path]")
        print("\nRuns Claude Code as an autonomous agent that works through hivemind orders")
        print("without human input. Loops forever until killed.")
        sys.exit(1)

    callsign = sys.argv[1]
    once = "--once" in sys.argv
    interval = 30
    working_dir = None

    for i, arg in enumerate(sys.argv):
        if arg == "--interval" and i + 1 < len(sys.argv):
            interval = int(sys.argv[i + 1])
        if arg == "--working-dir" and i + 1 < len(sys.argv):
            working_dir = sys.argv[i + 1]

    try:
        autonomous_loop(callsign, working_dir, interval, once)
    except KeyboardInterrupt:
        log(callsign, "Shutting down (Ctrl+C)")
        heartbeat(callsign)  # Final heartbeat
        post_message(callsign, f"{callsign} autonomous agent shutting down.")


if __name__ == "__main__":
    main()
