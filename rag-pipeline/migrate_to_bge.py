#!/usr/bin/env python3
"""
One-time migration: all-MiniLM-L6-v2 (384 dims) → BAAI/bge-base-en-v1.5 (768 dims).

Steps:
  1. Back up the database
  2. Drop vec_memories and vec_facts virtual tables
  3. Recreate them with FLOAT[768]
  4. Re-embed all active memories and facts
  5. Update rag_meta

Usage:
  # Dry run (shows what would happen, no changes):
  python3 migrate_to_bge.py --dry-run

  # Execute migration:
  python3 migrate_to_bge.py

IMPORTANT: Back up clarence.db before running this.
"""

import sqlite3
import sqlite_vec
import struct
import sys
import os
import shutil
from datetime import datetime

DB_PATH = os.environ.get("CLARENCE_DB", os.path.expanduser("~/.openclaw/workspace/memory/clarence.db"))
MODEL_NAME = "BAAI/bge-base-en-v1.5"
DIMS = 768

def serialize(vector):
    return struct.pack(f"{len(vector)}f", *vector)

def main():
    dry_run = "--dry-run" in sys.argv

    if not os.path.exists(DB_PATH):
        print(f"Database not found at {DB_PATH}")
        return 1

    # Count what we'll re-embed
    conn = sqlite3.connect(DB_PATH)
    mem_count = conn.execute("SELECT COUNT(*) FROM memories WHERE status = 'active'").fetchone()[0]
    fact_count = conn.execute("SELECT COUNT(*) FROM facts WHERE status = 'active'").fetchone()[0]
    conn.close()

    print(f"Migration: all-MiniLM-L6-v2 (384d) → BAAI/bge-base-en-v1.5 (768d)")
    print(f"Database: {DB_PATH}")
    print(f"Records to re-embed: {mem_count} memories, {fact_count} facts")

    if dry_run:
        print("\n[DRY RUN] No changes made.")
        return 0

    # Back up
    backup_path = DB_PATH + f".backup-pre-bge-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    print(f"\nBacking up to {backup_path}...")
    shutil.copy2(DB_PATH, backup_path)

    # Load model
    print("Loading BAAI/bge-base-en-v1.5 (first run will download ~110MB)...")
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)

    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    # Drop old vec tables
    print("Dropping old vec tables (384d)...")
    conn.execute("DROP TABLE IF EXISTS vec_memories")
    conn.execute("DROP TABLE IF EXISTS vec_facts")
    conn.commit()

    # Recreate with 768 dims
    print("Creating new vec tables (768d)...")
    conn.execute("""
        CREATE VIRTUAL TABLE vec_memories
        USING vec0(
            memory_id INTEGER PRIMARY KEY,
            embedding FLOAT[768]
        )
    """)
    conn.execute("""
        CREATE VIRTUAL TABLE vec_facts
        USING vec0(
            fact_id INTEGER PRIMARY KEY,
            embedding FLOAT[768]
        )
    """)
    conn.commit()

    # Re-embed memories
    print(f"Embedding {mem_count} memories...")
    rows = conn.execute("""
        SELECT id, name, description, body
        FROM memories WHERE status = 'active'
    """).fetchall()

    if rows:
        texts = [f"{r[1]}: {r[2] or ''}\n{r[3]}" for r in rows]
        # Batch encode in chunks of 256 to manage memory
        batch_size = 256
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            batch_rows = rows[i:i+batch_size]
            embeddings = model.encode(batch_texts, show_progress_bar=False)
            for row, emb in zip(batch_rows, embeddings):
                conn.execute(
                    "INSERT INTO vec_memories(memory_id, embedding) VALUES (?, ?)",
                    (row[0], serialize(emb.tolist()))
                )
            conn.commit()
            print(f"  Memories: {min(i+batch_size, len(texts))}/{len(texts)}")

    # Re-embed facts
    print(f"Embedding {fact_count} facts...")
    rows = conn.execute("""
        SELECT f.id, e.name, f.key, f.value
        FROM facts f
        JOIN entities e ON f.entity_id = e.id
        WHERE f.status = 'active'
    """).fetchall()

    if rows:
        texts = [f"{r[1]} — {r[2]}: {r[3]}" for r in rows]
        for i in range(0, len(texts), batch_size):
            batch_texts = texts[i:i+batch_size]
            batch_rows = rows[i:i+batch_size]
            embeddings = model.encode(batch_texts, show_progress_bar=False)
            for row, emb in zip(batch_rows, embeddings):
                conn.execute(
                    "INSERT INTO vec_facts(fact_id, embedding) VALUES (?, ?)",
                    (row[0], serialize(emb.tolist()))
                )
            conn.commit()
            print(f"  Facts: {min(i+batch_size, len(texts))}/{len(texts)}")

    # Update rag_meta
    now = datetime.now()
    conn.execute(
        "INSERT OR REPLACE INTO rag_meta(key, value) VALUES ('embedding_model', ?)",
        (MODEL_NAME,)
    )
    conn.execute(
        "INSERT OR REPLACE INTO rag_meta(key, value) VALUES ('embedding_dims', ?)",
        (str(DIMS),)
    )
    conn.execute(
        "INSERT OR REPLACE INTO rag_meta(key, value) VALUES ('last_embed_run', ?)",
        (str(int(now.timestamp())),)
    )
    conn.execute(
        "INSERT OR REPLACE INTO rag_meta(key, value) VALUES ('last_run', ?)",
        (now.isoformat(),)
    )
    conn.execute(
        "INSERT OR REPLACE INTO rag_meta(key, value) VALUES ('migration_bge', ?)",
        (now.isoformat(),)
    )
    conn.commit()
    conn.close()

    print(f"\nDone. {mem_count} memories + {fact_count} facts re-embedded at 768 dims.")
    print(f"Backup at: {backup_path}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
