---
description: Hivemind command center — send messages, check agents, manage the daemon, view learnings
argument-hint: "send [msg] | agents | learnings | status | daemon start|stop | task [prompt] | watch [path]"
allowed-tools: ["Bash", "Read"]
---

# Hivemind Command Center

Parse `$ARGUMENTS` and route to the correct operation.

**Database:** `~/hivemind.db`

## Commands

### `/hivemind send [message]`
Post a message to all active agents across all devices:
```bash
sqlite3 ~/hivemind.db "INSERT INTO messages (sender, recipient, channel, content, msg_type) VALUES ('$(hostname):manual', '*', 'general', '$MESSAGE', 'info')"
```

### `/hivemind send [agent-name] [message]`
Send a direct message to a specific agent:
```bash
sqlite3 ~/hivemind.db "INSERT INTO messages (sender, recipient, channel, content, msg_type) VALUES ('$(hostname):manual', '$AGENT', 'direct', '$MESSAGE', 'info')"
```

### `/hivemind agents`
Show all active agents across all devices:
```bash
sqlite3 -header -column ~/hivemind.db "SELECT agent_id, name, role, status, working_dir, last_heartbeat FROM agents WHERE status='active' OR last_heartbeat > datetime('now', '-1 hour') ORDER BY last_heartbeat DESC"
```

### `/hivemind learnings`
Show all active learnings:
```bash
sqlite3 -header -column ~/hivemind.db "SELECT id, category, rule, confidence, times_applied, created_at FROM learnings WHERE active=1 ORDER BY confidence DESC, times_applied DESC"
```

### `/hivemind learn [category] [rule]`
Manually add a learning:
```bash
sqlite3 ~/hivemind.db "INSERT INTO learnings (category, rule, confidence) VALUES ('$CATEGORY', '$RULE', 0.9)"
```
Categories: correction, preference, pattern, mistake, insight

### `/hivemind forget [id]`
Deactivate a learning:
```bash
sqlite3 ~/hivemind.db "UPDATE learnings SET active=0 WHERE id=$ID"
```

### `/hivemind status`
Full system status:
```bash
echo "=== HIVEMIND STATUS ==="
echo "--- Agents ---"
sqlite3 -header -column ~/hivemind.db "SELECT agent_id, name, status, last_heartbeat FROM agents ORDER BY last_heartbeat DESC LIMIT 10"
echo "--- Unread Messages ---"
sqlite3 -header -column ~/hivemind.db "SELECT id, sender, content, created_at FROM messages WHERE read_at IS NULL ORDER BY created_at DESC LIMIT 10"
echo "--- Active Learnings ---"
sqlite3 ~/hivemind.db "SELECT COUNT(*) || ' learnings active' FROM learnings WHERE active=1"
echo "--- Pending Tasks ---"
sqlite3 -header -column ~/hivemind.db "SELECT id, name, status, created_at FROM tasks WHERE status IN ('pending', 'running') ORDER BY priority DESC"
echo "--- Daemon ---"
cat ~/hivemind.pid 2>/dev/null && echo " (running)" || echo "Not running"
```

### `/hivemind daemon start`
Start the background daemon:
```bash
cd ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts && nohup python3 daemon.py > /dev/null 2>&1 &
echo "Daemon started (PID $!)"
```

### `/hivemind daemon stop`
Stop the daemon:
```bash
if [ -f ~/hivemind.pid ]; then
  kill $(cat ~/hivemind.pid) 2>/dev/null && echo "Daemon stopped" || echo "Daemon not running"
  rm -f ~/hivemind.pid
else
  echo "No PID file found"
fi
```

### `/hivemind task [prompt]`
Queue a task for the daemon to run autonomously:
```bash
sqlite3 ~/hivemind.db "INSERT INTO tasks (name, prompt, trigger_type, status) VALUES ('manual:$(date +%H%M)', '$PROMPT', 'manual', 'pending')"
echo "Task queued. Daemon will pick it up on next poll cycle."
```

### `/hivemind watch [path] [prompt]`
Add a file watcher — daemon triggers Claude when files change:
```bash
sqlite3 ~/hivemind.db "INSERT INTO watches (path, prompt, active) VALUES ('$PATH', '$PROMPT', 1)"
echo "Watch added. Daemon will monitor $PATH."
```

### `/hivemind inbox`
Read messages from other agents:
```bash
sqlite3 -header -column ~/hivemind.db "SELECT sender, content, created_at FROM messages WHERE read_at IS NULL ORDER BY priority DESC, created_at DESC LIMIT 20"
sqlite3 ~/hivemind.db "UPDATE messages SET read_at=CURRENT_TIMESTAMP WHERE read_at IS NULL"
```

### `/hivemind sync`
Sync messages, orders, and learnings with other devices via OneDrive:
```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/sync.py sync --shared ~/OneDrive/hivemind-sync
```
This exports local data to a JSON file in OneDrive, then imports any new data from other devices. Run on both machines to complete a sync cycle.

## Execution Notes
- Always use `sqlite3 ~/hivemind.db` for all database operations
- Escape single quotes in SQL by doubling them
- If hivemind.db doesn't exist, run: `python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/init_db.py`
- For multi-device sync, each device keeps its OWN hivemind.db. Use `/hivemind sync` to exchange data via OneDrive.
