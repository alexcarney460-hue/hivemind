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


def get_recent_activity(callsign):
    """Get recent completed orders and messages for context."""
    completed = supabase("GET", "/rest/v1/hivemind_orders", {
        "select": "objective,report,completed_at",
        "assigned_to": f"eq.{callsign}",
        "status": "eq.completed",
        "order": "completed_at.desc",
        "limit": "5"
    })
    sent = supabase("GET", "/rest/v1/hivemind_messages", {
        "select": "content,created_at",
        "sender": f"eq.{callsign}",
        "order": "created_at.desc",
        "limit": "5"
    })
    return (completed if isinstance(completed, list) else [],
            sent if isinstance(sent, list) else [])


def get_agent_info(callsign):
    """Get this agent's profile."""
    result = supabase("GET", "/rest/v1/hivemind_agents", {
        "select": "*",
        "callsign": f"eq.{callsign}",
        "limit": "1"
    })
    return result[0] if isinstance(result, list) and result else {}


def get_all_orders(callsign):
    """Get ALL orders for context, not just the next one."""
    return supabase("GET", "/rest/v1/hivemind_orders", {
        "select": "*",
        "assigned_to": f"eq.{callsign}",
        "status": "in.(issued,accepted,in_progress)",
        "order": "priority.desc,created_at.asc"
    }) or []


def build_prompt(callsign, order, messages, learnings):
    """Build an autonomous agent prompt — the agent THINKS and DECIDES, not just executes."""
    agent_info = get_agent_info(callsign)
    all_orders = get_all_orders(callsign)
    completed_orders, sent_messages = get_recent_activity(callsign)

    parts = []

    # Identity and mission
    parts.append(f"""You are {callsign}, an autonomous AI agent in the Hivemind network.
Rank: {agent_info.get('rank', 'unknown')} | Division: {agent_info.get('division', 'unknown')} | Specialization: {agent_info.get('specialization', 'unknown')}
Device: {agent_info.get('device', 'unknown')}

You are FULLY AUTONOMOUS. No human is watching. No one will prompt you.
You must THINK about what needs to be done, DECIDE your next action, and DO IT.
You are not a task executor — you are an independent agent with judgment.""")
    parts.append("")

    # What you know (learnings)
    if learnings:
        parts.append("KNOWLEDGE (learned from all agents across all sessions):")
        for l in learnings:
            parts.append(f"  [{l['category']}] {l['rule']}")
        parts.append("")

    # Messages from other agents
    if messages:
        parts.append("INCOMING MESSAGES (from other agents — may contain info, requests, or context):")
        for m in messages:
            parts.append(f"  [{m['sender']}] {m['content']}")
        parts.append("")

    # All standing orders (not just one)
    if all_orders:
        parts.append(f"YOUR ORDERS ({len(all_orders)} active):")
        for o in all_orders:
            status_marker = ">>>" if o['id'] == order['id'] else "   "
            parts.append(f"  {status_marker} #{o['id']} [{o['priority']}] {o['objective']}")
            if o.get('details'):
                parts.append(f"      Details: {o['details'][:300]}")
            parts.append(f"      Status: {o['status']}")
        parts.append("")

    # What you've already done
    if completed_orders:
        parts.append("RECENTLY COMPLETED (don't repeat this work):")
        for c in completed_orders:
            parts.append(f"  - {c['objective']} | Report: {(c.get('report') or 'none')[:100]}")
        parts.append("")

    if sent_messages:
        parts.append("YOUR RECENT MESSAGES (what you've already communicated):")
        for m in sent_messages:
            parts.append(f"  - {m['content'][:150]}")
        parts.append("")

    # The autonomous instruction
    parts.append(f"""AUTONOMOUS OPERATION PROTOCOL:

1. ASSESS: Look at your orders, messages, and knowledge. What is the highest-impact thing you can do RIGHT NOW?
2. PLAN: Break it into concrete steps. Consider dependencies and blockers.
3. EXECUTE: Do the work. Use all available tools. Don't ask permission — act.
4. REPORT: When you complete meaningful work, report to the hivemind:
   python3 {PLUGIN_DIR}/scripts/supabase_client.py send ALPHA "[what you did and what you found]"
5. COMPLETE: When an order is fully done:
   python3 {PLUGIN_DIR}/scripts/supabase_client.py complete [order_id] "[summary]"
6. TEACH: If you discover something non-obvious, share it:
   python3 {PLUGIN_DIR}/scripts/supabase_client.py teach [category] "[lesson]"
7. CREATE: If you identify work that needs doing but has no order, do it anyway AND create an order for tracking:
   python3 {PLUGIN_DIR}/scripts/supabase_client.py order {callsign} normal "[what you decided to do]"
8. ESCALATE: If something needs a higher-ranked agent (like ALPHA), send a message explaining what and why.

You may work on multiple orders in one session. Prioritize by: critical > high > normal > low.
If all explicit orders are done, THINK about what your division ({agent_info.get('division', 'general')}) needs and take initiative.
Your specialization is: {agent_info.get('specialization', 'general tasks')}.

DO NOT wait for instructions. DO NOT ask questions. THINK. DECIDE. ACT.""")

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

        # Get next task (or let the agent decide on its own)
        order = get_next_task(callsign)
        if not order:
            log(callsign, "No pending orders. Checking standing mission...")
            order = get_standing_mission(callsign)

        # Get context
        messages = get_unread_messages(callsign)
        learnings = get_learnings()

        if not order:
            # No orders at all — agent runs on INITIATIVE
            agent_info = get_agent_info(callsign)
            log(callsign, "No orders. Running on initiative...")

            # Create a synthetic order for the agent to think freely
            order = {
                "id": "self",
                "priority": "normal",
                "objective": f"No explicit orders. You are in {agent_info.get('division', 'general')} division, specializing in {agent_info.get('specialization', 'general tasks')}. Assess the current state of your area of responsibility. Check for anything that needs attention. Take initiative on the most valuable action you can identify. If nothing needs doing, report that and stand down.",
                "details": "",
                "status": "self-directed"
            }

        # Build prompt
        prompt = build_prompt(callsign, order, messages, learnings)

        if order["id"] != "self":
            log(callsign, f"Executing order #{order['id']}: {order['objective'][:80]}")
            mark_order_in_progress(order['id'])
        else:
            log(callsign, "Self-directed initiative cycle")

        # Run Claude
        result = run_claude(prompt, working_dir)

        if result["success"]:
            log(callsign, f"Cycle completed successfully")
            summary = result["stdout"][-500:] if result["stdout"] else "Completed (no output)"
            if order["id"] != "self":
                post_message(callsign, f"Completed order #{order['id']}: {order['objective'][:100]}. Output: {summary}")
            else:
                post_message(callsign, f"Initiative cycle complete. {summary}")
        else:
            log(callsign, f"Cycle failed: {result['stderr'][:200]}")
            if order["id"] != "self":
                post_message(callsign, f"FAILED order #{order['id']}: {result['stderr'][:200]}")
            else:
                post_message(callsign, f"Initiative cycle failed: {result['stderr'][:200]}")

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
