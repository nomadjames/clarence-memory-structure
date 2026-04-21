# Clarence Memory Architecture

This repository documents the structural framework of Clarence's memory system: the data layer, semantic retrieval path, MCP surfaces, and operational scripts that give an AI assistant persistent, searchable memory across sessions.

This is a public-safe reference. No personal data is included. Example names are illustrative and sanitized.

---

## Current deployment note

The live Clarence system runs under **Hermes**.

Some files, scripts, and database paths still live under `~/.openclaw/...` for compatibility. That path namespace is not the active runtime name.

Current deployment also separates two access lanes:

- **Internal writer lane**: full write-capable memory tooling used by Hermes
- **Bounded read-only lane**: search, list, and lookup workflows for inspection and retrieval

Hermes remains the sole memory writer.

---

## What this is

Clarence maintains memory across conversations through a layered pipeline:

```
Session artifacts
        ↓ conversation-distill.py
Structured memory in SQLite
        ↓ embedding pipeline
Vector indexes in sqlite-vec
        ↓ MCP tools and retrieval helpers
Semantic retrieval for future work
```

The public repo focuses on the stable structure. Exact operational counts, private examples, and internal-only wiring are intentionally omitted.

---

## Memory layers

### 1. Episodic to semantic distillation

Session artifacts are processed by `scripts/conversation-distill.py`. The script:
- extracts user and assistant message pairs
- sends batches to a local LLM through an OpenAI-compatible endpoint
- identifies durable knowledge such as decisions, corrections, preferences, project updates, and personal context
- writes structured records to the `memories` table

### 2. SQLite knowledge store

`database/schema.sql` defines the full schema. Key tables:

| Table | Purpose |
|---|---|
| `memories` | Named, typed, searchable knowledge records |
| `entities` | People, projects, tools, agents, concepts |
| `facts` | Key-value attributes of entities, with supersession chains |
| `entity_relations` | Typed relationships between entities |
| `sessions` | Session summaries and work done |
| `work_items` | Tracked tasks and completions |
| `interactions` | Corrections, confirmations, and preferences |
| `profiles` | Deterministic identity facts |
| `obsidian_sync` | Vault-to-DB sync tracking |
| `vault_notes` | Indexed Obsidian note metadata |
| `vault_fact_extraction` | Tracks which notes have had entities extracted |
| `daily_logs` | Per-day summaries |
| `conversation_distills` | Audit trail of distillation runs |
| `distill_batch_progress` | Batch-level progress for incremental distillation |
| `rag_meta` | Metadata for retrieval and embedding pipelines |

### 3. Vector search

The live deployment uses `sqlite-vec` for local semantic retrieval. The current primary retrieval path uses a local 384-dimensional embedding index. Separate evaluation lanes may exist, but this repo focuses on the stable architecture rather than every experiment.

The pipeline:
1. **`rag-pipeline/embedding_pipeline.py`** embeds new or changed records
2. **`rag-pipeline/retrieval.py`** handles query-time semantic search
3. **`rag-pipeline/distillation.py`** contains the structured conversation-to-memory logic

### 4. MCP surfaces

Memory access is exposed through MCP in two practical modes:

- **Internal memory server**: full CRUD for memories, entities, facts, sessions, work items, and profiles
- **Bounded read-only connectors**: safe lookup tools for search, semantic retrieval, entity inspection, profile lookup, and recent work

Higher-level wrappers may sit above these primitives, but the write boundary remains explicit.

---

## Directory structure

```
clarence-memory-structure/
├── README.md                    # This file
├── database/
│   └── schema.sql               # Full SQLite schema, empty tables only
├── rag-pipeline/
│   ├── embedding_pipeline.py    # Chunking and embedding
│   ├── retrieval.py             # Semantic query against sqlite-vec tables
│   ├── distillation.py          # Conversation to structured memory pipeline
│   └── requirements.txt         # Python dependencies
├── memory-mcp/
│   ├── server.py                # MCP server for memory, entity, session, and work tools
│   └── memory_tools.md          # Tool documentation
├── brain-mcp/
│   ├── server.py                # Optional higher-level wrapper surface
│   └── memory_tools.md          # Tool documentation
├── scripts/
│   ├── conversation-distill.py  # Distillation pipeline
│   ├── ingest-anthropic-export.py  # One-time export ingestion
│   └── obsidian-sync.sh         # Vault sync helper
└── docs/
    ├── memory-architecture.md   # System design deep dive
    ├── agent-memory-loop.md     # How read and write lanes interact with memory
    └── vector-search-design.md  # Retrieval and vector design
```

---

## Quick start

```bash
# Install Python deps
pip install -r rag-pipeline/requirements.txt

# Initialize database
sqlite3 your.db < database/schema.sql

# Run the internal memory MCP server
python3 memory-mcp/server.py

# Build embeddings
python3 rag-pipeline/embedding_pipeline.py

# Semantic search
python3 rag-pipeline/retrieval.py "project constraints and writing preferences"
```

---

## Design principles

- **No external vector database**: `sqlite-vec` keeps retrieval in the same SQLite file as the rest of the knowledge store
- **Explicit write boundary**: not every connected client writes memory, Hermes owns durable writes in the live deployment
- **Soft deletes everywhere**: supersession chains preserve history instead of erasing it
- **Local-first retrieval**: retrieval stays fast and cheap on CPU-only hardware
- **Obsidian integration**: vault notes can be indexed and connected to the entity graph
- **Public-safe exports**: examples stay sanitized and public docs avoid exposing private entity names or internal-only wiring

---

## Status note

This repository intentionally does not pin operational counts in the README. Counts drift quickly. If you need current scale, inspect the live system rather than treating a public snapshot as operational truth.

---

## Related

- Hermes, the active runtime for Clarence
- [sqlite-vec](https://github.com/asg017/sqlite-vec), vector search for SQLite
- [sentence-transformers](https://www.sbert.net/), local embedding tooling
