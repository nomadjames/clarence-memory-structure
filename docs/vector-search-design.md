# Vector Search Design

How semantic/RAG search works in the Clarence memory system.

---

## Overview

The system uses [sqlite-vec](https://github.com/asg017/sqlite-vec) for vector storage and KNN search, combined with [sentence-transformers](https://www.sbert.net/) for local embedding. Everything lives in the same SQLite file as the rest of the knowledge store.

---

## Embedding Model

**Model:** `all-MiniLM-L6-v2`
**Dimensions:** 384
**Size:** ~22MB
**Inference:** CPU-only, ~50-100ms per text on i7-7820X

This model is a good tradeoff for this use case:
- Small enough to load quickly and run without GPU
- 384 dims keeps the vec tables small
- Semantic quality is sufficient for personal knowledge retrieval
- Available via `sentence-transformers` pip package

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

Stored in: `vec_memories(memory_id, embedding FLOAT[384])`

### Facts
Text representation: `"{entity_name} — {key}: {value}"`

Example:
```
ipad-synthesizer — status: in active development as of 2026-03
ipad-synthesizer — tech_stack: Swift, AudioKit, iPad-first UI
```

Stored in: `vec_facts(fact_id, embedding FLOAT[384])`

---

## Vector Tables Schema

sqlite-vec uses virtual tables. Creating `vec_memories` with `vec0` automatically creates several companion shadow tables:

```sql
-- Main virtual table (what you interact with)
CREATE VIRTUAL TABLE vec_memories
USING vec0(
    memory_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]
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
7. struct.pack("384f", *embedding) → bytes for sqlite-vec
8. INSERT OR REPLACE INTO vec_memories(memory_id, embedding) VALUES (?, ?)
9. Update rag_meta(last_run) timestamp
```

Same process for facts via `vec_facts`.

---

## Query Time (Retrieval)

```python
# Embed the query
q_vec = model.encode(["what does James think about testing?"])[0]
q_bytes = struct.pack("384f", *q_vec.tolist())

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

The pipeline is incremental — it only embeds new/changed records:
- Deleted memories: `status='invalid'` records are excluded from queries but their embeddings remain in vec tables (orphaned, harmless)
- Updated memories: the pipeline does **not** re-embed updated memories unless explicitly triggered. If a memory's body changes significantly, manually delete its vec_memories row to force re-embedding on next run.
- New memories: automatically picked up on next nightly run

For immediate updates (e.g., after a major distillation run), run:
```bash
python3 rag-pipeline/embedding_pipeline.py
```

---

## Limitations & Known Issues

1. **No re-embedding on update.** If a memory's body changes, the old embedding persists until manually cleared. The semantic search may return stale results for recently-updated memories.

2. **Soft-deleted memories aren't removed from vec tables.** Querying with `m.status = 'active'` handles this at query time, but the vec table grows over time. Periodic cleanup: `DELETE FROM vec_memories WHERE memory_id NOT IN (SELECT id FROM memories WHERE status='active')`.

3. **No chunking for long memories.** Long bodies are embedded as one unit. If a memory's body is >512 tokens, the tail gets truncated by the tokenizer. For the current scale of memories (most <500 chars), this is not an issue.

4. **Cold start.** If `all-MiniLM-L6-v2` is not cached locally, the first embedding run will download it (~22MB). Subsequent runs load from cache.

---

## Scaling Considerations

Current scale: ~hundreds to low thousands of memories and facts. sqlite-vec is fast at this scale on CPU-only hardware.

If the knowledge base grows to millions of records:
- Consider switching to `hnswlib` or `faiss` for ANN (approximate nearest neighbor)
- Or migrate to a dedicated vector store (Qdrant, Weaviate)
- The MCP server interface would remain the same; only the backend changes
