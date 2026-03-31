# Vector Search Design

How semantic/RAG search works in the Clarence memory system.

---

## Overview

The system uses [sqlite-vec](https://github.com/asg017/sqlite-vec) for vector storage and KNN search, combined with [sentence-transformers](https://www.sbert.net/) for local embedding. Everything lives in the same SQLite file as the rest of the knowledge store.

---

## Embedding Model

**Model:** `BAAI/bge-base-en-v1.5`
**Dimensions:** 768
**Size:** ~110MB
**Inference:** CPU-only, ~150ms per text on i7-7820X

Upgraded from `all-MiniLM-L6-v2` (384d) on 2026-03-30. BGE-base outperforms
MiniLM on diverse, cross-domain retrieval which matters for a knowledge base
spanning UX, FM synthesis, accessibility, philosophy, and project context.
Tradeoffs: larger model, slightly slower inference, 2x storage for vectors.
At the current scale (~3K memories, ~9K facts), these are non-issues.

---

## What Gets Embedded

### Memories
Text representation: `"{name}: {description}\n{body}"`

Example:
```
feedback:no-mocking-db: Integration tests must hit a real database.
We got burned last quarter when mock/prod divergence masked a broken migration.
Don't mock the database in tests — use a real SQLite file or the actual DB.
```

Stored in: `vec_memories(memory_id, embedding FLOAT[768])`

### Facts
Text representation: `"{entity_name} — {key}: {value}"`

Example:
```
ipad-synthesizer — status: in active development as of 2026-03
ipad-synthesizer — tech_stack: Swift, AudioKit, iPad-first UI
```

Stored in: `vec_facts(fact_id, embedding FLOAT[768])`

---

## Vector Tables Schema

sqlite-vec uses virtual tables. Creating `vec_memories` with `vec0` automatically creates several companion shadow tables:

```sql
-- Main virtual table (what you interact with)
CREATE VIRTUAL TABLE vec_memories
USING vec0(
    memory_id INTEGER PRIMARY KEY,
    embedding FLOAT[768]
);

-- Auto-created shadow tables (managed by vec0, don't touch manually):
-- vec_memories_info       — metadata (row count, dims, etc.)
-- vec_memories_chunks     — vector storage chunks
-- vec_memories_rowids     — rowid → chunk mapping
-- vec_memories_vector_chunks00 — raw vector data
```

---

## Embedding Pipeline

Run nightly by cron (`rag-pipeline/embedding_pipeline.py`):

```
1. Load model (sentence-transformers)
2. SELECT id FROM vec_memories → set of already-embedded IDs
3. SELECT * FROM memories WHERE status='active' → all active memories
4. Diff: find memories not yet embedded
5. Build text repr for each new memory
6. model.encode(texts) → numpy array of shape [N, 384]
7. struct.pack("768f", *embedding) → bytes for sqlite-vec
8. INSERT OR REPLACE INTO vec_memories(memory_id, embedding) VALUES (?, ?)
9. Update rag_meta(last_run) timestamp
```

Same process for facts via `vec_facts`.

---

## Query Time (Retrieval)

```python
# Embed the query
q_vec = model.encode(["what does James think about testing?"])[0]
q_bytes = struct.pack("768f", *q_vec.tolist())

# KNN search in sqlite-vec
results = conn.execute("""
    SELECT m.name, m.type, m.body, vm.distance
    FROM vec_memories vm
    JOIN memories m ON m.id = vm.memory_id
    WHERE vm.embedding MATCH ?
      AND m.status = 'active'
      AND k = 5
    ORDER BY vm.distance
""", (q_bytes,)).fetchall()
```

The `MATCH` + `k = N` syntax is sqlite-vec's KNN query interface. Distance is L2 (Euclidean) by default; cosine similarity is available via `vec_distance_cosine()`.

---

## Incremental Updates

The pipeline is incremental:
- **New records:** automatically embedded on next nightly run
- **Updated records:** re-embedded if `updated_at > last_embed_run` (old vector deleted first)
- **Deleted records:** `status='invalid'` vectors are cleaned up at pipeline start via `cleanup_orphans()`

For immediate updates (e.g., after a major distillation run), run:
```bash
python3 rag-pipeline/embedding_pipeline.py
```

---

## Limitations & Known Issues

1. **~~No re-embedding on update.~~** Fixed. The pipeline now tracks `last_embed_run` and re-embeds any memory/fact whose `updated_at` exceeds it.

2. **~~Soft-deleted memories aren't removed from vec tables.~~** Fixed. The pipeline runs `cleanup_orphans()` at startup to purge vectors for invalidated records.

3. **No chunking for long memories.** Long bodies are embedded as one unit. If a memory's body is >512 tokens, the tail gets truncated by the tokenizer. For the current scale of memories (most <500 chars), this is not an issue.

4. **Cold start.** If `BAAI/bge-base-en-v1.5` is not cached locally, the first embedding run will download it (~110MB). Subsequent runs load from cache.

---

## Scaling Considerations

Current scale: ~hundreds to low thousands of memories and facts. sqlite-vec is fast at this scale on CPU-only hardware.

If the knowledge base grows to millions of records:
- Consider switching to `hnswlib` or `faiss` for ANN (approximate nearest neighbor)
- Or migrate to a dedicated vector store (Qdrant, Weaviate)
- The MCP server interface would remain the same; only the backend changes
