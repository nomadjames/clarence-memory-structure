#!/usr/bin/env python3
"""
conversation-distill.py — Extract durable knowledge from Telegram conversations.

Reads OpenClaw session JSONL files, extracts the human-side conversation,
distills it into structured memory entries (decisions, corrections, preferences,
project context), and writes them to clarence.db.

This is NOT a raw dump. It extracts signal from noise.

Usage:
  python3 conversation-distill.py                    # distill last 24h of sessions
  python3 conversation-distill.py --hours 72         # custom window
  python3 conversation-distill.py --backfill         # process ALL sessions (first run)
  python3 conversation-distill.py --dry-run          # show what would be extracted
  python3 conversation-distill.py --session FILE     # process a specific session file
  python3 conversation-distill.py --max-batches 10   # cap batches per session (resumes next run)
"""

import json
import os
import sys
import sqlite3
import hashlib
import time
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = os.path.expanduser("~/.openclaw/workspace/memory/clarence.db")
SESSIONS_DIR = os.path.expanduser("~/.openclaw/agents/main/sessions")
ARCHIVE_DIR = os.path.join(SESSIONS_DIR, "archive")
STATE_FILE = os.path.expanduser("~/.openclaw/workspace/memory/distill-state.json")

# Minimum message length to consider (skip "ok", "yes", "👍", etc.)
MIN_MSG_LEN = 30
# Maximum conversation pairs to include in one distill batch
MAX_PAIRS_PER_BATCH = 40


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # Create the distill tracking table if needed
    conn.execute("""
        CREATE TABLE IF NOT EXISTS conversation_distills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_file TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            distilled_at INTEGER DEFAULT (unixepoch()),
            entries_created INTEGER DEFAULT 0,
            window_start TEXT,
            window_end TEXT
        )
    """)
    # Track batch-level progress for large sessions
    conn.execute("""
        CREATE TABLE IF NOT EXISTS distill_batch_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_file TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            batch_index INTEGER NOT NULL,
            total_batches INTEGER NOT NULL,
            entries_created INTEGER DEFAULT 0,
            processed_at INTEGER DEFAULT (unixepoch()),
            UNIQUE(session_file, file_hash, batch_index)
        )
    """)
    conn.commit()
    return conn


def already_distilled(conn, filepath, file_hash):
    """Check if we've already processed this exact file content."""
    row = conn.execute(
        "SELECT id FROM conversation_distills WHERE session_file=? AND file_hash=?",
        (os.path.basename(filepath), file_hash)
    ).fetchone()
    return row is not None


def file_hash(filepath):
    """Quick hash of file to detect changes."""
    h = hashlib.md5()
    with open(filepath, "rb") as f:
        # Hash first 10KB + last 10KB + size (fast enough for change detection)
        h.update(f.read(10240))
        f.seek(0, 2)
        size = f.tell()
        h.update(str(size).encode())
        if size > 10240:
            f.seek(-10240, 2)
            h.update(f.read(10240))
    return h.hexdigest()


def extract_conversation(filepath):
    """Extract user/assistant message pairs from a session JSONL file."""
    pairs = []
    current_user = None
    timestamps = []

    with open(filepath) as f:
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg = obj.get("message", {})
            role = msg.get("role", "")
            content = msg.get("content", "")
            ts = obj.get("timestamp", "")

            # Extract text from content (handle both string and list formats)
            text = ""
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(item.get("text", ""))
                text = "\n".join(parts)

            # Strip Telegram metadata wrapper to get actual message
            if "```\n\n" in text:
                text = text.split("```\n\n", 1)[-1].strip()
            # Also strip tool results and system messages
            if role in ("system", "tool"):
                continue

            if role == "user" and len(text) >= MIN_MSG_LEN:
                current_user = text[:2000]  # Cap individual messages
                if ts:
                    timestamps.append(ts)
            elif role == "assistant" and current_user:
                # Get the assistant's text response (skip tool calls)
                assistant_text = ""
                if isinstance(content, str):
                    assistant_text = content[:2000]
                elif isinstance(content, list):
                    text_parts = []
                    for item in content:
                        if isinstance(item, dict) and item.get("type") == "text":
                            text_parts.append(item.get("text", ""))
                    assistant_text = "\n".join(text_parts)[:2000]

                if assistant_text and len(assistant_text) >= MIN_MSG_LEN:
                    pairs.append({
                        "user": current_user,
                        "assistant": assistant_text,
                        "timestamp": ts or (timestamps[-1] if timestamps else "")
                    })
                current_user = None

    return pairs, timestamps


def build_distill_prompt(pairs, session_name, date_range):
    """Build the prompt that asks the model to distill conversation into memories."""
    # Truncate to manageable size
    if len(pairs) > MAX_PAIRS_PER_BATCH:
        pairs = pairs[-MAX_PAIRS_PER_BATCH:]

    conversation_text = ""
    for p in pairs:
        ts = p.get("timestamp", "")[:19] if p.get("timestamp") else ""
        conversation_text += f"\n[{ts}] James: {p['user']}\n"
        conversation_text += f"Clarence: {p['assistant'][:500]}\n"

    return f"""You are a memory distillation system for Clarence (an AI assistant).

Below is a conversation between James and Clarence from {date_range}.
Your job: extract ONLY the durable, reusable knowledge — things that should persist across sessions.

## Extract these categories:

1. **DECISIONS** — James decided something ("let's use X", "we're going with Y", "forget Z")
2. **CORRECTIONS** — James corrected Clarence ("no, not that", "that's wrong", "don't do X")
3. **PREFERENCES** — James expressed a preference ("I prefer X", "I like when you Y", emotional reactions)
4. **PROJECT_UPDATES** — Status changes, new info about ongoing work
5. **PERSONAL_CONTEXT** — Anything about James's life, feelings, goals that helps Clarence serve him better

## Rules:
- Skip greetings, small talk, routine commands ("run this", "check that")
- Skip tool output, error messages, technical debugging back-and-forth
- Only extract things that would be USEFUL in a FUTURE conversation
- Each entry should be 1-3 sentences, factual, specific
- Include the approximate date/time if it matters for context
- Output valid JSON array

## Output format:
```json
[
  {{
    "type": "decision|correction|preference|project_update|personal_context",
    "name": "short-kebab-case-title",
    "description": "One-line summary for search/index",
    "body": "The full context. What happened, what was decided, why it matters.",
    "tags": ["relevant", "topic", "tags"]
  }}
]
```

If there is nothing worth extracting, return an empty array: `[]`

## Conversation ({session_name}, {date_range}):
{conversation_text}

## Extracted memories (JSON):"""


def distill_with_model(prompt):
    """Send the distill prompt to a model and parse the result."""
    import subprocess

    # Try cc-forge first, fall back to Ollama
    endpoints = [
        ("http://127.0.0.1:8321/v1/chat/completions", "cc-forge", "gemini-2.0-flash", 4096),
        ("http://127.0.0.1:11434/v1/chat/completions", "OLLAMA_API_KEY", "minimax-m2.7:cloud", 4096),
    ]

    for url, key, model, max_tokens in endpoints:
        result = subprocess.run(
            [
                "curl", "-s", "--max-time", "120", url,
                "-H", "Content-Type: application/json",
                "-H", f"Authorization: Bearer {key}",
                "-d", json.dumps({
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": max_tokens,
                    "temperature": 0.1
                })
            ],
            capture_output=True, text=True, timeout=130
        )

        if result.returncode != 0:
            continue

        try:
            response = json.loads(result.stdout)
            if "error" in response:
                continue  # Try next endpoint
            msg = response["choices"][0]["message"]
            text = msg.get("content", "") or msg.get("reasoning", "")
            # Extract JSON from markdown code block if wrapped
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text.strip())
        except (json.JSONDecodeError, KeyError, IndexError) as e:
            continue  # Try next endpoint

    print(f"  ERROR: All model endpoints failed")
    return []


def write_memories(conn, entries, source_session):
    """Write distilled entries to clarence.db as memories."""
    created = 0
    for entry in entries:
        name = f"conv:{entry.get('name', 'unknown')}"
        mem_type = entry.get("type", "project")
        # Map conversation types to memory DB types
        type_map = {
            "decision": "project",
            "correction": "feedback",
            "preference": "feedback",
            "project_update": "project",
            "personal_context": "user"
        }
        db_type = type_map.get(mem_type, "project")
        description = entry.get("description", "")
        body = entry.get("body", "")
        tags = json.dumps(entry.get("tags", []) + ["conversation-distill", source_session[:8]])

        try:
            conn.execute(
                """INSERT INTO memories (name, type, description, body, tags, author_agent)
                   VALUES (?, ?, ?, ?, ?, 'conversation-distill')""",
                (name, db_type, description, body, tags)
            )
            created += 1
        except sqlite3.IntegrityError:
            # Memory with this name already exists — update if body is different
            existing = conn.execute(
                "SELECT body FROM memories WHERE name=?", (name,)
            ).fetchone()
            if existing and existing["body"] != body:
                conn.execute(
                    """UPDATE memories SET body=?, description=?, tags=?, updated_at=unixepoch()
                       WHERE name=?""",
                    (body, description, tags, name)
                )
                created += 1

    conn.commit()
    return created


def get_completed_batches(conn, fname, fhash):
    """Get set of batch indices already processed for this session file."""
    rows = conn.execute(
        "SELECT batch_index FROM distill_batch_progress WHERE session_file=? AND file_hash=?",
        (fname, fhash)
    ).fetchall()
    return {r["batch_index"] for r in rows}


def record_batch(conn, fname, fhash, batch_idx, total_batches, entries_created):
    """Record that a batch was processed."""
    conn.execute(
        """INSERT OR REPLACE INTO distill_batch_progress
           (session_file, file_hash, batch_index, total_batches, entries_created)
           VALUES (?, ?, ?, ?, ?)""",
        (fname, fhash, batch_idx, total_batches, entries_created)
    )
    conn.commit()


def process_session(conn, filepath, dry_run=False, max_batches=None):
    """Process a single session file. Returns (entries_created, is_complete)."""
    fname = os.path.basename(filepath)
    fhash = file_hash(filepath)

    if already_distilled(conn, filepath, fhash):
        return 0, True

    pairs, timestamps = extract_conversation(filepath)
    if not pairs:
        return 0, True

    # Skip cron-only sessions (1-2 pairs, typically automated reports)
    if len(pairs) < 3:
        return 0, True

    # Determine date range
    if timestamps:
        date_range = f"{timestamps[0][:10]} to {timestamps[-1][:10]}"
    else:
        date_range = "unknown dates"

    # Process in batches for large sessions
    batch_size = MAX_PAIRS_PER_BATCH
    batches = [pairs[i:i + batch_size] for i in range(0, len(pairs), batch_size)]
    completed_batches = get_completed_batches(conn, fname, fhash)

    # Find remaining batches
    remaining = [(i, b) for i, b in enumerate(batches) if i not in completed_batches]
    if not remaining:
        # All batches done but not marked complete — finalize now
        total_created = sum(
            r["entries_created"] for r in conn.execute(
                "SELECT entries_created FROM distill_batch_progress WHERE session_file=? AND file_hash=?",
                (fname, fhash)
            ).fetchall()
        )
        conn.execute(
            """INSERT INTO conversation_distills (session_file, file_hash, entries_created, window_start, window_end)
               VALUES (?, ?, ?, ?, ?)""",
            (fname, fhash, total_created,
             timestamps[0] if timestamps else None,
             timestamps[-1] if timestamps else None)
        )
        conn.commit()
        return 0, True

    skipped = len(completed_batches)
    print(f"  {fname[:12]}... — {len(pairs)} pairs, {len(batches)} batches ({skipped} already done, {len(remaining)} remaining)")

    if dry_run:
        for p in pairs[:3]:
            print(f"    James: {p['user'][:80]}")
            print(f"    Clarence: {p['assistant'][:80]}")
            print()
        return 0, True

    # Cap batches per run if specified
    if max_batches is not None:
        remaining = remaining[:max_batches]

    created = 0
    for batch_idx, batch in remaining:
        print(f"    batch {batch_idx + 1}/{len(batches)}...")
        batch_ts = [p.get("timestamp", "") for p in batch if p.get("timestamp")]
        batch_range = f"{batch_ts[0][:10] if batch_ts else '?'} to {batch_ts[-1][:10] if batch_ts else '?'}"

        prompt = build_distill_prompt(batch, fname[:12], batch_range)
        entries = distill_with_model(prompt)

        batch_created = 0
        if entries:
            batch_created = write_memories(conn, entries, fname)
            created += batch_created
            print(f"    -> batch {batch_idx + 1}: {batch_created} memories")
        else:
            print(f"    -> batch {batch_idx + 1}: nothing worth extracting")

        record_batch(conn, fname, fhash, batch_idx, len(batches), batch_created)

        # Brief pause between batches to avoid rate limits
        if batch_idx < remaining[-1][0]:
            time.sleep(2)

    # Check if ALL batches are now done
    all_completed = get_completed_batches(conn, fname, fhash)
    is_complete = len(all_completed) >= len(batches)

    if is_complete:
        total_created = sum(
            r["entries_created"] for r in conn.execute(
                "SELECT entries_created FROM distill_batch_progress WHERE session_file=? AND file_hash=?",
                (fname, fhash)
            ).fetchall()
        )
        conn.execute(
            """INSERT INTO conversation_distills (session_file, file_hash, entries_created, window_start, window_end)
               VALUES (?, ?, ?, ?, ?)""",
            (fname, fhash, total_created,
             timestamps[0] if timestamps else None,
             timestamps[-1] if timestamps else None)
        )
        conn.commit()
        print(f"    -> session complete: {total_created} total memories")

    return created, is_complete


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    backfill = "--backfill" in args
    hours = 24
    max_batches = None

    if "--hours" in args:
        idx = args.index("--hours")
        hours = int(args[idx + 1])

    if "--max-batches" in args:
        idx = args.index("--max-batches")
        max_batches = int(args[idx + 1])

    specific_session = None
    if "--session" in args:
        idx = args.index("--session")
        specific_session = args[idx + 1]

    conn = get_db()

    if specific_session:
        files = [specific_session]
    else:
        cutoff = time.time() - (hours * 3600) if not backfill else 0
        files = []
        # Active sessions
        for fname in os.listdir(SESSIONS_DIR):
            if not fname.endswith(".jsonl"):
                continue
            fpath = os.path.join(SESSIONS_DIR, fname)
            if os.path.getmtime(fpath) >= cutoff:
                files.append(fpath)
        # Also check archive for backfill
        if backfill and os.path.isdir(ARCHIVE_DIR):
            import gzip
            for fname in os.listdir(ARCHIVE_DIR):
                if fname.endswith(".jsonl.gz"):
                    # Decompress to temp for processing
                    fpath = os.path.join(ARCHIVE_DIR, fname)
                    tmp = f"/tmp/distill-{fname}.jsonl"
                    with gzip.open(fpath, "rb") as gz, open(tmp, "wb") as out:
                        out.write(gz.read())
                    files.append(tmp)

    files.sort(key=lambda f: os.path.getmtime(f) if os.path.exists(f) else 0)

    print(f"Conversation Distill — {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"Sessions to process: {len(files)}")
    if max_batches:
        print(f"Max batches per session: {max_batches}")
    print()

    total_created = 0
    incomplete = 0
    for fpath in files:
        try:
            created, is_complete = process_session(conn, fpath, dry_run=dry_run, max_batches=max_batches)
            total_created += created
            if not is_complete:
                incomplete += 1
        except Exception as e:
            print(f"  ERROR processing {os.path.basename(fpath)}: {e}")

    # Clean up temp files
    for fpath in files:
        if fpath.startswith("/tmp/distill-"):
            try:
                os.remove(fpath)
            except OSError:
                pass

    print(f"\nDone. {total_created} total memories created.")
    if incomplete:
        print(f"{incomplete} session(s) partially processed — will resume on next run.")
    conn.close()


if __name__ == "__main__":
    main()
