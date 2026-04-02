#!/usr/bin/env python3
"""Initialize the hivemind database — the shared brain between all Claude instances.

Three systems in one db:
  1. Message Bus — agents post/read messages to coordinate
  2. Learning Engine — corrections, patterns, preferences extracted from sessions
  3. Task Queue — daemon picks up tasks and spawns Claude to handle them
"""

import sqlite3
import os
import sys

DB_PATH = os.path.expanduser("~/hivemind.db")


def init():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # === MESSAGE BUS ===
    # Agents post messages, other agents read them
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            recipient TEXT DEFAULT '*',
            channel TEXT DEFAULT 'general',
            content TEXT NOT NULL,
            msg_type TEXT DEFAULT 'info',
            priority INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            read_at TIMESTAMP,
            expires_at TIMESTAMP
        )
    """)

    # === LEARNING ENGINE ===
    # Every correction, preference, pattern extracted from sessions
    c.execute("""
        CREATE TABLE IF NOT EXISTS learnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            rule TEXT NOT NULL,
            context TEXT,
            source_session TEXT,
            confidence REAL DEFAULT 0.5,
            times_applied INTEGER DEFAULT 0,
            times_helpful INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_applied TIMESTAMP,
            active INTEGER DEFAULT 1
        )
    """)
    # Categories: correction, preference, pattern, mistake, insight

    # === TASK QUEUE ===
    # Daemon watches this table, spawns Claude when tasks appear
    c.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            prompt TEXT NOT NULL,
            working_dir TEXT,
            trigger_type TEXT DEFAULT 'manual',
            cron_schedule TEXT,
            status TEXT DEFAULT 'pending',
            priority INTEGER DEFAULT 0,
            max_retries INTEGER DEFAULT 1,
            retry_count INTEGER DEFAULT 0,
            result TEXT,
            error TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMP,
            completed_at TIMESTAMP,
            next_run TIMESTAMP
        )
    """)
    # trigger_type: manual, cron, file_watch, webhook, message

    # === AGENT REGISTRY (with military hierarchy) ===
    # Rank determines authority. Higher rank = can assign tasks to lower ranks.
    # Chain of command: Commander > General > Colonel > Captain > Lieutenant > Sergeant > Private
    c.execute("""
        CREATE TABLE IF NOT EXISTS agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id TEXT UNIQUE NOT NULL,
            name TEXT,
            callsign TEXT,
            role TEXT,
            rank TEXT DEFAULT 'private',
            rank_level INTEGER DEFAULT 1,
            reports_to TEXT,
            division TEXT DEFAULT 'general',
            specialization TEXT,
            device TEXT,
            status TEXT DEFAULT 'active',
            pid INTEGER,
            working_dir TEXT,
            tasks_completed INTEGER DEFAULT 0,
            tasks_failed INTEGER DEFAULT 0,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_heartbeat TIMESTAMP,
            ended_at TIMESTAMP,
            FOREIGN KEY (reports_to) REFERENCES agents(agent_id)
        )
    """)

    # === CHAIN OF COMMAND ===
    # Defines who can assign tasks to whom and approval flows
    c.execute("""
        CREATE TABLE IF NOT EXISTS chain_of_command (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            division TEXT NOT NULL,
            rank TEXT NOT NULL,
            rank_level INTEGER NOT NULL,
            can_assign_to TEXT,
            can_approve INTEGER DEFAULT 0,
            can_spawn INTEGER DEFAULT 0,
            max_direct_reports INTEGER DEFAULT 5
        )
    """)

    # Seed rank structure
    ranks = [
        ('all', 'commander', 7, '*', 1, 1, 100),
        ('all', 'general', 6, 'colonel,captain,lieutenant,sergeant,private', 1, 1, 20),
        ('all', 'colonel', 5, 'captain,lieutenant,sergeant,private', 1, 1, 10),
        ('all', 'captain', 4, 'lieutenant,sergeant,private', 0, 1, 5),
        ('all', 'lieutenant', 3, 'sergeant,private', 0, 1, 3),
        ('all', 'sergeant', 2, 'private', 0, 0, 3),
        ('all', 'private', 1, None, 0, 0, 0),
    ]
    for div, rank, level, assigns, approve, spawn, reports in ranks:
        c.execute(
            """INSERT OR IGNORE INTO chain_of_command
            (division, rank, rank_level, can_assign_to, can_approve, can_spawn, max_direct_reports)
            VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (div, rank, level, assigns, approve, spawn, reports)
        )

    # === ORDERS ===
    # Formal task assignments through the chain of command
    c.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            issued_by TEXT NOT NULL,
            assigned_to TEXT NOT NULL,
            order_type TEXT DEFAULT 'task',
            priority TEXT DEFAULT 'normal',
            objective TEXT NOT NULL,
            details TEXT,
            constraints TEXT,
            deadline TIMESTAMP,
            status TEXT DEFAULT 'issued',
            accepted_at TIMESTAMP,
            completed_at TIMESTAMP,
            report TEXT,
            parent_order_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (issued_by) REFERENCES agents(agent_id),
            FOREIGN KEY (assigned_to) REFERENCES agents(agent_id),
            FOREIGN KEY (parent_order_id) REFERENCES orders(id)
        )
    """)
    # order_type: task, recon, review, build, deploy, report
    # priority: critical, high, normal, low
    # status: issued, accepted, in_progress, completed, failed, cancelled

    # === DIVISIONS ===
    # Organizational units for specialization
    c.execute("""
        CREATE TABLE IF NOT EXISTS divisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            mission TEXT,
            commander_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (commander_id) REFERENCES agents(agent_id)
        )
    """)

    # Seed default divisions
    divisions = [
        ('engineering', 'Build and ship software products'),
        ('intelligence', 'Research, analysis, and competitive intel'),
        ('operations', 'Business ops, CRM, deals, communications'),
        ('security', 'Code review, vulnerability scanning, compliance'),
        ('logistics', 'Deployments, infrastructure, DevOps'),
    ]
    for name, mission in divisions:
        c.execute(
            "INSERT OR IGNORE INTO divisions (name, mission) VALUES (?, ?)",
            (name, mission)
        )

    # === SESSION LOG ===
    # What happened in each session (for learning extraction)
    c.execute("""
        CREATE TABLE IF NOT EXISTS session_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            content TEXT,
            metadata TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # event_type: correction, success, error, decision, preference

    # === FILE WATCHES ===
    # Daemon monitors these paths and triggers tasks on change
    c.execute("""
        CREATE TABLE IF NOT EXISTS watches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL,
            pattern TEXT DEFAULT '*',
            task_id INTEGER,
            prompt TEXT,
            active INTEGER DEFAULT 1,
            last_triggered TIMESTAMP,
            FOREIGN KEY (task_id) REFERENCES tasks(id)
        )
    """)

    # === DESKTOP ACTIONS LOG ===
    # Record desktop automation actions for replay/learning
    c.execute("""
        CREATE TABLE IF NOT EXISTS desktop_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            target TEXT,
            parameters TEXT,
            screenshot_before TEXT,
            screenshot_after TEXT,
            success INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    conn.close()
    print(f"Hivemind database initialized at {DB_PATH}")
    return DB_PATH


if __name__ == "__main__":
    init()
