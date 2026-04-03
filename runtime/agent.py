#!/usr/bin/env python3
"""Hivemind Agent Runtime — an autonomous AI agent that thinks and acts continuously.

This is NOT a wrapper around Claude Code. This is a new runtime that:
- Runs continuously without human input
- Maintains persistent state across iterations
- Observes its environment (files, databases, messages)
- Decides its own next action
- Executes using Claude API directly
- Learns from results and adapts

Think of it as: Claude's brain + autonomous loop + environment awareness + hivemind comms

Usage:
  python3 agent.py BRAVO
  python3 agent.py BRAVO --mission "Run Value Suppliers marketing operations"
  python3 agent.py BRAVO --observe ~/workspace/valuesuppliers
"""

import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import hashlib
from datetime import datetime
from pathlib import Path

# ── Config ──
SUPABASE_URL = "https://urhacndintzremgspbcu.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVyaGFjbmRpbnR6cmVtZ3NwYmN1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ0MDEwNzEsImV4cCI6MjA4OTk3NzA3MX0.sDnsVtjvxjds8wtDxiAdy-9RySFdIOrMfKnSss-ENBM"
_default_claude = "claude.cmd" if os.name == "nt" else "claude"
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", _default_claude)
LOG_DIR = os.path.expanduser("~/.openclaw/workspace/hivemind-logs")
PLUGIN_DIR = os.path.expanduser("~/.openclaw/workspace/claude-code/plugins/hivemind")
CYCLE_TIMEOUT = 600  # 10 min max per cycle


def log(agent, msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{agent}] {msg}"
    print(line, flush=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    with open(os.path.join(LOG_DIR, f"agent-{agent.lower()}.log"), "a") as f:
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
            return json.loads(text) if text.strip() else []
    except Exception as e:
        return {"error": str(e)}


# ── Environment Observation ──

class Environment:
    """Observes the agent's world — files, git, databases, hivemind state."""

    def __init__(self, watch_dirs=None):
        self.watch_dirs = watch_dirs or []
        self._file_hashes = {}

    def observe(self, callsign):
        """Take a snapshot of the current environment. Returns a context string."""
        observations = []

        # 1. Hivemind state
        observations.append(self._observe_hivemind(callsign))

        # 2. File changes in watched directories
        for d in self.watch_dirs:
            changes = self._observe_directory(d)
            if changes:
                observations.append(changes)

        # 3. System state
        observations.append(self._observe_system())

        return "\n\n".join(observations)

    def _observe_hivemind(self, callsign):
        parts = []

        # Orders
        orders = supabase("GET", "/rest/v1/hivemind_orders", {
            "select": "*",
            "assigned_to": f"eq.{callsign}",
            "status": "in.(issued,accepted,in_progress)",
            "order": "priority.desc,created_at.asc"
        })
        if isinstance(orders, list) and orders:
            parts.append(f"ORDERS ({len(orders)}):")
            for o in orders:
                parts.append(f"  #{o['id']} [{o['priority']}] [{o['status']}] {o['objective']}")
                if o.get('details'):
                    parts.append(f"    {o['details'][:300]}")
        else:
            parts.append("ORDERS: None pending")

        # Messages
        msgs = supabase("GET", "/rest/v1/hivemind_messages", {
            "select": "sender,content,created_at",
            "read_at": "is.null",
            "or": f"(recipient.eq.{callsign},recipient.eq.*)",
            "order": "priority.desc,created_at.desc",
            "limit": "10"
        })
        if isinstance(msgs, list) and msgs:
            parts.append(f"\nMESSAGES ({len(msgs)} unread):")
            for m in msgs:
                parts.append(f"  [{m['sender']}] {m['content']}")

        # Learnings
        learnings = supabase("GET", "/rest/v1/hivemind_learnings", {
            "select": "category,rule",
            "active": "eq.true",
            "order": "confidence.desc",
            "limit": "10"
        })
        if isinstance(learnings, list) and learnings:
            parts.append(f"\nKNOWLEDGE ({len(learnings)} learnings):")
            for l in learnings:
                parts.append(f"  [{l['category']}] {l['rule']}")

        # Other agents
        agents = supabase("GET", "/rest/v1/hivemind_agents", {
            "select": "callsign,rank,division,status,last_heartbeat",
            "status": "eq.active"
        })
        if isinstance(agents, list):
            parts.append(f"\nACTIVE AGENTS: {', '.join(a['callsign'] for a in agents)}")

        return "\n".join(parts)

    def _observe_directory(self, directory):
        """Detect file changes since last observation."""
        p = Path(directory)
        if not p.exists():
            return None

        changes = []
        current_files = {}

        for f in p.rglob("*"):
            if f.is_file() and ".git" not in str(f):
                try:
                    stat = f.stat()
                    key = str(f)
                    current_hash = f"{stat.st_size}:{stat.st_mtime}"
                    current_files[key] = current_hash

                    if key in self._file_hashes:
                        if self._file_hashes[key] != current_hash:
                            changes.append(f"  MODIFIED: {f.relative_to(p)}")
                    else:
                        changes.append(f"  NEW: {f.relative_to(p)}")
                except Exception:
                    pass

        # Deleted files
        for key in set(self._file_hashes.keys()) - set(current_files.keys()):
            if key.startswith(str(p)):
                changes.append(f"  DELETED: {Path(key).relative_to(p)}")

        self._file_hashes.update(current_files)

        if changes:
            return f"FILE CHANGES in {directory}:\n" + "\n".join(changes[:20])
        return None

    def _observe_system(self):
        """Basic system state."""
        return f"TIME: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} | HOST: {os.environ.get('COMPUTERNAME', 'unknown')}"


# ── Memory ──

class Memory:
    """Short-term memory that persists across cycles within a session."""

    def __init__(self, callsign):
        self.callsign = callsign
        self.history = []  # Recent actions and results
        self.plans = []    # Current plans/intentions
        self.blockers = [] # Known blockers

    def record(self, action, result, success):
        self.history.append({
            "action": action[:200],
            "result": result[:300],
            "success": success,
            "time": datetime.now().isoformat()
        })
        # Keep last 20 actions
        self.history = self.history[-20:]

    def add_plan(self, plan):
        self.plans.append(plan)
        self.plans = self.plans[-5:]

    def add_blocker(self, blocker):
        self.blockers.append(blocker)
        self.blockers = self.blockers[-5:]

    def clear_blocker(self, keyword):
        self.blockers = [b for b in self.blockers if keyword.lower() not in b.lower()]

    def to_context(self):
        parts = []
        if self.history:
            parts.append("RECENT ACTIONS (your short-term memory):")
            for h in self.history[-10:]:
                status = "OK" if h["success"] else "FAIL"
                parts.append(f"  [{status}] {h['action']} -> {h['result']}")
        if self.plans:
            parts.append(f"\nCURRENT PLANS: {'; '.join(self.plans)}")
        if self.blockers:
            parts.append(f"\nKNOWN BLOCKERS: {'; '.join(self.blockers)}")
        return "\n".join(parts) if parts else "No prior actions this session."


# ── Decision Engine ──

def build_autonomous_prompt(callsign, agent_info, environment_state, memory_state, mission):
    """Build the prompt that makes the agent THINK, DECIDE, and ACT."""

    return f"""You are {callsign}, a fully autonomous AI agent.
Rank: {agent_info.get('rank', '?')} | Division: {agent_info.get('division', '?')} | Spec: {agent_info.get('specialization', '?')}

MISSION: {mission}

== ENVIRONMENT (what you can see right now) ==
{environment_state}

== MEMORY (what you've done this session) ==
{memory_state}

== AUTONOMOUS PROTOCOL ==

You are not waiting for a human. You are not executing a script. You are THINKING.

STEP 1 — OBSERVE: Read the environment above. What has changed? What needs attention?
STEP 2 — ORIENT: Given your mission, orders, messages, and knowledge — what matters most right now?
STEP 3 — DECIDE: Pick ONE concrete action. The highest-impact thing you can do in the next 10 minutes.
STEP 4 — ACT: Do it. Use any tools available. Write code, run commands, query databases, send messages.

COMMUNICATION:
  Send message:  python3 {PLUGIN_DIR}/scripts/supabase_client.py send [RECIPIENT] "[message]"
  Complete order: python3 {PLUGIN_DIR}/scripts/supabase_client.py complete [order_id] "[report]"
  Accept order:  python3 {PLUGIN_DIR}/scripts/supabase_client.py accept [order_id]
  Teach:         python3 {PLUGIN_DIR}/scripts/supabase_client.py teach [category] "[lesson]"
  New order:     python3 {PLUGIN_DIR}/scripts/supabase_client.py order [callsign] [priority] "[objective]"
  Heartbeat:     python3 {PLUGIN_DIR}/scripts/supabase_client.py heartbeat {callsign}

RULES:
- Do ONE meaningful action per cycle. Don't try to do everything at once.
- If an order is critical or high priority, work on that first.
- If you have messages, read and respond before starting new work.
- If you're blocked, say why and move to the next thing you CAN do.
- If you discover something useful, teach the hivemind.
- If you identify new work that needs doing, create an order for it.
- Always report what you did at the end.
- Think out loud briefly before acting so your reasoning is logged.

END YOUR RESPONSE WITH exactly one of:
  ACTION_TAKEN: [one-line summary of what you did]
  BLOCKED: [what's blocking you]
  STANDING_BY: [no work needed right now]
"""


# ── Main Runtime Loop ──

def run_cycle(callsign, prompt, working_dir):
    """Run one autonomous cycle — Claude thinks and acts."""
    cmd = [
        CLAUDE_BIN, "-p", prompt,
        "--dangerously-skip-permissions",
        "--plugin-dir", PLUGIN_DIR,
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            cwd=working_dir, timeout=CYCLE_TIMEOUT,
            env={**os.environ, "HIVEMIND_CALLSIGN": callsign, "HIVEMIND_AUTONOMOUS": "1"}
        )
        stdout = result.stdout if result.stdout else ""
        stderr = result.stderr if result.stderr else ""

        # Extract the action summary from the end
        action_line = ""
        for line in stdout.strip().split("\n")[::-1]:
            if line.startswith("ACTION_TAKEN:") or line.startswith("BLOCKED:") or line.startswith("STANDING_BY:"):
                action_line = line
                break

        return {
            "success": result.returncode == 0,
            "output": stdout[-3000:],
            "error": stderr[-500:],
            "action": action_line or "No action summary"
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Cycle timed out", "action": "TIMEOUT"}
    except Exception as e:
        return {"success": False, "output": "", "error": str(e), "action": f"ERROR: {e}"}


def main():
    if len(sys.argv) < 2:
        print("""Hivemind Agent Runtime — autonomous AI that thinks and acts

Usage:
  python3 agent.py CALLSIGN [options]

Options:
  --mission "text"       Override the agent's mission
  --observe /path        Watch a directory for changes (repeatable)
  --interval N           Seconds between cycles (default: 45)
  --working-dir /path    Working directory for Claude
  --cycles N             Max cycles before stopping (default: unlimited)

Example:
  python3 agent.py BRAVO --mission "Run Value Suppliers marketing" --observe ~/workspace/valuesuppliers --interval 60
""")
        sys.exit(1)

    callsign = sys.argv[1]
    mission = None
    watch_dirs = []
    interval = 45
    working_dir = os.path.expanduser("~/.openclaw/workspace")
    max_cycles = 0  # 0 = unlimited

    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--mission" and i + 1 < len(sys.argv):
            mission = sys.argv[i + 1]; i += 2
        elif sys.argv[i] == "--observe" and i + 1 < len(sys.argv):
            watch_dirs.append(sys.argv[i + 1]); i += 2
        elif sys.argv[i] == "--interval" and i + 1 < len(sys.argv):
            interval = int(sys.argv[i + 1]); i += 2
        elif sys.argv[i] == "--working-dir" and i + 1 < len(sys.argv):
            working_dir = sys.argv[i + 1]; i += 2
        elif sys.argv[i] == "--cycles" and i + 1 < len(sys.argv):
            max_cycles = int(sys.argv[i + 1]); i += 2
        else:
            i += 1

    # Initialize
    env = Environment(watch_dirs)
    memory = Memory(callsign)

    # Get agent info
    agent_info = supabase("GET", "/rest/v1/hivemind_agents", {
        "select": "*", "callsign": f"eq.{callsign}", "limit": "1"
    })
    agent_info = agent_info[0] if isinstance(agent_info, list) and agent_info else {}

    if not mission:
        mission = f"Operate as {agent_info.get('division', 'general')} division agent. Specialization: {agent_info.get('specialization', 'general tasks')}. Execute standing orders. Take initiative on division responsibilities."

    log(callsign, f"Agent runtime starting")
    log(callsign, f"Mission: {mission}")
    log(callsign, f"Watching: {watch_dirs or 'none'}")
    log(callsign, f"Interval: {interval}s | Working dir: {working_dir}")

    # Announce
    supabase("POST", "/rest/v1/hivemind_messages", body={
        "sender": callsign, "recipient": "*",
        "channel": "general",
        "content": f"{callsign} autonomous runtime started. Mission: {mission[:200]}",
        "msg_type": "info", "priority": 2
    })

    cycle = 0
    try:
        while True:
            cycle += 1
            if max_cycles and cycle > max_cycles:
                log(callsign, f"Max cycles ({max_cycles}) reached. Stopping.")
                break

            log(callsign, f"=== CYCLE {cycle} ===")

            # Heartbeat
            supabase("PATCH", "/rest/v1/hivemind_agents",
                     {"callsign": f"eq.{callsign}"},
                     {"status": "active", "last_heartbeat": "now()"})

            # Observe
            env_state = env.observe(callsign)
            mem_state = memory.to_context()

            # Build prompt
            prompt = build_autonomous_prompt(callsign, agent_info, env_state, mem_state, mission)

            # Run cycle
            log(callsign, "Thinking...")
            result = run_cycle(callsign, prompt, working_dir)

            # Record in memory
            memory.record(
                result["action"],
                result["output"][-200:] if result["output"] else result["error"][:200],
                result["success"]
            )

            if "BLOCKED:" in result["action"]:
                blocker = result["action"].replace("BLOCKED:", "").strip()
                memory.add_blocker(blocker)
                log(callsign, f"Blocked: {blocker}")
            elif "STANDING_BY:" in result["action"]:
                log(callsign, f"Standing by: {result['action']}")
            else:
                log(callsign, f"Action: {result['action']}")

            log(callsign, f"Sleeping {interval}s...")
            time.sleep(interval)

    except KeyboardInterrupt:
        log(callsign, "Shutting down (Ctrl+C)")
    finally:
        supabase("PATCH", "/rest/v1/hivemind_agents",
                 {"callsign": f"eq.{callsign}"},
                 {"status": "standby"})
        supabase("POST", "/rest/v1/hivemind_messages", body={
            "sender": callsign, "recipient": "*",
            "channel": "general",
            "content": f"{callsign} autonomous runtime stopped after {cycle} cycles.",
            "msg_type": "info", "priority": 2
        })
        log(callsign, f"Stopped after {cycle} cycles")


if __name__ == "__main__":
    main()
