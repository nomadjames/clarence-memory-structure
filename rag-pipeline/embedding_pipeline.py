#!/usr/bin/env python3
"""
RAG embedding script for Clarence knowledge DB.
Embeds all active memories and facts into sqlite-vec for semantic search.
Run nightly to keep vectors current.
"""

import sqlite3
import sqlite_vec
import struct
import json
import sys
import os
from datetime import datetime

DB_PATH = os.environ.get("CLARENCE_DB", "./clarence.db")
MODEL_NAME = "BAAI/bge-base-en-v1.5"
DIMS = 768

def get_embedding_model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)

def serialize(vector):
    """Pack float list into bytes for sqlite-vec."""
    return struct.pack(f"{len(vector)}f", *vector)

def setup_vec_tables(conn):
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories
        USING vec0(
            memory_id INTEGER PRIMARY KEY,
            embedding FLOAT[768]
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_facts
        USING vec0(
            fact_id INTEGER PRIMARY KEY,
            embedding FLOAT[768]
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rag_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()

def get_last_embed_run(conn):
    """Get the timestamp of the last embedding run."""
    row = conn.execute("SELECT value FROM rag_meta WHERE key = 'last_embed_run'").fetchone()
    if row:
        return int(row[0])
    return 0

def embed_memories(conn, model):
    last_run = get_last_embed_run(conn)

    rows = conn.execute("""
        SELECT id, name, description, body, updated_at
        FROM memories
        WHERE status = 'active'
    """).fetchall()

    if not rows:
        print("No active memories to embed.")
        return 0

    # Get already-embedded IDs
    existing = {r[0] for r in conn.execute("SELECT memory_id FROM vec_memories").fetchall()}

    # Find memories that are new OR updated since last embed run
    to_embed = []
    for r in rows:
        if r[0] not in existing:
            to_embed.append(r)
        elif r[4] and r[4] > last_run:
            # Memory was updated since last embed — delete old vector first
            conn.execute("DELETE FROM vec_memories WHERE memory_id = ?", (r[0],))
            to_embed.append(r)

    if not to_embed:
        print(f"All {len(rows)} memories already embedded and current.")
        return 0

    new_count = sum(1 for r in to_embed if r[0] not in existing)
    updated_count = len(to_embed) - new_count
    print(f"Embedding {len(to_embed)} memories ({new_count} new, {updated_count} updated, of {len(rows)} total)...")

    texts = [f"{r[1]}: {r[2] or ''}\n{r[3]}" for r in to_embed]
    embeddings = model.encode(texts, show_progress_bar=False)

    for row, emb in zip(to_embed, embeddings):
        conn.execute(
            "INSERT INTO vec_memories(memory_id, embedding) VALUES (?, ?)",
            (row[0], serialize(emb.tolist()))
        )
    conn.commit()
    return len(to_embed)

def embed_facts(conn, model):
    last_run = get_last_embed_run(conn)

    rows = conn.execute("""
        SELECT f.id, e.name, f.key, f.value, f.updated_at
        FROM facts f
        JOIN entities e ON f.entity_id = e.id
        WHERE f.status = 'active'
    """).fetchall()

    if not rows:
        print("No active facts to embed.")
        return 0

    existing = {r[0] for r in conn.execute("SELECT fact_id FROM vec_facts").fetchall()}

    to_embed = []
    for r in rows:
        if r[0] not in existing:
            to_embed.append(r)
        elif r[4] and r[4] > last_run:
            conn.execute("DELETE FROM vec_facts WHERE fact_id = ?", (r[0],))
            to_embed.append(r)

    if not to_embed:
        print(f"All {len(rows)} facts already embedded and current.")
        return 0

    new_count = sum(1 for r in to_embed if r[0] not in existing)
    updated_count = len(to_embed) - new_count
    print(f"Embedding {len(to_embed)} facts ({new_count} new, {updated_count} updated, of {len(rows)} total)...")

    texts = [f"{r[1]} — {r[2]}: {r[3]}" for r in to_embed]
    embeddings = model.encode(texts, show_progress_bar=False)

    for row, emb in zip(to_embed, embeddings):
        conn.execute(
            "INSERT INTO vec_facts(fact_id, embedding) VALUES (?, ?)",
            (row[0], serialize(emb.tolist()))
        )
    conn.commit()
    return len(to_embed)

def main():
    print(f"[{datetime.now().isoformat()}] RAG embed starting...")

    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    setup_vec_tables(conn)

    print("Loading embedding model...")
    model = get_embedding_model()

    m_count = embed_memories(conn, model)
    f_count = embed_facts(conn, model)

    now = datetime.now()
    conn.execute(
        "INSERT OR REPLACE INTO rag_meta(key, value) VALUES ('last_run', ?)",
        (now.isoformat(),)
    )
    conn.execute(
        "INSERT OR REPLACE INTO rag_meta(key, value) VALUES ('last_embed_run', ?)",
        (str(int(now.timestamp())),)
    )
    conn.commit()
    conn.close()

    total = m_count + f_count
    print(f"Done. {m_count} memories + {f_count} facts embedded ({total} new vectors).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
