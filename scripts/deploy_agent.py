#!/usr/bin/env python3
"""Deploy Agent Kit — packages everything needed to make a new device
as capable as the primary machine.

Creates a self-contained deployment folder that gets copied to the new device.
Once there, run `python3 install.py` and the device is fully operational.

What gets packaged:
  1. hivemind.db (the shared brain)
  2. Both plugins (biz-ops + hivemind)
  3. CLAUDE.md, primer.md, memory system
  4. Shell config (.bashrc alias)
  5. Settings (hooks, permissions)
  6. Install script that wires everything up on the target
"""

import os
import sys
import shutil
import json
from pathlib import Path
from datetime import datetime

HOME = os.path.expanduser("~")
WORKSPACE = os.path.join(HOME, ".openclaw", "workspace")
CLAUDE_DIR = os.path.join(HOME, ".claude")


def create_kit(output_dir=None):
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    kit_name = f"hivemind-deploy-kit-{ts}"

    if output_dir:
        kit_path = os.path.join(output_dir, kit_name)
    else:
        kit_path = os.path.join(WORKSPACE, kit_name)

    os.makedirs(kit_path, exist_ok=True)
    print(f"Building deployment kit at: {kit_path}")

    # 1. Copy hivemind.db
    db_src = os.path.join(HOME, "hivemind.db")
    if os.path.exists(db_src):
        shutil.copy2(db_src, os.path.join(kit_path, "hivemind.db"))
        print("  + hivemind.db")

    # 2. Copy plugins
    plugins_src = os.path.join(WORKSPACE, "claude-code", "plugins")
    for plugin in ["biz-ops", "hivemind"]:
        src = os.path.join(plugins_src, plugin)
        dst = os.path.join(kit_path, "plugins", plugin)
        if os.path.exists(src):
            shutil.copytree(src, dst)
            print(f"  + plugins/{plugin}")

    # 3. Copy Claude config
    config_dst = os.path.join(kit_path, "claude-config")
    os.makedirs(config_dst, exist_ok=True)

    for fname in ["CLAUDE.md", "primer.md", "settings.json", "settings.local.json"]:
        src = os.path.join(CLAUDE_DIR, fname)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(config_dst, fname))
            print(f"  + claude-config/{fname}")

    # Copy rules
    rules_src = os.path.join(CLAUDE_DIR, "rules")
    if os.path.exists(rules_src):
        shutil.copytree(rules_src, os.path.join(config_dst, "rules"))
        print("  + claude-config/rules/")

    # Copy memory system
    # Find the memory dir (could be under different project paths)
    for dirpath, dirnames, filenames in os.walk(os.path.join(CLAUDE_DIR, "projects")):
        if "memory" in dirnames:
            mem_src = os.path.join(dirpath, "memory")
            shutil.copytree(mem_src, os.path.join(config_dst, "memory"))
            print("  + claude-config/memory/")
            break

    # 4. Create install script
    install_script = '''#!/usr/bin/env python3
"""Hivemind Agent Installer — run this on the new device.

Usage: python3 install.py [callsign]
Example: python3 install.py BRAVO
"""

import os
import sys
import shutil
from pathlib import Path

HOME = os.path.expanduser("~")
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def install(callsign=None):
    print(f"Installing Hivemind Agent Kit...")
    print(f"Home: {HOME}")

    # 1. Copy hivemind.db to home
    db_src = os.path.join(SCRIPT_DIR, "hivemind.db")
    db_dst = os.path.join(HOME, "hivemind.db")
    if os.path.exists(db_src):
        shutil.copy2(db_src, db_dst)
        print(f"  hivemind.db -> {db_dst}")

    # 2. Set up workspace and copy plugins
    workspace = os.path.join(HOME, ".openclaw", "workspace", "claude-code", "plugins")
    os.makedirs(workspace, exist_ok=True)

    plugins_src = os.path.join(SCRIPT_DIR, "plugins")
    if os.path.exists(plugins_src):
        for plugin in os.listdir(plugins_src):
            src = os.path.join(plugins_src, plugin)
            dst = os.path.join(workspace, plugin)
            if os.path.exists(dst):
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
            print(f"  plugin: {plugin} -> {dst}")

    # 3. Copy Claude config
    claude_dir = os.path.join(HOME, ".claude")
    os.makedirs(claude_dir, exist_ok=True)

    config_src = os.path.join(SCRIPT_DIR, "claude-config")
    if os.path.exists(config_src):
        for item in os.listdir(config_src):
            src = os.path.join(config_src, item)
            dst = os.path.join(claude_dir, item)
            if os.path.isdir(src):
                if os.path.exists(dst):
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            print(f"  config: {item} -> {dst}")

    # 4. Set up memory dir for this device
    # Create project-specific memory directory
    projects_dir = os.path.join(claude_dir, "projects")
    os.makedirs(projects_dir, exist_ok=True)

    # 5. Set up .bashrc alias
    bashrc = os.path.join(HOME, ".bashrc")
    alias_line = 'alias cc=\\'claude --dangerously-skip-permissions --plugin-dir "$HOME/.openclaw/workspace/claude-code/plugins/biz-ops" --plugin-dir "$HOME/.openclaw/workspace/claude-code/plugins/hivemind"\\''

    existing = ""
    if os.path.exists(bashrc):
        existing = open(bashrc).read()

    if "alias cc=" not in existing:
        with open(bashrc, "a") as f:
            f.write(f"\\n# Claude Code with hivemind + biz-ops\\n{alias_line}\\n")
        print(f"  alias cc -> .bashrc")
    else:
        print(f"  alias cc already exists in .bashrc")

    # 6. Install Python deps
    print("\\nInstalling Python dependencies...")
    os.system(f"{sys.executable} -m pip install pyautogui Pillow")

    # 7. Activate agent in hivemind
    if callsign:
        import sqlite3
        conn = sqlite3.connect(db_dst)
        hostname = os.environ.get("COMPUTERNAME", os.environ.get("HOSTNAME", "unknown"))
        conn.execute(
            "UPDATE agents SET device=?, status=\\'active\\' WHERE callsign=?",
            (hostname, callsign)
        )
        conn.commit()
        conn.close()
        print(f"\\n  Agent {callsign} activated on {hostname}")

    print("\\n=== INSTALLATION COMPLETE ===")
    print("Start Claude with: cc")
    print("Or: claude --plugin-dir ~/.openclaw/workspace/claude-code/plugins/biz-ops --plugin-dir ~/.openclaw/workspace/claude-code/plugins/hivemind")
    if callsign:
        print(f"\\nYou are agent {callsign}. Run /army sitrep to see your orders.")
    print("Run /hivemind daemon start to enable autonomous operation.")


if __name__ == "__main__":
    callsign = sys.argv[1] if len(sys.argv) > 1 else None
    install(callsign)
'''

    with open(os.path.join(kit_path, "install.py"), "w") as f:
        f.write(install_script)
    print("  + install.py")

    # 5. Create README for the kit
    readme = f"""# Hivemind Agent Deployment Kit
Generated: {datetime.now().strftime("%Y-%m-%d %H:%M")}
Source: {os.environ.get("COMPUTERNAME", "unknown")}

## Quick Install

1. Copy this entire folder to the target device
2. Open a terminal on the target device
3. Run: python3 install.py BRAVO
   (replace BRAVO with the agent's callsign)

## What Gets Installed
- hivemind.db (shared brain — agent communication, learnings, orders)
- biz-ops plugin (business commands, morning briefing, deployment)
- hivemind plugin (agent comms, desktop control, autonomous tasks, army)
- Claude Code config (settings, rules, memory)
- Shell alias (cc command)
- Python deps (pyautogui, Pillow)

## After Install
- Start Claude: cc
- Check status: /hivemind status
- See orders: /army sitrep
- Start daemon: /hivemind daemon start

## Sync Setup
For ongoing sync of hivemind.db between devices, use OneDrive, Syncthing, or a network share.
Point all devices to the same hivemind.db location.
"""

    with open(os.path.join(kit_path, "README.md"), "w") as f:
        f.write(readme)
    print("  + README.md")

    # Calculate kit size
    total_size = sum(
        os.path.getsize(os.path.join(dirpath, filename))
        for dirpath, dirnames, filenames in os.walk(kit_path)
        for filename in filenames
    )

    print(f"\nKit ready: {kit_path}")
    print(f"Size: {total_size / 1024 / 1024:.1f} MB")
    print(f"\nTo deploy: copy this folder to the target device and run:")
    print(f"  python3 install.py BRAVO")

    return kit_path


if __name__ == "__main__":
    output = sys.argv[1] if len(sys.argv) > 1 else None
    create_kit(output)
