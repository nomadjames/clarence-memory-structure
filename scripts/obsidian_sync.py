#!/usr/bin/env python3
"""
Obsidian <-> Clarence DB bidirectional sync.

vault_to_db: reads vault markdown notes, upserts entities/memories into DB
db_to_vault: writes agent-generated session logs and work items back to vault

Run directly or as a cron job. Safe to run repeatedly.
"""
import sqlite3
import os
import re
import json
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = os.path.expanduser("~/.openclaw/workspace/memory/clarence.db")
VAULT_PATH = os.path.expanduser("~/vault")
AGENT_NOTES_DIR = os.path.join(VAULT_PATH, "Agent Notes")

# Folders to sync from vault → DB
VAULT_SYNC_DIRS = ["Projects", "Reference", "Daily"]

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def parse_frontmatter(content):
    meta = {}
    body = content
    match = re.match(r'^---\n(.*?)\n---\n?(.*)', content, re.DOTALL)
    if match:
        for line in match.group(1).splitlines():
            if ':' in line:
                k, _, v = line.partition(':')
                meta[k.strip()] = v.strip()
        body = match.group(2).strip()
    return meta, body

def vault_to_db():
    """Sync vault notes → DB entities/memories."""
    conn = get_conn()
    synced, skipped = 0, 0

    for folder in VAULT_SYNC_DIRS:
        folder_path = os.path.join(VAULT_PATH, folder)
        if not os.path.isdir(folder_path):
            continue

        for fname in os.listdir(folder_path):
            if not fname.endswith('.md'):
                continue

            fpath = os.path.join(folder_path, fname)
            rel_path = os.path.relpath(fpath, VAULT_PATH)
            with open(fpath, 'r') as f:
                content = f.read()

            meta, body = parse_frontmatter(content)
            name = meta.get('name') or fname.replace('.md', '')
            mtime = int(os.path.getmtime(fpath))

            # Check sync log
            row = conn.execute(
                "SELECT last_synced FROM obsidian_sync WHERE vault_path=? AND direction='vault_to_db'",
                (rel_path,)
            ).fetchone()

            if row and row['last_synced'] >= mtime:
                skipped += 1
                continue

            # Determine entity type from folder
            if folder == "Projects":
                etype = "project"
                # Upsert as entity
                existing = conn.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE entities SET description=?, obsidian_path=?, updated_at=unixepoch() WHERE id=?",
                        (body[:200], rel_path, existing['id'])
                    )
                else:
                    conn.execute(
                        "INSERT INTO entities (name, type, description, obsidian_path) VALUES (?,?,?,?)",
                        (name, etype, body[:200], rel_path)
                    )
            elif folder == "Daily":
                # Store daily notes as session summaries
                date_match = re.match(r'(\d{4}-\d{2}-\d{2})', fname)
                sid = date_match.group(1) if date_match else fname.replace('.md', '')
                conn.execute(
                    """INSERT OR REPLACE INTO sessions (session_id, summary, obsidian_path)
                       VALUES (?,?,?)""",
                    (sid, body[:500], rel_path)
                )
            elif folder == "Reference":
                mtype = meta.get('type', 'reference')
                desc = meta.get('description', body[:100])
                conn.execute(
                    """INSERT OR REPLACE INTO memories (name, type, description, body, obsidian_path)
                       VALUES (?,?,?,?,?)""",
                    (name, mtype, desc, body, rel_path)
                )

            # Update sync log
            conn.execute(
                """INSERT OR REPLACE INTO obsidian_sync (vault_path, table_name, last_synced, direction)
                   VALUES (?,?,unixepoch(),?)""",
                (rel_path, folder.lower(), 'vault_to_db')
            )
            synced += 1

    conn.commit()
    conn.close()
    print(f"vault_to_db: {synced} synced, {skipped} up-to-date")

def db_to_vault():
    """Write recent sessions and work items back to vault as Agent Notes."""
    os.makedirs(AGENT_NOTES_DIR, exist_ok=True)
    conn = get_conn()

    # Write session summaries not yet in vault
    sessions = conn.execute(
        """SELECT s.* FROM sessions s
           LEFT JOIN obsidian_sync os ON os.vault_path LIKE 'Agent Notes/session-%' AND os.direction='db_to_vault'
           WHERE s.obsidian_path IS NULL
           ORDER BY s.started_at DESC LIMIT 10"""
    ).fetchall()

    for s in sessions:
        sid = s['session_id']
        fname = f"session-{sid}.md"
        fpath = os.path.join(AGENT_NOTES_DIR, fname)
        rel_path = os.path.relpath(fpath, VAULT_PATH)

        work = json.loads(s['work_done'] or '[]')
        decisions = json.loads(s['key_decisions'] or '[]')

        content = f"""---
type: session
session_id: {sid}
date: {datetime.fromtimestamp(s['started_at'] or 0, tz=timezone.utc).strftime('%Y-%m-%d') if s['started_at'] else 'unknown'}
---

# Session: {sid}

## Summary
{s['summary'] or 'No summary logged.'}

## Work Done
{''.join(f'- {w}' + chr(10) for w in work) if work else '- (none logged)'}

## Key Decisions
{''.join(f'- {d}' + chr(10) for d in decisions) if decisions else '- (none logged)'}
"""
        with open(fpath, 'w') as f:
            f.write(content)

        # Update session and sync log
        conn.execute(
            "UPDATE sessions SET obsidian_path=? WHERE session_id=?",
            (rel_path, sid)
        )
        conn.execute(
            """INSERT OR REPLACE INTO obsidian_sync (vault_path, table_name, last_synced, direction)
               VALUES (?,?,unixepoch(),?)""",
            (rel_path, 'sessions', 'db_to_vault')
        )

    # Write a work log summary note (rolling, updates each sync)
    work_items = conn.execute(
        "SELECT * FROM work_items ORDER BY created_at DESC LIMIT 50"
    ).fetchall()

    if work_items:
        today = datetime.now().strftime('%Y-%m-%d')
        fpath = os.path.join(AGENT_NOTES_DIR, "work-log.md")
        lines = [f"---\ntype: work-log\nupdated: {today}\n---\n\n# Work Log\n\n"]
        for w in work_items:
            ts = datetime.fromtimestamp(w['created_at'], tz=timezone.utc).strftime('%Y-%m-%d')
            status_icon = {"done": "✓", "todo": "○", "in_progress": "→", "blocked": "✗"}.get(w['status'], "·")
            lines.append(f"- {status_icon} [{ts}] **{w['title']}** `{w['type']}`")
            if w['description']:
                lines.append(f"  {w['description']}")
            lines.append("")
        with open(fpath, 'w') as f:
            f.write('\n'.join(lines))

    conn.commit()
    conn.close()
    print(f"db_to_vault: wrote {len(sessions)} session notes + work log")

def full_sync():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Obsidian sync starting...")
    vault_to_db()
    db_to_vault()
    print("Sync complete.")

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        if sys.argv[1] == "vault_to_db":
            vault_to_db()
        elif sys.argv[1] == "db_to_vault":
            db_to_vault()
        else:
            print(f"Unknown direction: {sys.argv[1]}")
    else:
        full_sync()
