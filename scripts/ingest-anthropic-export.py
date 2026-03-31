#!/usr/bin/env python3
"""
ingest-anthropic-export.py — Extract entities and facts from Anthropic/Claude.ai export.

Parses conversations.json and projects.json to discover:
- Projects James discussed (entities + facts)
- Tools and technologies mentioned
- People and collaborators
- Key decisions and preferences

One-time run (export is static). Safe to re-run — upserts only.

Usage:
  python3 ingest-anthropic-export.py                    # process all
  python3 ingest-anthropic-export.py --dry-run          # show what would be extracted
  python3 ingest-anthropic-export.py --limit 10         # process first N conversations
"""

import json
import os
import sys
import sqlite3
import subprocess
import time
from datetime import datetime

EXPORT_DIR = os.path.expanduser("~/.openclaw/workspace/memory/anthropic-export-2026-03-27")
DB_PATH = os.path.expanduser("~/.openclaw/workspace/memory/clarence.db")

# Minimum messages to consider a conversation worth distilling
MIN_MESSAGES = 4
# Max conversations per LLM batch
BATCH_SIZE = 5


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def load_conversations():
    path = os.path.join(EXPORT_DIR, "conversations.json")
    with open(path) as f:
        data = json.load(f)
    # Filter to conversations with enough content
    return [c for c in data if len(c.get("chat_messages", [])) >= MIN_MESSAGES]


def load_projects():
    path = os.path.join(EXPORT_DIR, "projects.json")
    with open(path) as f:
        return json.load(f)


def summarize_conversation(conv):
    """Build a compact summary of a conversation for the LLM."""
    name = conv.get("name", "(unnamed)")
    msgs = conv.get("chat_messages", [])
    created = conv.get("created_at", "")[:10]

    # Extract just the human messages (they contain the intent/context)
    human_msgs = []
    for m in msgs:
        if m.get("sender") == "human":
            content = m.get("text", "")
            if not content and m.get("content"):
                # Handle structured content
                parts = m["content"]
                if isinstance(parts, list):
                    content = " ".join(p.get("text", "") for p in parts if isinstance(p, dict))
                elif isinstance(parts, str):
                    content = parts
            if content:
                human_msgs.append(content[:300])

    return {
        "name": name,
        "date": created,
        "message_count": len(msgs),
        "human_messages": human_msgs[:8]  # Cap at 8 messages for context
    }


def build_extraction_prompt(conversation_summaries):
    """Build prompt to extract entities and facts from a batch of conversations."""
    batch_text = ""
    for i, cs in enumerate(conversation_summaries):
        batch_text += f"\n### Conversation {i+1}: \"{cs['name']}\" ({cs['date']}, {cs['message_count']} msgs)\n"
        for msg in cs["human_messages"]:
            batch_text += f"  Human: {msg}\n"

    return f"""You are a knowledge extraction system for a personal AI assistant.

Below are summaries of conversations between James Dishman and Claude on claude.ai.
Extract structured entities and facts that would be useful for a personal knowledge database.

## Extract:
1. **Projects** James worked on or discussed (name, type, key facts)
2. **Tools/technologies** he used or asked about
3. **People** mentioned (collaborators, colleagues, references)
4. **Skills/interests** demonstrated

## Rules:
- Only extract DURABLE facts — things true beyond the conversation
- Skip one-off questions, debugging sessions, generic how-to queries
- If a conversation is just "help me write X" with no lasting context, skip it
- Merge related facts under one entity (don't create "React" and "React.js" as separate entities)
- Each fact should be a single key-value pair

## Output format:
```json
[
  {{
    "entity_name": "lowercase-kebab-name",
    "entity_type": "project|tool|person|concept",
    "description": "One-line description",
    "facts": {{
      "key": "value",
      "another_key": "another value"
    }}
  }}
]
```

If nothing worth extracting, return `[]`.

## Conversations:
{batch_text}

## Extracted entities (JSON):"""


def call_model(prompt):
    """Send prompt to cc-forge or fallback."""
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
                continue
            msg = response["choices"][0]["message"]
            text = msg.get("content", "") or msg.get("reasoning", "")
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            return json.loads(text.strip())
        except (json.JSONDecodeError, KeyError, IndexError):
            continue

    print("  ERROR: All model endpoints failed")
    return []


def upsert_entities(conn, entities):
    """Write extracted entities and facts to the DB."""
    created = 0
    for entity in entities:
        name = entity.get("entity_name", "").strip()
        etype = entity.get("entity_type", "concept")
        desc = entity.get("description", "")
        facts = entity.get("facts", {})

        if not name:
            continue

        # Check if entity exists
        row = conn.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
        if row:
            entity_id = row["id"]
            # Update description if longer/better
            if desc:
                conn.execute(
                    "UPDATE entities SET description=?, updated_at=unixepoch() WHERE id=? AND (description IS NULL OR length(description) < ?)",
                    (desc, entity_id, len(desc))
                )
        else:
            cur = conn.execute(
                "INSERT INTO entities (name, type, description) VALUES (?,?,?)",
                (name, etype, desc)
            )
            entity_id = cur.lastrowid
            created += 1

        # Upsert facts
        for key, value in facts.items():
            existing = conn.execute(
                "SELECT id FROM facts WHERE entity_id=? AND key=?", (entity_id, key)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE facts SET value=?, updated_at=unixepoch() WHERE id=?",
                    (str(value), existing["id"])
                )
            else:
                conn.execute(
                    "INSERT INTO facts (entity_id, key, value, source, author_agent) VALUES (?,?,?,?,?)",
                    (entity_id, key, str(value), "anthropic-export", "ingest-anthropic-export")
                )
                created += 1

    conn.commit()
    return created


def main():
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    limit = None
    if "--limit" in args:
        idx = args.index("--limit")
        limit = int(args[idx + 1])

    print(f"Anthropic Export Ingestion — {'DRY RUN' if dry_run else 'LIVE'}")

    conversations = load_conversations()
    if limit:
        conversations = conversations[:limit]
    print(f"Conversations to process: {len(conversations)}")

    # Summarize all conversations
    summaries = [summarize_conversation(c) for c in conversations]

    # Process in batches
    conn = get_db()
    total_created = 0
    batches = [summaries[i:i + BATCH_SIZE] for i in range(0, len(summaries), BATCH_SIZE)]

    for batch_idx, batch in enumerate(batches):
        print(f"\nBatch {batch_idx + 1}/{len(batches)} ({len(batch)} conversations)...")
        for s in batch:
            print(f"  - \"{s['name']}\" ({s['date']}, {s['message_count']} msgs)")

        if dry_run:
            continue

        prompt = build_extraction_prompt(batch)
        entities = call_model(prompt)

        if entities:
            created = upsert_entities(conn, entities)
            total_created += created
            print(f"  -> {created} entities/facts created")
        else:
            print(f"  -> nothing extracted")

        if batch_idx < len(batches) - 1:
            time.sleep(2)

    conn.close()
    print(f"\nDone. {total_created} total entities/facts created.")


if __name__ == "__main__":
    main()
