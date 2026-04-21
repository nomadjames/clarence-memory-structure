# Vector Search Design

How semantic search works in the Clarence memory system.

---

## Overview

The system uses [sqlite-vec](https://github.com/asg017/sqlite-vec) for vector storage and KNN search, combined with local embedding models through [sentence-transformers](https://www.sbert.net/). Everything lives in the same SQLite file as the rest of the knowledge store.

This document focuses on the current stable retrieval path. Evaluation lanes may exist beside it, but they are not the main architecture described here.

---

## Primary retrieval model

**Primary model:** `all-MiniLM-L6-v2`

**Primary dimensions:** 384

**Why this doc uses cautious wording:** retrieval experiments continue over time, but the live local code currently points the main search path at a 384-dimensional local index. Public docs should reflect the stable path, not freeze every temporary experiment into architecture.

---

## What gets embedded

### Memories

Text representation: `"{name}: {description}\n{body}"`

Example:

```text
feedback:no-mock-db: Integration tests must hit a real database.
We got burned when a mock masked a broken migration.
Use a real SQLite file or the actual DB path instead of a fake in-memory substitute.
```

Stored in: `vec_memories_384(memory_id, embedding FLOAT[384])`

### Facts

Text representation combines the entity name, fact key, and fact value into one embedding string.

Example:

```text
mobile-instrument-prototype: status: in active development
mobile-instrument-prototype: tech_stack: Swift, AudioKit, sensor-driven controls
```

Stored in: `vec_facts_384(fact_id, embedding FLOAT[384])`

---

## Vector tables schema

sqlite-vec uses virtual tables. A primary 384-dimensional table looks like this:

```sql
CREATE VIRTUAL TABLE vec_memories_384
USING vec0(
    memory_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]
);
```

A matching facts table follows the same pattern:

```sql
CREATE VIRTUAL TABLE vec_facts_384
USING vec0(
    fact_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]
);
```

Companion shadow tables are created automatically by `vec0` and should not be edited manually.

---

## Embedding pipeline

Run by scheduled jobs through `rag-pipeline/embedding_pipeline.py`:

```text
1. Load the embedding model
2. Read the set of already-embedded IDs from sqlite-vec tables
3. Select active memories and facts from SQLite
4. Find new or changed records
5. Build normalized text representations
6. model.encode(texts) -> vectors of shape [N, 384]
7. Pack vectors for sqlite-vec
8. Upsert into vec_memories_384 or vec_facts_384
9. Update retrieval metadata timestamps
```

The same overall logic applies whether the run is processing memories or facts.

---

## Query time retrieval

A semantic query follows the same pattern:

```python
# Embed the query
q_vec = model.encode(["What does James think about testing?"])[0]

# Query sqlite-vec
# The exact SQL wrapper can vary by implementation, but the flow is:
# 1. embed query
# 2. run KNN against vec_memories_384 or vec_facts_384
# 3. join result IDs back to SQLite rows
```

The core idea is stable even if helper functions or wrappers change: query text becomes an embedding, sqlite-vec performs KNN search, and the matching IDs are joined back to full records.

---

## Incremental updates

The pipeline is incremental:

- **New records:** embedded on the next scheduled run
- **Updated records:** re-embedded when the source record changes
- **Invalid records:** removed from active retrieval results

For immediate refreshes after a large ingest or migration:

```bash
python3 rag-pipeline/embedding_pipeline.py
```

---

## Limitations and known edges

1. **No chunking for long records.** Very long bodies may lose detail compared with a chunked retriever.
2. **Cold start cost.** The first retrieval call loads the embedding model into memory.
3. **Experiment drift.** Evaluation lanes can diverge from the main path. Public docs should only describe the stable default unless a comparison is explicitly the point.

---

## Scaling notes

At the current scale, `sqlite-vec` is still the right tool. It keeps the retrieval path local, cheap, and easy to back up.

If the knowledge base grew by orders of magnitude, the retrieval backend could change without changing the MCP-level interface. That is the real architectural boundary that matters.
