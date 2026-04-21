# Memory Architecture

Clarence's memory system is built around a simple rule: keep the durable knowledge path local, inspectable, and easy to back up. The shared SQLite database still lives under `~/.openclaw/workspace/memory/clarence.db` in the current deployment, but that path is legacy storage compatibility, not proof that OpenClaw is the active runtime.

The live runtime is **Hermes**.

---

## The memory stack

```text
                ┌──────────────────────────────┐
                │        Hermes runtime        │
                │  reads context, writes back  │
                └──────────────┬───────────────┘
                               │
                  internal write-capable MCP
                               │
        ┌──────────────────────▼──────────────────────┐
        │            Clarence memory server           │
        │     memories, entities, facts, sessions     │
        │     work_items, profiles, interactions      │
        └──────────────────────┬──────────────────────┘
                               │ sqlite3
        ┌──────────────────────▼──────────────────────┐
        │              clarence.db (SQLite)           │
        │                                              │
        │  memories   entities   facts   profiles      │
        │  sessions   work_items interactions          │
        │  vault_notes daily_logs rag metadata         │
        │  vec_memories_384   vec_facts_384            │
        └──────────────────────┬──────────────────────┘
                               │
                    read-only retrieval surfaces
                               │
        ┌──────────────────────▼──────────────────────┐
        │ bounded lookup clients and public-safe MCP  │
        │ search, semantic retrieval, entity lookup   │
        └─────────────────────────────────────────────┘
```

The important boundary is not the file path. It is the access model:

- Hermes owns durable writes
- bounded external clients read without mutating the store

---

## Data flow

### Path 1: Conversation to memory

1. Session artifacts are recorded by the live system
2. Distillation jobs process unhandled conversation material
3. The distillation step extracts durable items such as preferences, corrections, decisions, and project state
4. Structured records are written to the `memories` table with audit metadata

Some session artifacts still persist under legacy `~/.openclaw/...` paths. That does not change the runtime identity.

### Path 2: Memory to vectors

1. The embedding pipeline reads active memories and facts
2. It builds normalized text representations for each record
3. It embeds them with the current local retrieval model
4. It stores the vectors in `sqlite-vec` tables such as `vec_memories_384` and `vec_facts_384`

Separate evaluation tables may exist for experiments. The stable production shape is still local SQLite plus sqlite-vec.

### Path 3: Query to retrieval

1. A client performs keyword, profile, entity, or semantic lookup
2. For semantic search, the query is embedded with the same primary local model
3. sqlite-vec performs KNN search against the active tables
4. Matching IDs are joined back to SQLite rows
5. The caller receives records, facts, or relationship context

### Path 4: Notes to knowledge graph

1. Vault content is indexed on a schedule
2. Note metadata is written to `vault_notes`
3. Entity and fact extraction can connect note content to the broader graph

---

## Key design decisions

### Why SQLite plus sqlite-vec?

The original design looked at standalone vector stores, including ChromaDB. SQLite plus sqlite-vec won because it keeps the knowledge store in one place:

- one file to back up
- one connection model
- no separate vector database process
- enough performance for the current scale on CPU-only hardware

### Why keep a strict write boundary?

Because memory quality matters more than write convenience.

If every connected client can write freely, the memory system turns into an uncurated log. The live system keeps the boundary explicit:

- retrieval can be broad
- durable writes stay narrow and accountable

### Why use local embedding?

Local embedding keeps retrieval cheap, fast, and inspectable. It also means the retrieval layer does not depend on a paid external vector service just to function.

### Why soft deletes?

A corrected memory is still part of the system's history.

Invalidating stale memory instead of deleting it preserves audit trails, supports supersession chains, and makes reversibility possible when a correction itself was incomplete.

---

## Tables reference

| Table | Type | Purpose |
|---|---|---|
| `memories` | Knowledge | Named records for preferences, feedback, project context, references |
| `entities` | Knowledge | People, projects, tools, agents, concepts |
| `facts` | Knowledge | Key-value attributes of entities |
| `entity_relations` | Knowledge | Typed links between entities |
| `profiles` | Identity | Deterministic identity and project constants |
| `sessions` | Activity | Session summaries, work done, key decisions |
| `work_items` | Activity | Tracked tasks with type, status, and description |
| `interactions` | Activity | Corrections, confirmations, and questions |
| `daily_logs` | Activity | Per-day summaries |
| `vault_notes` | Integration | Indexed note metadata |
| `obsidian_sync` | Integration | Sync state between vault and DB |
| `vec_memories_384` | Vectors | Embeddings for semantic search of memories |
| `vec_facts_384` | Vectors | Embeddings for semantic search of facts |
| `rag_meta` | Ops | Retrieval metadata and timestamps |
| `conversation_distills` | Ops | Distillation audit trail |
| `distill_batch_progress` | Ops | Per-batch progress for resumable distillation |
| `vault_fact_extraction` | Ops | Tracks which notes have been processed into graph data |

---

## Operational notes

- **DB location:** `~/.openclaw/workspace/memory/clarence.db`
- **Runtime identity:** Hermes, not OpenClaw
- **Path warning:** `~/.openclaw/...` is a legacy path namespace that still stores active components
- **Write boundary:** durable writes stay on the Hermes side of the system
- **Public-safe exports:** public docs and external surfaces should avoid exposing private entity names or internal-only wiring
