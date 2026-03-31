# Memory Architecture

Clarence's memory system is designed around a single principle: **everything in one place, zero infrastructure overhead**. One SQLite file. No Redis, no Postgres, no external vector database. The file lives at `~/.openclaw/workspace/memory/clarence.db` and is backed up to Google Drive via rclone.

---

## The Memory Stack

```
┌─────────────────────────────────────────────────────────────┐
│                        Agent (LLM)                          │
│    Session starts → reads context → works → writes back     │
└────────────────────┬───────────────────────────────────────┘
                     │ MCP (stdio)
        ┌────────────▼────────────┐
        │    memory-mcp/server.py │  ← CRUD interface
        │    brain-mcp/server.py  │  ← aggregated reads
        └────────────┬────────────┘
                     │ sqlite3
        ┌────────────▼────────────────────────────────────────┐
        │              clarence.db (SQLite)                   │
        │                                                     │
        │  memories    entities    facts    sessions          │
        │  work_items  profiles    interactions               │
        │  daily_logs  vault_notes                            │
        │                                                     │
        │  vec_memories  vec_facts  (sqlite-vec extension)    │
        └─────────────────────────────────────────────────────┘
                     ↑
        ┌────────────┴────────────┐
        │   Offline Pipelines     │
        │  conversation-distill   │  ← nightly: sessions → memories
        │  rag-embed              │  ← nightly: memories → vectors
        │  vault-indexer          │  ← 30min: vault notes → vault_notes
        │  ingest-anthropic-export│  ← one-time: claude.ai export → entities
        └─────────────────────────┘
```

---

## Data Flow

### Path 1: Conversation → Memory (Nightly)

1. OpenClaw stores every session as a JSONL file in `~/.openclaw/agents/main/sessions/`
2. `scripts/conversation-distill.py` runs nightly via cron at 3am
3. For each unprocessed session file:
   - Extracts user/assistant message pairs (skips tool calls, system messages)
   - Groups pairs into batches of 40
   - Sends each batch to a local LLM via an OpenAI-compatible endpoint
   - LLM returns structured JSON: `[{type, name, description, body, tags}]`
   - Records are written to `memories` table with `author_agent = 'conversation-distill'`
4. Deduplication: exact-match on `name` field; updates body if content changed

### Path 2: Memory → Vector (Nightly)

1. `rag-pipeline/embedding_pipeline.py` runs after distillation
2. Fetches all `active` memories and facts not yet in vec tables
3. Builds text representations:
   - Memories: `"{name}: {description}\n{body}"`
   - Facts: `"{entity_name} — {key}: {value}"`
4. Embeds via `sentence-transformers` (`BAAI/bge-base-en-v1.5`, 768 dims)
5. Stores in `vec_memories` and `vec_facts` (sqlite-vec virtual tables)

### Path 3: Agent Query → Semantic Retrieval (Real-time)

1. At session start, agent may call `memory_search` (keyword) or `rag-query` (semantic)
2. For semantic: query text is embedded using same model
3. sqlite-vec performs KNN search using cosine distance
4. Top-K results joined against `memories`/`facts` tables to get full records
5. Injected into agent context

### Path 4: Vault Notes → Entity Graph (Every 30 min)

1. `scripts/vault-index.sh` runs every 30 min
2. Scans `~/vault/` for Markdown files with YAML frontmatter
3. Extracts `topic`, `project`, `date`, `status`, `tags`, `title`, `summary`
4. Writes to `vault_notes` table
5. `vault-to-facts.py` then extracts entities/facts from note content

---

## Key Design Decisions

### Why SQLite + sqlite-vec instead of a dedicated vector DB?

The original design considered ChromaDB but rejected it:
- ChromaDB requires a separate process and separate data directory
- sqlite-vec embeds vector search directly in the SQLite file
- One backup, one sync, one connection string
- sqlite-vec uses the same KNN algorithm (cosine similarity on FLOAT[384])
- Performance is adequate for tens of thousands of vectors on a CPU-only machine

### Why sentence-transformers instead of an API embedding model?

- Local inference = no latency, no API costs, no rate limits
- `BAAI/bge-base-en-v1.5` is ~110MB, runs in ~150ms on CPU
- 768 dims provides better cross-domain retrieval for diverse knowledge
- An API-based model (e.g., OpenAI ada-002) would be architecturally compatible but unnecessary

### Why LLM distillation instead of keyword extraction?

Raw keyword extraction captures what was said, not what matters. The LLM distillation step:
- Recognizes that "ok fine let's just use Postgres" is a decision worth keeping
- Skips tool output, debugging loops, and generic how-to questions
- Classifies entries by type (decision/correction/preference/project/personal)
- Produces natural-language bodies that embed well

The tradeoff is token cost (mitigated by using smaller models for distillation) and potential for hallucination in the distilled memory (mitigated by low temperature and clear schema).

### Why soft deletes?

Memory correctness matters more than storage efficiency. When James corrects a previous belief, we don't delete the old memory — we mark it `invalid` and create a new one with `supersedes` pointing to the old. This means:
- We can audit what Clarence believed at any point in time
- We can understand when/why beliefs changed
- Accidental invalidations are recoverable

---

## Tables Reference

| Table | Type | Purpose |
|---|---|---|
| `memories` | Knowledge | Named records: user prefs, feedback, project context, references |
| `entities` | Knowledge | Named objects: people, projects, tools, agents, concepts |
| `facts` | Knowledge | Key-value attributes of entities |
| `profiles` | Identity | Deterministic lookups for agent name, user prefs, project constants |
| `sessions` | Activity | Session summaries, work done, key decisions |
| `work_items` | Activity | Tracked tasks with type/status/description |
| `interactions` | Activity | Discrete corrections, confirmations, preferences from James |
| `daily_logs` | Activity | Per-day summary: highlights, blockers |
| `vault_notes` | Integration | Indexed Obsidian note metadata |
| `obsidian_sync` | Integration | Sync state between vault and DB |
| `vec_memories` | Vectors | Embeddings for semantic search of memories |
| `vec_facts` | Vectors | Embeddings for semantic search of facts |
| `rag_meta` | Ops | Pipeline metadata (last_run timestamps) |
| `conversation_distills` | Ops | Audit trail of distillation runs |
| `distill_batch_progress` | Ops | Per-batch progress for large sessions (resumable) |
| `vault_fact_extraction` | Ops | Tracks which vault notes have been extracted |

---

## Operational Notes

- **DB location:** `~/.openclaw/workspace/memory/clarence.db`
- **Backup:** synced to `gdrive:openclaw-workspace` every 2 hours via rclone
- **Distillation cron:** daily at 3am, runs `conversation-distill.py`
- **Embedding cron:** daily at 3:30am, runs `rag-embed.py`
- **Vault index cron:** every 30 min, runs `vault-index.sh`
- **sqlite-vec extension:** loaded at runtime via `sqlite_vec.load(conn)` — must be installed as Python package or .so
