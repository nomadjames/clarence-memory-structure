#!/usr/bin/env python3
"""
RAG query helper for Clarence knowledge DB.
Usage: python3 rag-query.py "what does James think about AI agent UX?"
Returns top-k semantically similar memories and facts.
"""

import sqlite3
import sqlite_vec
import struct
import sys
import os
import json

DB_PATH = os.environ.get("CLARENCE_DB", "./clarence.db")
MODEL_NAME = "all-MiniLM-L6-v2"
TOP_K = 5

def serialize(vector):
    return struct.pack(f"{len(vector)}f", *vector)

def query(question, top_k=TOP_K):
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(MODEL_NAME)
    q_vec = model.encode([question])[0]
    q_bytes = serialize(q_vec.tolist())

    conn = sqlite3.connect(DB_PATH)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    # Search memories
    memory_results = conn.execute("""
        SELECT m.name, m.type, m.description, m.body,
               vm.distance
        FROM vec_memories vm
        JOIN memories m ON m.id = vm.memory_id
        WHERE vm.embedding MATCH ?
          AND m.status = 'active'
          AND k = ?
        ORDER BY vm.distance
    """, (q_bytes, top_k)).fetchall()

    # Search facts
    fact_results = conn.execute("""
        SELECT e.name, f.key, f.value, vf.distance
        FROM vec_facts vf
        JOIN facts f ON f.id = vf.fact_id
        JOIN entities e ON f.entity_id = e.id
        WHERE vf.embedding MATCH ?
          AND f.status = 'active'
          AND k = ?
        ORDER BY vf.distance
    """, (q_bytes, top_k)).fetchall()

    conn.close()
    return memory_results, fact_results

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 rag-query.py \"your question here\"")
        sys.exit(1)

    question = " ".join(sys.argv[1:])
    print(f"\nQuery: {question}\n{'='*60}")

    memories, facts = query(question)

    if memories:
        print(f"\nTop memories (by semantic similarity):")
        for i, (name, mtype, desc, body, dist) in enumerate(memories, 1):
            print(f"\n  [{i}] {name} ({mtype}) — dist: {dist:.4f}")
            print(f"      {desc or ''}")
            preview = body[:200].replace('\n', ' ')
            print(f"      {preview}...")

    if facts:
        print(f"\nTop facts (by semantic similarity):")
        for i, (entity, key, value, dist) in enumerate(facts, 1):
            print(f"\n  [{i}] {entity} / {key} — dist: {dist:.4f}")
            preview = value[:200].replace('\n', ' ')
            print(f"      {preview}")

    if not memories and not facts:
        print("No results. Run rag-embed.py first to build the index.")

if __name__ == "__main__":
    main()
