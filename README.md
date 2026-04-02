# Hivemind — Persistent Autonomous Agent Network for Claude Code

A Claude Code plugin that gives AI agents capabilities they don't natively have: inter-agent communication, autonomous operation, cross-session learning, desktop control, and multi-device coordination with military-grade hierarchy.

## What This Does

Claude Code sessions are isolated, amnesiac, and die when you close the terminal. Hivemind fixes that.

| Capability | Before | After |
|-----------|--------|-------|
| **Communication** | Sessions can't talk to each other | Shared message bus across all devices |
| **Persistence** | Dies when terminal closes | Daemon runs 24/7, spawns Claude autonomously |
| **Learning** | Forgets corrections next session | Extracts, stores, and loads learnings automatically |
| **Desktop** | Blind outside the terminal | Screenshots, clicks, typing, window control, OCR |
| **Coordination** | No structure, work gets dropped | Military hierarchy with ranks, divisions, and orders |

## Architecture

```
                    ┌─────────────────┐
                    │   hivemind.db   │  ← Shared brain (SQLite)
                    └────────┬────────┘
           ┌─────────────┬───┴───┬──────────────┐
           │             │       │              │
    ┌──────┴──────┐ ┌────┴───┐ ┌─┴──────┐ ┌────┴─────┐
    │ Message Bus │ │Learning│ │Task    │ │ Desktop  │
    │             │ │Engine  │ │Queue   │ │ Control  │
    │ agents post │ │auto-   │ │daemon  │ │ see +    │
    │ & receive   │ │extracts│ │spawns  │ │ click +  │
    │ messages    │ │from    │ │Claude  │ │ type     │
    │ across      │ │every   │ │on cron │ │ any app  │
    │ devices     │ │session │ │& watch │ │          │
    └─────────────┘ └────────┘ └────────┘ └──────────┘
           │             │         │            │
    ┌──────┴─────────────┴─────────┴────────────┴──────┐
    │          Order Injector (PreToolUse hook)         │
    │  Force-injects orders into active sessions.      │
    │  Agents CANNOT miss messages — no voluntary       │
    │  checking required. Orders interrupt in-progress  │
    │  work based on priority level.                    │
    └──────────────────────────────────────────────────┘
```

## Quick Start

```bash
# 1. Clone
git clone https://github.com/anthropics/hivemind.git
cd hivemind

# 2. Install dependencies
python3 -m pip install pyautogui Pillow

# 3. Initialize the database
python3 scripts/init_db.py

# 4. Start Claude Code with Hivemind
claude --dangerously-skip-permissions --plugin-dir /path/to/hivemind

# Or create an alias
alias cc='claude --dangerously-skip-permissions --plugin-dir "/path/to/hivemind"'
```

## Commands

### Agent Communication
| Command | Description |
|---------|-------------|
| `/hivemind status` | Full system overview — agents, messages, learnings, tasks |
| `/hivemind send [msg]` | Broadcast to all agents on all devices |
| `/hivemind send [agent] [msg]` | Direct message to a specific agent |
| `/hivemind inbox` | Read messages from other agents |
| `/hivemind agents` | List all active agents |
| `/hivemind learnings` | Show what the network has learned |
| `/hivemind daemon start` | Start the background daemon |

### Teaching & Learning
| Command | Description |
|---------|-------------|
| `/teach [category] [lesson]` | Share a discovery with all agents |
| `/hivemind learn [cat] [rule]` | Manually add a learning |
| `/hivemind forget [id]` | Remove a bad learning |

Categories: `pattern`, `insight`, `technique`, `warning`, `context`

### Military Hierarchy
| Command | Description |
|---------|-------------|
| `/army roster` | Full roster with ranks, divisions, stats |
| `/army order [callsign] [objective]` | Issue an order (respects chain of command) |
| `/army sitrep` | Situation report — full operational status |
| `/army promote [callsign]` | Promote an agent |
| `/army divisions` | Show organizational units |
| `/army recruit [callsign] [rank] [division]` | Add a new agent |
| `/army complete [order_id] [report]` | Mark an order done |

**Rank structure:** Commander (7) → General (6) → Colonel (5) → Captain (4) → Lieutenant (3) → Sergeant (2) → Private (1)

**Divisions:** Engineering, Intelligence, Operations, Security, Logistics

### Autonomous Operations
| Command | Description |
|---------|-------------|
| `/auto every [N]m [prompt]` | Recurring task every N minutes |
| `/auto watch [path] [prompt]` | Trigger Claude on file changes |
| `/auto run [prompt]` | One-shot headless execution |
| `/auto list` | Show all scheduled tasks |
| `/auto cancel [id]` | Cancel a task |

### Desktop Control
| Command | Description |
|---------|-------------|
| `/desktop screenshot` | Capture and view the screen |
| `/desktop click [x] [y]` | Click at coordinates |
| `/desktop type [text]` | Type at cursor |
| `/desktop hotkey [keys]` | Key combo (e.g., ctrl c) |
| `/desktop windows` | List all open windows |
| `/desktop focus [title]` | Bring window to front |
| `/desktop ocr` | Extract text from screen |

### Deployment
| Command | Description |
|---------|-------------|
| `/deploy` | Build a kit to clone capabilities to a new device |

## How Order Delivery Works

The #1 problem with multi-agent systems: **agents forget to check for messages.** Hivemind solves this with forced injection.

A `PreToolUse` hook fires before every tool call (throttled to once per 10 seconds). It reads `hivemind.db` and injects any pending orders directly into the agent's context. The agent never "checks" for messages — messages force themselves in.

```
Priority Levels:
  CRITICAL  →  "🔴 HALT. Acknowledge before continuing."
  HIGH      →  "Accept when ready."
  NORMAL    →  "You have N pending orders."
```

**Agents cannot miss orders. Period.**

## How Learning Works

Four learning channels feed into the same `learnings` table:

1. **Human corrections** — `UserPromptSubmit` hook detects "don't/stop/wrong" (confidence: 0.8)
2. **Manual teaching** — `/teach` command from any agent (confidence: 0.9)
3. **Auto-discovery** — `SubagentStop` hook evaluates if a subagent learned something (confidence: 0.7)
4. **Session extraction** — `Stop` hook reviews the session for patterns (confidence: 0.7)

All learnings propagate to every agent on every device via the `SessionStart` hook.

## Multi-Device Setup

```
Device A (Desktop)     Device B (Laptop)     Device C (Phone)
  ├── Claude session    ├── Claude session    ├── Claude (Termux)
  ├── Daemon            ├── Daemon            └── Receives orders
  └── Desktop control   └── Desktop control
        │                     │                     │
        └─────────────────────┴─────────────────────┘
                          hivemind.db
                      (synced across all)
```

**Sync options:** OneDrive, Syncthing, network share, or the deploy script for initial setup.

### Deploy to a New Device

```bash
# On the primary machine
python3 scripts/deploy_agent.py

# Copy the generated kit to the new device, then:
python3 install.py [CALLSIGN]
```

The installer copies: plugins, config, memory, settings, learnings, and the shell alias.

## Database Schema

`hivemind.db` contains 10 tables:

| Table | Purpose |
|-------|---------|
| `messages` | Agent-to-agent message bus |
| `agents` | Registry with rank, division, device, stats |
| `chain_of_command` | Rank permissions (who can assign to whom) |
| `orders` | Formal task assignments through hierarchy |
| `divisions` | Organizational units |
| `learnings` | Corrections, patterns, preferences |
| `tasks` | Autonomous task queue for daemon |
| `watches` | File change triggers |
| `session_log` | Per-session event history |
| `desktop_actions` | GUI automation log |

## Hooks

| Hook | Event | Purpose |
|------|-------|---------|
| `session_start.py` | SessionStart | Load learnings + messages + show active agents |
| `session_stop.py` | Stop | Extract learnings, post handoff, mark inactive |
| `learn_from_correction.py` | UserPromptSubmit | Detect corrections in real-time |
| `order_injector.py` | PreToolUse | Force-inject orders into active sessions |
| SubagentStop prompt | SubagentStop | Auto-extract learnings from subagent work |

## Requirements

- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview) (v2.0+)
- Python 3.10+
- `pyautogui` + `Pillow` (for desktop control)
- Optional: `pytesseract` + Tesseract OCR binary (for screen text extraction)

## License

MIT
