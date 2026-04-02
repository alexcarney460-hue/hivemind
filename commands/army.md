---
description: Manage the agent army — ranks, divisions, chain of command, orders, promotions, and battle readiness
argument-hint: "roster | order [agent] [objective] | promote [agent] | divisions | sitrep | recruit [name] [rank] [division]"
allowed-tools: ["Bash", "Read"]
---

# Army Command — Hierarchical Agent Management

Military-grade chain of command for multi-agent operations.

**Database:** `~/hivemind.db`

## Rank Structure

| Rank | Level | Can Assign To | Can Approve | Can Spawn |
|------|-------|---------------|-------------|-----------|
| Commander | 7 | Everyone | Yes | Yes |
| General | 6 | Colonel and below | Yes | Yes |
| Colonel | 5 | Captain and below | Yes | Yes |
| Captain | 4 | Lieutenant and below | No | Yes |
| Lieutenant | 3 | Sergeant and below | No | Yes |
| Sergeant | 2 | Private | No | No |
| Private | 1 | Nobody | No | No |

## Commands

### `/army roster`
Show full roster with ranks, divisions, and status:
```bash
sqlite3 -header -column ~/hivemind.db "
SELECT 
  a.callsign || ' (' || a.name || ')' as agent,
  a.rank,
  a.rank_level as lvl,
  a.division,
  a.specialization as spec,
  a.device,
  a.status,
  a.tasks_completed as done,
  a.tasks_failed as fail,
  a.last_heartbeat as last_seen
FROM agents a
ORDER BY a.rank_level DESC, a.division, a.name
"
```

### `/army recruit [callsign] [rank] [division] [specialization]`
Add a new agent to the roster:
```bash
sqlite3 ~/hivemind.db "INSERT INTO agents (agent_id, name, callsign, rank, rank_level, division, specialization, device, status) VALUES ('$CALLSIGN', '$NAME', '$CALLSIGN', '$RANK', (SELECT rank_level FROM chain_of_command WHERE rank='$RANK' LIMIT 1), '$DIVISION', '$SPEC', '$(hostname)', 'standby')"
```

Example recruits for a 3-device team:
- `/army recruit ALPHA commander engineering "full-stack development"` — The human operator
- `/army recruit BRAVO general intelligence "research and analysis"` — Device 2 lead
- `/army recruit CHARLIE colonel operations "business ops and CRM"` — Device 3 lead
- `/army recruit DELTA captain engineering "frontend development"` — Worker
- `/army recruit ECHO captain security "code review and testing"` — Worker
- `/army recruit FOXTROT sergeant logistics "deployment and DevOps"` — Worker

### `/army order [callsign] [objective]`
Issue an order through chain of command. Only works if issuer outranks the target:
```bash
sqlite3 ~/hivemind.db "INSERT INTO orders (issued_by, assigned_to, objective, priority, status) VALUES ('$ISSUER', '$TARGET', '$OBJECTIVE', 'normal', 'issued')"
```
Also post to message bus so the target agent sees it on next session start:
```bash
sqlite3 ~/hivemind.db "INSERT INTO messages (sender, recipient, channel, content, msg_type, priority) VALUES ('$ISSUER', '$TARGET', 'orders', 'ORDER: $OBJECTIVE', 'task_request', 5)"
```

### `/army promote [callsign]`
Promote an agent one rank:
```bash
sqlite3 ~/hivemind.db "UPDATE agents SET rank_level = rank_level + 1, rank = (SELECT rank FROM chain_of_command WHERE rank_level = (SELECT rank_level + 1 FROM agents WHERE callsign='$CALLSIGN') LIMIT 1) WHERE callsign='$CALLSIGN'"
```

### `/army demote [callsign]`
Demote an agent one rank:
```bash
sqlite3 ~/hivemind.db "UPDATE agents SET rank_level = MAX(1, rank_level - 1), rank = (SELECT rank FROM chain_of_command WHERE rank_level = (SELECT MAX(1, rank_level - 1) FROM agents WHERE callsign='$CALLSIGN') LIMIT 1) WHERE callsign='$CALLSIGN'"
```

### `/army divisions`
Show all divisions and their agents:
```bash
sqlite3 -header -column ~/hivemind.db "
SELECT d.name as division, d.mission,
  (SELECT COUNT(*) FROM agents WHERE division=d.name AND status='active') as active_agents,
  (SELECT GROUP_CONCAT(callsign, ', ') FROM agents WHERE division=d.name ORDER BY rank_level DESC) as roster
FROM divisions d
ORDER BY d.name
"
```

### `/army sitrep`
Situation report — full operational status:
```bash
echo "════════════════════════════════════"
echo "  SITUATION REPORT — $(date '+%Y-%m-%d %H:%M')"
echo "════════════════════════════════════"
echo ""
echo "FORCE STRENGTH:"
sqlite3 ~/hivemind.db "SELECT rank, COUNT(*) as count FROM agents GROUP BY rank ORDER BY (SELECT rank_level FROM chain_of_command c WHERE c.rank=agents.rank LIMIT 1) DESC"
echo ""
echo "DIVISION STATUS:"
sqlite3 ~/hivemind.db "SELECT division, COUNT(*) as agents, SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) as active FROM agents GROUP BY division"
echo ""
echo "PENDING ORDERS:"
sqlite3 -header -column ~/hivemind.db "SELECT id, assigned_to, priority, objective, status FROM orders WHERE status IN ('issued', 'accepted', 'in_progress') ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END"
echo ""
echo "RECENT COMPLETIONS:"
sqlite3 -header -column ~/hivemind.db "SELECT assigned_to, objective, completed_at FROM orders WHERE status='completed' ORDER BY completed_at DESC LIMIT 5"
echo ""
echo "AGENTS OFFLINE (>5min):"
sqlite3 ~/hivemind.db "SELECT callsign, device, last_heartbeat FROM agents WHERE status='active' AND last_heartbeat < datetime('now', '-5 minutes')"
echo ""
echo "UNREAD MESSAGES: $(sqlite3 ~/hivemind.db 'SELECT COUNT(*) FROM messages WHERE read_at IS NULL')"
echo "════════════════════════════════════"
```

### `/army assign [callsign] to [division]`
Transfer an agent to a different division:
```bash
sqlite3 ~/hivemind.db "UPDATE agents SET division='$DIVISION' WHERE callsign='$CALLSIGN'"
```

### `/army chain`
Show the full chain of command:
```bash
sqlite3 -header -column ~/hivemind.db "
SELECT a.callsign, a.rank, a.rank_level, a.division,
  (SELECT b.callsign FROM agents b WHERE b.agent_id = a.reports_to) as reports_to,
  (SELECT COUNT(*) FROM agents c WHERE c.reports_to = a.agent_id) as direct_reports
FROM agents a
WHERE a.status IN ('active', 'standby')
ORDER BY a.rank_level DESC, a.division
"
```

### `/army orders`
Show all active orders:
```bash
sqlite3 -header -column ~/hivemind.db "
SELECT o.id, o.issued_by, o.assigned_to, o.priority, o.objective, o.status, o.created_at
FROM orders o
WHERE o.status NOT IN ('completed', 'cancelled')
ORDER BY CASE o.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'normal' THEN 2 ELSE 3 END, o.created_at
"
```

### `/army complete [order_id] [report]`
Mark an order as completed with an after-action report:
```bash
sqlite3 ~/hivemind.db "UPDATE orders SET status='completed', completed_at=CURRENT_TIMESTAMP, report='$REPORT' WHERE id=$ORDER_ID"
```
Also update the agent's task count:
```bash
sqlite3 ~/hivemind.db "UPDATE agents SET tasks_completed = tasks_completed + 1 WHERE agent_id = (SELECT assigned_to FROM orders WHERE id=$ORDER_ID)"
```

## Workflow: How Orders Flow

1. **Commander** (you) issues a high-level order: `/army order BRAVO "Research best Supabase auth patterns for YieldRadar"`
2. **General BRAVO** receives the order on their next session start
3. BRAVO can decompose it and issue sub-orders to lower ranks
4. Workers complete sub-tasks and report back up the chain
5. BRAVO consolidates results and posts to hivemind message bus
6. Commander sees the completed report in `/hivemind inbox`

## Multi-Device Deployment

- **Device 1 (Desktop):** Commander + Engineering division
- **Device 2 (Laptop):** Intelligence + Operations division  
- **Device 3 (Server/Cloud):** Logistics + autonomous daemon tasks
