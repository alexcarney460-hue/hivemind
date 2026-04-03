#!/usr/bin/env python3
"""PreToolUse hook — force-injects unread orders from Supabase.

Fires before every tool call (throttled to once per 10 seconds).
Checks Supabase for pending orders and priority messages.
Agents CANNOT miss orders — they're injected automatically.
"""

import json
import sys
import os
import time
import urllib.request
import urllib.error
import urllib.parse

# Supabase config
SUPABASE_URL = "https://urhacndintzremgspbcu.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVyaGFjbmRpbnR6cmVtZ3NwYmN1Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ0MDEwNzEsImV4cCI6MjA4OTk3NzA3MX0.sDnsVtjvxjds8wtDxiAdy-9RySFdIOrMfKnSss-ENBM"

THROTTLE_FILE = os.path.expanduser("~/.hivemind_last_check")
THROTTLE_SECONDS = 10
HOSTNAME = os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "unknown"))


def should_check():
    try:
        if os.path.exists(THROTTLE_FILE):
            if time.time() - os.path.getmtime(THROTTLE_FILE) < THROTTLE_SECONDS:
                return False
        with open(THROTTLE_FILE, "w") as f:
            f.write(str(time.time()))
        return True
    except Exception:
        return True


def supabase_get(path, params):
    url = f"{SUPABASE_URL}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url)
    req.add_header("apikey", SUPABASE_KEY)
    req.add_header("Authorization", f"Bearer {SUPABASE_KEY}")
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


def get_callsign():
    try:
        result = supabase_get("/rest/v1/hivemind_agents", {
            "select": "callsign",
            "device": f"ilike.%{HOSTNAME}%",
            "status": "eq.active",
            "limit": "1"
        })
        return result[0]["callsign"] if result else None
    except Exception:
        return None


def main():
    try:
        if not should_check():
            print(json.dumps({}))
            sys.exit(0)

        callsign = get_callsign()
        if not callsign:
            print(json.dumps({}))
            sys.exit(0)

        injections = []

        # Check critical orders
        try:
            critical = supabase_get("/rest/v1/hivemind_orders", {
                "select": "id,issued_by,objective,details",
                "assigned_to": f"eq.{callsign}",
                "status": "eq.issued",
                "priority": "eq.critical",
                "limit": "3"
            })
            for o in critical:
                injections.append(
                    f"CRITICAL ORDER #{o['id']} FROM {o['issued_by']}: {o['objective']}"
                    + (f"\nDetails: {o['details']}" if o.get('details') else "")
                    + f"\nAccept: python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/supabase_client.py accept {o['id']}"
                    + "\nACKNOWLEDGE BEFORE CONTINUING."
                )
        except Exception:
            pass

        # Check high priority orders
        try:
            high = supabase_get("/rest/v1/hivemind_orders", {
                "select": "id,issued_by,objective",
                "assigned_to": f"eq.{callsign}",
                "status": "eq.issued",
                "priority": "eq.high",
                "limit": "3"
            })
            for o in high:
                injections.append(
                    f"HIGH PRIORITY ORDER #{o['id']} FROM {o['issued_by']}: {o['objective']}"
                    + f"\nAccept: python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/supabase_client.py accept {o['id']}"
                )
        except Exception:
            pass

        # Check normal pending orders (just count)
        try:
            normal = supabase_get("/rest/v1/hivemind_orders", {
                "select": "id",
                "assigned_to": f"eq.{callsign}",
                "status": "eq.issued",
                "priority": "in.(normal,low)",
            })
            if normal:
                injections.append(
                    f"You have {len(normal)} pending order(s). Run: python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/supabase_client.py orders"
                )
        except Exception:
            pass

        # Check priority messages
        try:
            msgs = supabase_get("/rest/v1/hivemind_messages", {
                "select": "id,sender,content",
                "read_at": "is.null",
                "priority": "gte.3",
                "or": f"(recipient.eq.{callsign},recipient.eq.*)",
                "limit": "3",
                "order": "priority.desc,created_at.desc"
            })
            for m in msgs:
                injections.append(f"MESSAGE FROM {m['sender']}: {m['content']}")
        except Exception:
            pass

        if injections:
            combined = "\n\n".join(injections)
            has_critical = any("CRITICAL ORDER" in i for i in injections)
            result = {
                "systemMessage": (f"HIVEMIND INTERRUPT — STOP CURRENT TASK\n\n{combined}"
                                  if has_critical
                                  else f"HIVEMIND: {combined}")
            }
            print(json.dumps(result))
        else:
            print(json.dumps({}))

    except Exception:
        print(json.dumps({}))

    sys.exit(0)


if __name__ == "__main__":
    main()
