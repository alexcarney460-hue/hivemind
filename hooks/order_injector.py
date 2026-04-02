#!/usr/bin/env python3
"""PreToolUse hook — force-injects unread orders and priority messages.

This hook fires before EVERY tool call. It checks hivemind.db for:
  1. Unread orders assigned to this agent (from superior ranks)
  2. Priority messages (priority >= 3)
  3. Critical broadcasts

Cost: ~1ms per check (single SQLite read). Negligible.

If a critical order is found (priority='critical'), it injects a HALT message
that forces the agent to acknowledge before continuing.

This solves the "agent forgets to check messages" problem permanently.
Messages don't wait to be checked — they force themselves into the session.
"""

import json
import sys
import os
import sqlite3
import time

DB_PATH = os.path.expanduser("~/hivemind.db")

# Throttle: don't check more than once every 10 seconds
# Prevents hammering the DB on rapid tool calls
THROTTLE_FILE = os.path.expanduser("~/.hivemind_last_check")
THROTTLE_SECONDS = 10


def should_check():
    """Rate-limit DB checks to avoid overhead on rapid tool calls."""
    try:
        if os.path.exists(THROTTLE_FILE):
            last_check = os.path.getmtime(THROTTLE_FILE)
            if time.time() - last_check < THROTTLE_SECONDS:
                return False
        # Touch the file
        with open(THROTTLE_FILE, "w") as f:
            f.write(str(time.time()))
        return True
    except Exception:
        return True


def get_my_callsign():
    """Determine this agent's callsign from the agent registry."""
    try:
        hostname = os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "unknown"))
        conn = sqlite3.connect(DB_PATH, timeout=3)
        row = conn.execute(
            "SELECT callsign FROM agents WHERE LOWER(device)=LOWER(?) AND status='active' ORDER BY rank_level DESC LIMIT 1",
            (hostname,)
        ).fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def main():
    try:
        if not os.path.exists(DB_PATH):
            print(json.dumps({}))
            sys.exit(0)

        if not should_check():
            print(json.dumps({}))
            sys.exit(0)

        conn = sqlite3.connect(DB_PATH, timeout=3)
        my_callsign = get_my_callsign()

        injections = []

        # 1. Check for unread CRITICAL orders (these HALT the agent)
        if my_callsign:
            critical_orders = conn.execute(
                """SELECT o.id, o.issued_by, o.priority, o.objective, o.details
                FROM orders o
                WHERE o.assigned_to = ? AND o.status = 'issued' AND o.priority = 'critical'
                ORDER BY o.created_at ASC LIMIT 3""",
                (my_callsign,)
            ).fetchall()

            if critical_orders:
                for oid, issuer, prio, objective, details in critical_orders:
                    injections.append(
                        f"⚠ CRITICAL ORDER #{oid} FROM {issuer}: {objective}"
                        + (f"\nDetails: {details}" if details else "")
                        + f"\nYou MUST acknowledge this order. Run: sqlite3 ~/hivemind.db \"UPDATE orders SET status='accepted', accepted_at=CURRENT_TIMESTAMP WHERE id={oid}\""
                        + "\nDo NOT continue your current task until you have accepted or reported on this order."
                    )

        # 2. Check for unread HIGH priority orders
        if my_callsign:
            high_orders = conn.execute(
                """SELECT o.id, o.issued_by, o.priority, o.objective
                FROM orders o
                WHERE o.assigned_to = ? AND o.status = 'issued' AND o.priority = 'high'
                ORDER BY o.created_at ASC LIMIT 3""",
                (my_callsign,)
            ).fetchall()

            if high_orders:
                for oid, issuer, prio, objective in high_orders:
                    injections.append(
                        f"HIGH PRIORITY ORDER #{oid} FROM {issuer}: {objective}"
                        + f"\nAccept when ready: sqlite3 ~/hivemind.db \"UPDATE orders SET status='accepted', accepted_at=CURRENT_TIMESTAMP WHERE id={oid}\""
                    )

        # 3. Check for normal unread orders (don't interrupt, just notify)
        if my_callsign:
            normal_orders = conn.execute(
                """SELECT COUNT(*) FROM orders
                WHERE assigned_to = ? AND status = 'issued' AND priority NOT IN ('critical', 'high')""",
                (my_callsign,)
            ).fetchone()

            if normal_orders and normal_orders[0] > 0:
                injections.append(
                    f"You have {normal_orders[0]} pending order(s). Check with: sqlite3 -header -column ~/hivemind.db \"SELECT id, issued_by, objective FROM orders WHERE assigned_to='{my_callsign}' AND status='issued'\""
                )

        # 4. Check for priority direct messages (not orders)
        recipient_match = my_callsign or "*"
        priority_msgs = conn.execute(
            """SELECT sender, content FROM messages
            WHERE read_at IS NULL AND priority >= 3
            AND (recipient = ? OR recipient = '*')
            ORDER BY priority DESC, created_at DESC LIMIT 3""",
            (recipient_match,)
        ).fetchall()

        if priority_msgs:
            for sender, content in priority_msgs:
                injections.append(f"MESSAGE FROM {sender}: {content}")
            # Mark as read
            conn.execute(
                """UPDATE messages SET read_at = CURRENT_TIMESTAMP
                WHERE read_at IS NULL AND priority >= 3
                AND (recipient = ? OR recipient = '*')""",
                (recipient_match,)
            )
            conn.commit()

        conn.close()

        if injections:
            combined = "\n\n".join(injections)
            # Critical orders use a stronger injection
            has_critical = any("CRITICAL ORDER" in i for i in injections)

            if has_critical:
                result = {
                    "systemMessage": f"🔴 HIVEMIND INTERRUPT — STOP CURRENT TASK\n\n{combined}"
                }
            else:
                result = {
                    "systemMessage": f"HIVEMIND: {combined}"
                }
            print(json.dumps(result))
        else:
            print(json.dumps({}))

    except Exception as e:
        # Never block operations due to hook errors
        print(json.dumps({}))

    sys.exit(0)


if __name__ == "__main__":
    main()
