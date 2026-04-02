---
description: Build a deployment kit to clone this machine's full capabilities onto a new device
argument-hint: "[output-path]"
allowed-tools: ["Bash", "Read"]
---

# Deploy Agent Kit

Packages everything needed to make a new device as capable as this one:
- hivemind.db (shared brain)
- Both plugins (biz-ops + hivemind)
- CLAUDE.md, primer.md, memory system
- Settings, rules, permissions
- Shell alias
- One-command installer

## Execution

```bash
python3 ~/.openclaw/workspace/claude-code/plugins/hivemind/scripts/deploy_agent.py $ARGUMENTS
```

If `$ARGUMENTS` is empty, output goes to `~/.openclaw/workspace/`.

## After Building

Tell the user:
1. Copy the kit folder to the target device (USB, network share, OneDrive, etc.)
2. On the target device, run: `python3 install.py [CALLSIGN]`
3. That's it — the device is now a fully operational hivemind agent

## For Ongoing Sync

The kit is a one-time bootstrap. For ongoing brain sync, the user needs to set up
hivemind.db sharing between devices. Options:
- **OneDrive/Google Drive**: Symlink hivemind.db to a synced folder
- **Syncthing**: Real-time P2P sync (best for local network)
- **Network share**: Point all devices to a shared location
- **Git**: Commit hivemind.db to a private repo (works but has merge conflicts)
