# Clarence Memory Architecture

This repository documents the structural framework of Clarence's memory system — the data layer, embedding pipeline, MCP server interfaces, and operational scripts that give an AI assistant persistent, searchable memory across sessions.

No personal data is included. This is the plumbing.

---

## What This Is

Clarence is a persistent AI assistant running via [OpenClaw](https://openclaw.ai). Unlike stateless LLM sessions, Clarence maintains memory across conversations using a multi-layer architecture:

```
Raw Conversations (JSONL)
        ↓ conversation-distill.py
Structured Memories (SQLite: memories, entities, facts)
        ↓ rag-embed.py
Vector Embeddings (sqlite-vec: vec_memories, vec_facts)
        ↓ rag-query.py / MCP tools
Semantic Retrieval (agents query relevant context at session start)
```

---

## Memory Layers

### 1. Episodic → Semantic Distillation

Raw session transcripts (OpenClaw JSONL) are processed nightly by `scripts/conversation-distill.py`. The script:
- Extracts user/assistant message pairs
- Sends batches to a local LLM (Gemini Flash or MiniMax via cc-forge)
- The LLM identifies durable knowledge: decisions, corrections, preferences, project updates, personal context
- Writes structured records to the `memories` table

### 2. SQLite Knowledge Store

`database/schema.sql` defines the full schema. Key tables:

| Table | Purpose |
|---|---|
| `memories` | Named, typed, searchable knowledge records |
| `entities` | People, projects, tools, agents, concepts |
| `facts` | Key-value attributes of entities |
| `sessions` | Session summaries and work done |
| `work_items` | Tracked tasks and completions |
| `interactions` | James corrections/confirmations/preferences |
| `profiles` | Deterministic identity facts (agent name, user prefs) |
| `daily_logs` | Per-day summaries |
| `conversation_distills` | Audit trail of distillation runs |
| `vault_notes` | Indexed Obsidian notes metadata |

### 3. Vector Search (RAG)

Active memories and facts are embedded using `sentence-transformers` (`all-MiniLM-L6-v2`, 384 dims) and stored in `sqlite-vec` virtual tables. This enables semantic retrieval — agents can ask "what does James think about X?" and get relevant memories ranked by cosine similarity.

The pipeline:
1. **`rag-pipeline/embedding_pipeline.py`** — embeds new/changed records nightly
2. **`rag-pipeline/retrieval.py`** — query-time semantic search
3. **`rag-pipeline/distillation.py`** — conversation → structured memory (same logic as `scripts/conversation-distill.py`, refactored for clarity)

### 4. MCP Server Interface

Agents access memory through two MCP servers:

- **`memory-mcp/server.py`** — Full CRUD for memories, entities, facts, sessions, work items, profiles
- **`brain-mcp/`** — Higher-level brain tools (if separate server exists)

These run as stdio MCP servers, configured in OpenClaw's agent manifest.

---

## Directory Structure

```
clarence-memory-structure/
├── README.md                    # This file
├── database/
│   └── schema.sql               # Full SQLite schema (empty tables only)
├── rag-pipeline/
│   ├── embedding_pipeline.py    # Chunking + embedding via sentence-transformers
│   ├── retrieval.py             # Semantic query against vec_memories/vec_facts
│   ├── distillation.py          # Conversation → structured memory pipeline
│   └── requirements.txt         # Python deps
├── memory-mcp/
│   ├── server.py                # MCP server: memory/entity/session/work tools
│   └── memory_tools.md          # Tool documentation
├── brain-mcp/
│   ├── server.py                # Brain MCP server (higher-level tools)
│   └── memory_tools.md          # Tool documentation
├── scripts/
│   ├── conversation-distill.py  # Nightly distillation pipeline
│   ├── ingest-anthropic-export.py  # One-time Claude.ai export ingestion
│   └── obsidian-sync.sh         # Vault sync to Google Drive
└── docs/
    ├── memory-architecture.md   # System design deep-dive
    ├── agent-memory-loop.md     # How agents interact with memory per session
    └── vector-search-design.md  # RAG/vector search design
```

---

## Quick Start

```bash
# Install Python deps
pip install -r rag-pipeline/requirements.txt

# Initialize database
sqlite3 your.db < database/schema.sql

# Run the memory MCP server (stdio)
python3 memory-mcp/server.py

# Embed all memories into vector store
python3 rag-pipeline/embedding_pipeline.py

# Semantic search
python3 rag-pipeline/retrieval.py "what does James think about agent UX?"
```

---

## Design Principles

- **No external vector DB** — sqlite-vec keeps everything in one file, zero ops overhead
- **LLM-driven distillation** — not keyword extraction, but semantic understanding of what's worth keeping
- **Soft deletes everywhere** — memories have `status` (active/invalid), facts have `status`, supersession chains preserve history
- **Agent-agnostic** — any agent with MCP access can read/write the same knowledge store
- **Obsidian integration** — vault notes are indexed into `vault_notes`, facts extracted into the entity graph

---

## Related

- [OpenClaw](https://openclaw.ai) — the agent runtime this runs inside
- [sqlite-vec](https://github.com/asg017/sqlite-vec) — vector search extension for SQLite
- [sentence-transformers](https://www.sbert.net/) — local embedding model
