#!/usr/bin/env python3
"""
Brain MCP Server — Placeholder / Reference Implementation

The "brain" MCP server provides higher-level read tools that aggregate
across the memory database. It is a companion to the memory MCP server,
which handles raw CRUD operations.

In the current Clarence deployment, the memory-mcp/server.py handles
all tool calls directly (including entity_get, profile_get, etc.).

This file is a reference for how a higher-level brain layer could be
structured — e.g., for tools that join across tables, summarize recent
activity, or provide a "session context" bundle.

See memory-mcp/server.py for the full working implementation.
"""

import json
import sqlite3
import sys
import os
from datetime import datetime, timedelta

DB_PATH = os.path.expanduser("~/.openclaw/workspace/memory/clarence.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# ── Higher-Level Brain Tools ──────────────────────────────────────────────────

def brain_context_bundle(hours_back: int = 48):
    """
    Return a bundle of recent context for session startup:
    - Recent work items
    - Recent sessions
    - Active project memories
    - Recent interactions (corrections/preferences)
    """
    conn = get_conn()
    cutoff = int((datetime.now() - timedelta(hours=hours_back)).timestamp())

    recent_work = conn.execute(
        "SELECT title, type, status, description FROM work_items WHERE created_at > ? ORDER BY created_at DESC LIMIT 10",
        (cutoff,)
    ).fetchall()

    recent_sessions = conn.execute(
        "SELECT session_id, summary, started_at FROM sessions WHERE started_at > ? ORDER BY started_at DESC LIMIT 5",
        (cutoff,)
    ).fetchall()

    project_memories = conn.execute(
        "SELECT name, description, body FROM memories WHERE type='project' AND status='active' ORDER BY updated_at DESC LIMIT 10"
    ).fetchall()

    recent_interactions = conn.execute(
        "SELECT type, content, created_at FROM interactions WHERE created_at > ? ORDER BY created_at DESC LIMIT 10",
        (cutoff,)
    ).fetchall()

    conn.close()
    return {
        "recent_work": [dict(r) for r in recent_work],
        "recent_sessions": [dict(r) for r in recent_sessions],
        "project_memories": [dict(r) for r in project_memories],
        "recent_interactions": [dict(r) for r in recent_interactions],
    }


def brain_daily_summary(date: str = None):
    """Get the daily log summary for a given date (YYYY-MM-DD). Defaults to today."""
    conn = get_conn()
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    row = conn.execute("SELECT * FROM daily_logs WHERE date=?", (date,)).fetchone()
    conn.close()
    return dict(row) if row else {"date": date, "summary": None}


# ── MCP Protocol ──────────────────────────────────────────────────────────────

def send(obj):
    print(json.dumps(obj), flush=True)

def respond(id, result):
    send({"jsonrpc": "2.0", "id": id, "result": result})

def error(id, code, message):
    send({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})


TOOLS = {
    "brain_context_bundle": {
        "description": "Get a bundle of recent context for session startup: recent work, sessions, project memories, and interactions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hours_back": {"type": "integer", "description": "How far back to look (default 48 hours)"}
            }
        }
    },
    "brain_daily_summary": {
        "description": "Get the daily log summary for a given date (YYYY-MM-DD). Defaults to today.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format. Omit for today."}
            }
        }
    },
}

DISPATCH = {
    "brain_context_bundle": lambda a: brain_context_bundle(**a),
    "brain_daily_summary": lambda a: brain_daily_summary(**a),
}


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        id = msg.get("id")

        if method == "initialize":
            respond(id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "clarence-brain", "version": "1.0.0"}
            })

        elif method == "tools/list":
            respond(id, {
                "tools": [
                    {"name": k, "description": v["description"], "inputSchema": v["inputSchema"]}
                    for k, v in TOOLS.items()
                ]
            })

        elif method == "tools/call":
            name = msg.get("params", {}).get("name")
            args = msg.get("params", {}).get("arguments", {})
            if name in DISPATCH:
                try:
                    result = DISPATCH[name](args)
                    respond(id, {
                        "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                    })
                except Exception as e:
                    error(id, -32000, str(e))
            else:
                error(id, -32601, f"Unknown tool: {name}")

        elif method == "notifications/initialized":
            pass

        elif id is not None:
            error(id, -32601, f"Method not found: {method}")


if __name__ == "__main__":
    main()
