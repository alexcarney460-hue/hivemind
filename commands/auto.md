---
description: Schedule autonomous tasks — Claude runs without you. Cron jobs, file watchers, recurring prompts.
argument-hint: "every [N]m [prompt] | watch [path] [prompt] | list | cancel [id]"
allowed-tools: ["Bash", "Read"]
---

# Autonomous Task Scheduling

Schedule tasks that the hivemind daemon executes without human presence.

**Requires daemon running:** `/hivemind daemon start`

## Commands

### `/auto every [N]m [prompt]`
Run a task every N minutes:
```bash
sqlite3 ~/hivemind.db "INSERT INTO tasks (name, prompt, trigger_type, cron_schedule, status) VALUES ('cron:$PROMPT_SHORT', '$PROMPT', 'cron', '$N', 'pending')"
```
Examples:
- `/auto every 30m check git status in all workspace repos and post summary to hivemind`
- `/auto every 60m query brain.db for deals updated today and send report to hivemind`
- `/auto every 15m check YieldRadar Supabase for new signups`

### `/auto watch [path] [prompt]`
Trigger Claude when files at path change:
```bash
sqlite3 ~/hivemind.db "INSERT INTO watches (path, prompt, active) VALUES ('$PATH', '$PROMPT', 1)"
```
Examples:
- `/auto watch ~/brain.db when brain.db changes, post new deals to hivemind`
- `/auto watch ~/.openclaw/workspace/yieldradar/src run tests when source changes`

### `/auto run [prompt]`
Queue a one-shot task for immediate autonomous execution:
```bash
sqlite3 ~/hivemind.db "INSERT INTO tasks (name, prompt, trigger_type, status, priority) VALUES ('oneshot:$(date +%s)', '$PROMPT', 'manual', 'pending', 5)"
```
This runs Claude headless — no human in the loop. Claude gets the prompt, does the work, posts results to hivemind messages.

### `/auto list`
Show all scheduled and active tasks:
```bash
echo "=== SCHEDULED TASKS ==="
sqlite3 -header -column ~/hivemind.db "SELECT id, name, trigger_type, cron_schedule, status, next_run FROM tasks WHERE trigger_type='cron' ORDER BY next_run"
echo ""
echo "=== FILE WATCHES ==="
sqlite3 -header -column ~/hivemind.db "SELECT id, path, pattern, active, last_triggered FROM watches ORDER BY id"
echo ""
echo "=== RECENT TASKS ==="
sqlite3 -header -column ~/hivemind.db "SELECT id, name, status, started_at, completed_at FROM tasks ORDER BY created_at DESC LIMIT 10"
```

### `/auto cancel [id]`
Cancel a scheduled task:
```bash
sqlite3 ~/hivemind.db "UPDATE tasks SET status='cancelled' WHERE id=$ID"
```

### `/auto pause [id]`
Pause a file watch:
```bash
sqlite3 ~/hivemind.db "UPDATE watches SET active=0 WHERE id=$ID"
```

### `/auto resume [id]`
Resume a paused file watch:
```bash
sqlite3 ~/hivemind.db "UPDATE watches SET active=1 WHERE id=$ID"
```

### `/auto logs`
Show recent daemon activity:
```bash
LOGDIR=~/.openclaw/workspace/hivemind-logs
LATEST=$(ls -t "$LOGDIR"/*.log 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
  tail -30 "$LATEST"
else
  echo "No logs found. Is the daemon running?"
fi
```

## How It Works
1. You schedule a task or watch
2. The daemon (running in background) polls every 30 seconds
3. When triggered, daemon spawns `claude -p "your prompt" --allowedTools "*"`
4. Claude runs headless, completes the task, posts results to hivemind messages
5. Next time you open a session, SessionStart hook shows you the results

## Multi-Device
If hivemind.db is synced across devices (OneDrive, Syncthing, etc.), any device's daemon can pick up tasks. The agent registry prevents double-execution.
