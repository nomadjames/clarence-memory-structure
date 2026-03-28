#!/usr/bin/env python3
"""
vault_indexer.py — Syncs Obsidian brain/ vault to SQLite for unified querying.
No external deps — uses stdlib only (re, sqlite3, pathlib, datetime).
"""
import re
import sqlite3
import os
from pathlib import Path
from datetime import datetime

VAULT_DIR = Path.home() / ".openclaw/workspace/brain"
DB_PATH = Path.home() / ".openclaw/workspace/memory/clarence.db"


def parse_frontmatter(text):
    """Extract YAML frontmatter from markdown text. Returns (metadata dict, body).
    
    Handles files with or without explicit --- YAML blocks.
    Falls back to extracting title/date from content headers if no frontmatter.
    """
    text = text.lstrip()  # Remove leading blank lines
    
    # Check for YAML frontmatter block
    if text.startswith('---'):
        match = re.match(r'^---\s*\n(.*?)\n---\s*\n(.*)$', text, re.DOTALL)
        if match:
            raw_yaml, body = match.group(1), match.group(2)
            meta = {}
            for line in raw_yaml.splitlines():
                m = re.match(r'^(\w+):\s*(.*)$', line.strip())
                if m:
                    key, val = m.group(1), m.group(2).strip()
                    if val.startswith('['):
                        val = val.strip('[]').replace(',', ',')
                    meta[key] = val
            return meta, body
    
    # No frontmatter — extract from content headers
    body = text
    meta = {}
    
    # First H1 becomes title
    h1_match = re.search(r'^#\s+(.+)$', body, re.MULTILINE)
    if h1_match:
        meta["title"] = h1_match.group(1).strip()
    
    # First H2 becomes topic
    h2_match = re.search(r'^##\s+(.+)$', body, re.MULTILINE)
    if h2_match:
        meta["topic"] = h2_match.group(1).strip()
    
    return meta, body


def extract_title(body):
    """Get title from first H1, or **bold**, or first meaningful line."""
    lines = body.strip().splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # H1
        m = re.match(r'^#\s+(.+)$', line)
        if m:
            return m.group(1).strip()
        # Bold text at start
        m = re.match(r'^\*\*(.+)\*\*', line)
        if m:
            return m.group(1).strip()
        # Return first non-empty line
        return line[:80]
    return "Untitled"


def extract_summary(body, max_chars=300):
    """Strip markdown, return plain text summary."""
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', body)  # links
    text = re.sub(r'[#*_`~>-]', ' ', text)  # markdown chars
    text = re.sub(r'\s+', ' ', text).strip()
    return text[:max_chars]


def parse_file(filepath):
    try:
        text = filepath.read_text(encoding="utf-8", errors="ignore")
        meta, body = parse_frontmatter(text)
        return {
            "file": str(filepath),
            "topic": meta.get("topic", ""),
            "project": meta.get("project", ""),
            "date": meta.get("date", ""),
            "status": meta.get("status", ""),
            "tags": meta.get("tags", ""),
            "title": meta.get("title", extract_title(body)),
            "summary": extract_summary(body),
            "updated": datetime.fromtimestamp(filepath.stat().st_mtime).strftime("%Y-%m-%d")
        }
    except Exception as e:
        return None


def ensure_table(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS vault_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE,
            topic TEXT,
            project TEXT,
            date TEXT,
            status TEXT,
            tags TEXT,
            title TEXT,
            summary TEXT,
            updated TEXT,
            indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()


def index_vault(conn):
    cursor = conn.cursor()
    indexed = 0
    errors = 0
    
    for md_file in VAULT_DIR.rglob("*.md"):
        if any(p.startswith(".") for p in md_file.parts):
            continue
        
        parsed = parse_file(md_file)
        if not parsed:
            errors += 1
            continue
        
        try:
            cursor.execute("""
                INSERT INTO vault_notes 
                    (file_path, topic, project, date, status, tags, title, summary, updated)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_path) DO UPDATE SET
                    topic=excluded.topic,
                    project=excluded.project,
                    date=excluded.date,
                    status=excluded.status,
                    tags=excluded.tags,
                    title=excluded.title,
                    summary=excluded.summary,
                    updated=excluded.updated,
                    indexed_at=CURRENT_TIMESTAMP
            """, (
                parsed["file"], parsed["topic"], parsed["project"],
                parsed["date"], parsed["status"], parsed["tags"],
                parsed["title"], parsed["summary"], parsed["updated"]
            ))
            indexed += 1
        except Exception as e:
            print(f"  DB error {md_file.name}: {e}")
    
    conn.commit()
    return indexed, errors


def main():
    print(f"Vault: {VAULT_DIR}")
    print(f"DB: {DB_PATH}")
    
    if not VAULT_DIR.exists():
        print("Vault dir not found")
        return
    
    conn = sqlite3.connect(DB_PATH)
    ensure_table(conn)
    indexed, errors = index_vault(conn)
    
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM vault_notes")
    total = cursor.fetchone()[0]
    
    print(f"Indexed: {indexed} | Errors: {errors} | Total notes in DB: {total}")
    
    print("\nRecent notes:")
    cursor.execute("SELECT title, project, updated FROM vault_notes ORDER BY updated DESC LIMIT 8")
    for row in cursor.fetchall():
        print(f"  [{row[2]}] {row[0]} | {row[1]}")
    
    conn.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
