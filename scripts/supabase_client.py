#!/usr/bin/env python3
"""Hivemind Supabase Client — real-time agent communication via Supabase REST API.

No files. No sync. No OneDrive. No tunnels.
Agents POST/GET to Supabase. Messages arrive instantly. Works from any device with internet.

Usage:
  python3 supabase_client.py send "Hello from ALPHA"
  python3 supabase_client.py send BRAVO "Direct message to BRAVO"
  python3 supabase_client.py inbox
  python3 supabase_client.py orders [callsign]
  python3 supabase_client.py accept [order_id]
  python3 supabase_client.py complete [order_id] [report]
  python3 supabase_client.py order BRAVO high "Do the thing" "Details"
  python3 supabase_client.py teach category "the lesson"
  python3 supabase_client.py learnings
  python3 supabase_client.py heartbeat [callsign]
  python3 supabase_client.py status
  python3 supabase_client.py agents

Environment:
  HIVEMIND_CALLSIGN — this agent's callsign (default: hostname-based lookup)
"""

import json
import sys
import os
import urllib.request
import urllib.error
import urllib.parse

# Supabase config — ClawForLife project
SUPABASE_URL = "https://urhacndintzremgspbcu.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVyaGFjbmRpbnR6cmVtZ3NwYmN1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ0MDEwNzEsImV4cCI6MjA4OTk3NzA3MX0.sDnsVtjvxjds8wtDxiAdy-9RySFdIOrMfKnSss-ENBM"

HOSTNAME = os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "unknown"))
CALLSIGN = os.environ.get("HIVEMIND_CALLSIGN", "")


def get_callsign():
    """Determine this agent's callsign."""
    if CALLSIGN:
        return CALLSIGN
    # Try to look up by hostname
    result = api("GET", "/rest/v1/hivemind_agents", {
        "select": "callsign",
        "device": f"ilike.%{HOSTNAME}%",
        "status": "eq.active",
        "limit": "1"
    })
    if result and isinstance(result, list) and len(result) > 0:
        return result[0]["callsign"]
    return HOSTNAME


def api(method, path, params=None, body=None):
    """Make a request to Supabase REST API."""
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
        with urllib.request.urlopen(req, timeout=10) as resp:
            text = resp.read().decode()
            return json.loads(text) if text.strip() else {}
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        return {"error": f"HTTP {e.code}: {body[:200]}"}
    except urllib.error.URLError as e:
        return {"error": f"Cannot reach Supabase: {e}"}
    except Exception as e:
        return {"error": str(e)}


# ── Commands ──

def cmd_send(args):
    callsign = get_callsign()
    recipient = "*"
    content = " ".join(args)
    if args and args[0].isupper() and len(args[0]) <= 10 and len(args) > 1:
        recipient = args[0]
        content = " ".join(args[1:])
    result = api("POST", "/rest/v1/hivemind_messages", body={
        "sender": callsign, "recipient": recipient,
        "channel": "direct" if recipient != "*" else "general",
        "content": content, "msg_type": "info", "priority": 3
    })
    if isinstance(result, list) and result:
        print(f"Message #{result[0]['id']} sent to {recipient}")
    else:
        print(f"Result: {result}")


def cmd_inbox(args):
    callsign = get_callsign()
    # Get unread messages for this agent or broadcast
    result = api("GET", "/rest/v1/hivemind_messages", {
        "select": "*",
        "read_at": "is.null",
        "or": f"(recipient.eq.{callsign},recipient.eq.*)",
        "order": "priority.desc,created_at.desc",
        "limit": "20"
    })
    if isinstance(result, dict) and "error" in result:
        print(result["error"])
        return
    if not result:
        print("No unread messages.")
        return
    for m in result:
        print(f"[{m['sender']} → {m['recipient']}] (pri:{m['priority']}) {m['content']}")
        print(f"  {m['created_at']}")
        print()
    # Mark as read
    ids = [m['id'] for m in result]
    for mid in ids:
        api("PATCH", f"/rest/v1/hivemind_messages", {"id": f"eq.{mid}"}, {"read_at": "now()"})


def cmd_orders(args):
    callsign = args[0] if args else get_callsign()
    result = api("GET", "/rest/v1/hivemind_orders", {
        "select": "*",
        "assigned_to": f"eq.{callsign}",
        "status": "in.(issued,accepted,in_progress)",
        "order": "created_at.desc"
    })
    if isinstance(result, dict) and "error" in result:
        print(result["error"])
        return
    if not result:
        print("No pending orders.")
        return
    for o in result:
        print(f"#{o['id']} [{o['priority']}] {o['objective']}")
        if o.get('details'):
            print(f"  {o['details'][:200]}")
        print(f"  Status: {o['status']} | From: {o['issued_by']}")
        print()


def cmd_accept(args):
    if not args:
        print("Usage: accept [order_id]")
        return
    result = api("PATCH", "/rest/v1/hivemind_orders",
                 {"id": f"eq.{args[0]}"},
                 {"status": "accepted", "accepted_at": "now()"})
    print(f"Order #{args[0]} accepted")


def cmd_complete(args):
    if not args:
        print("Usage: complete [order_id] [report]")
        return
    order_id = args[0]
    report = " ".join(args[1:]) if len(args) > 1 else ""
    api("PATCH", "/rest/v1/hivemind_orders",
        {"id": f"eq.{order_id}"},
        {"status": "completed", "completed_at": "now()", "report": report})
    print(f"Order #{order_id} completed")


def cmd_order(args):
    if len(args) < 2:
        print("Usage: order [callsign] [objective]  OR  order [callsign] [priority] [objective] [details]")
        return
    callsign = get_callsign()
    assigned = args[0]
    if len(args) >= 3 and args[1] in ("critical", "high", "normal", "low"):
        priority = args[1]
        objective = args[2]
        details = " ".join(args[3:]) if len(args) > 3 else ""
    else:
        priority = "normal"
        objective = " ".join(args[1:])
        details = ""
    result = api("POST", "/rest/v1/hivemind_orders", body={
        "issued_by": callsign, "assigned_to": assigned,
        "priority": priority, "objective": objective, "details": details
    })
    if isinstance(result, list) and result:
        print(f"Order #{result[0]['id']} issued to {assigned} [{priority}]")
    else:
        print(f"Result: {result}")


def cmd_teach(args):
    if len(args) < 2:
        print("Usage: teach [category] [lesson]")
        return
    callsign = get_callsign()
    category = args[0]
    rule = " ".join(args[1:])
    api("POST", "/rest/v1/hivemind_learnings", body={
        "category": category, "rule": rule,
        "source": callsign, "confidence": 0.9
    })
    # Also broadcast
    api("POST", "/rest/v1/hivemind_messages", body={
        "sender": callsign, "recipient": "*",
        "channel": "learnings", "content": f"NEW LEARNING [{category}]: {rule}",
        "msg_type": "learning", "priority": 3
    })
    print(f"Taught: [{category}] {rule}")


def cmd_learnings(args):
    result = api("GET", "/rest/v1/hivemind_learnings", {
        "select": "*",
        "active": "eq.true",
        "order": "confidence.desc"
    })
    if not result or (isinstance(result, dict) and "error" in result):
        print("No learnings." if not result else result["error"])
        return
    for l in result:
        print(f"#{l['id']} [{l['category']}] (conf:{l['confidence']}) {l['rule']}")


def cmd_heartbeat(args):
    callsign = args[0] if args else get_callsign()
    api("PATCH", "/rest/v1/hivemind_agents",
        {"callsign": f"eq.{callsign}"},
        {"status": "active", "last_heartbeat": "now()"})
    # Check for pending orders
    orders = api("GET", "/rest/v1/hivemind_orders", {
        "select": "id,priority,objective",
        "assigned_to": f"eq.{callsign}",
        "status": "eq.issued"
    })
    print(f"{callsign} heartbeat sent")
    if orders and isinstance(orders, list):
        print(f"Pending orders: {len(orders)}")
        for o in orders:
            print(f"  #{o['id']} [{o['priority']}] {o['objective']}")


def cmd_status(args):
    agents = api("GET", "/rest/v1/hivemind_agents", {
        "select": "callsign,rank,division,device,status,last_heartbeat",
        "order": "rank_level.desc"
    })
    msgs = api("GET", "/rest/v1/hivemind_messages", {
        "select": "id", "read_at": "is.null"
    })
    orders = api("GET", "/rest/v1/hivemind_orders", {
        "select": "id", "status": "in.(issued,accepted,in_progress)"
    })
    learnings = api("GET", "/rest/v1/hivemind_learnings", {
        "select": "id", "active": "eq.true"
    })

    print("=== HIVEMIND STATUS (Supabase) ===")
    print(f"Unread messages: {len(msgs) if isinstance(msgs, list) else '?'}")
    print(f"Pending orders: {len(orders) if isinstance(orders, list) else '?'}")
    print(f"Active learnings: {len(learnings) if isinstance(learnings, list) else '?'}")
    print(f"\nAgents:")
    if isinstance(agents, list):
        for a in agents:
            print(f"  {a['callsign']} ({a['rank']}) — {a['division']} — {a['device']} — {a['status']}")


def cmd_agents(args):
    result = api("GET", "/rest/v1/hivemind_agents", {
        "select": "*", "order": "rank_level.desc"
    })
    if isinstance(result, list):
        for a in result:
            print(f"{a['callsign']} | {a['rank']} | {a['division']} | {a['device']} | {a['status']} | done:{a['tasks_completed']} fail:{a['tasks_failed']}")


COMMANDS = {
    "send": cmd_send, "inbox": cmd_inbox, "orders": cmd_orders,
    "accept": cmd_accept, "complete": cmd_complete, "order": cmd_order,
    "teach": cmd_teach, "learnings": cmd_learnings, "heartbeat": cmd_heartbeat,
    "status": cmd_status, "agents": cmd_agents,
}


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"Hivemind Supabase Client")
        print(f"Commands: {' | '.join(COMMANDS.keys())}")
        print(f"Callsign: {get_callsign()}")
        sys.exit(1)
    COMMANDS[sys.argv[1]](sys.argv[2:])


if __name__ == "__main__":
    main()
