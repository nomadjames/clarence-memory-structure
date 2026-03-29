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
MODEL_NAME = "all-MiniLM-L6-v2"
DIMS = 384

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
            embedding FLOAT[384]
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS vec_facts
        USING vec0(
            fact_id INTEGER PRIMARY KEY,
            embedding FLOAT[384]
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rag_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()

def embed_memories(conn, model):
    rows = conn.execute("""
        SELECT id, name, description, body
        FROM memories
        WHERE status = 'active'
    """).fetchall()

    if not rows:
        print("No active memories to embed.")
        return 0

    # Get already-embedded IDs
    existing = {r[0] for r in conn.execute("SELECT memory_id FROM vec_memories").fetchall()}
    new_rows = [r for r in rows if r[0] not in existing]

    if not new_rows:
        print(f"All {len(rows)} memories already embedded.")
        return 0

    print(f"Embedding {len(new_rows)} new memories (of {len(rows)} total)...")

    texts = [f"{r[1]}: {r[2] or ''}\n{r[3]}" for r in new_rows]
    embeddings = model.encode(texts, show_progress_bar=False)

    for row, emb in zip(new_rows, embeddings):
        conn.execute(
            "INSERT OR REPLACE INTO vec_memories(memory_id, embedding) VALUES (?, ?)",
            (row[0], serialize(emb.tolist()))
        )
    conn.commit()
    return len(new_rows)

def embed_facts(conn, model):
    rows = conn.execute("""
        SELECT f.id, e.name, f.key, f.value
        FROM facts f
        JOIN entities e ON f.entity_id = e.id
        WHERE f.status = 'active'
    """).fetchall()

    if not rows:
        print("No active facts to embed.")
        return 0

    existing = {r[0] for r in conn.execute("SELECT fact_id FROM vec_facts").fetchall()}
    new_rows = [r for r in rows if r[0] not in existing]

    if not new_rows:
        print(f"All {len(rows)} facts already embedded.")
        return 0

    print(f"Embedding {len(new_rows)} new facts (of {len(rows)} total)...")

    texts = [f"{r[1]} — {r[2]}: {r[3]}" for r in new_rows]
    embeddings = model.encode(texts, show_progress_bar=False)

    for row, emb in zip(new_rows, embeddings):
        conn.execute(
            "INSERT OR REPLACE INTO vec_facts(fact_id, embedding) VALUES (?, ?)",
            (row[0], serialize(emb.tolist()))
        )
    conn.commit()
    return len(new_rows)

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

    conn.execute(
        "INSERT OR REPLACE INTO rag_meta(key, value) VALUES ('last_run', ?)",
        (datetime.now().isoformat(),)
    )
    conn.commit()
    conn.close()

    total = m_count + f_count
    print(f"Done. {m_count} memories + {f_count} facts embedded ({total} new vectors).")
    return 0

if __name__ == "__main__":
    sys.exit(main())
