# Agent Memory Loop

How Clarence interacts with memory during a session.

---

## Session Lifecycle

```
Session Start
    │
    ├─ 1. Load static context (SOUL.md, USER.md, AGENTS.md, TOOLS.md)
    │      These are workspace files auto-loaded into every session.
    │
    ├─ 2. Load today's daily note (memory/YYYY-MM-DD.md)
    │      Raw timeline of recent activity.
    │
    ├─ 3. Load MEMORY.md index (curated long-term memory)
    │      Pointers to named memory files in the memory system.
    │
    ├─ 4. MCP tool calls (on-demand during session)
    │      - memory_search: find relevant memories by keyword
    │      - entity_get: look up what's known about a person/project/tool
    │      - profile_get: deterministic identity lookups
    │      - work_recent: what was done recently
    │
    └─ Session active...

During Session
    │
    ├─ Agent reads context, answers questions, executes tasks
    │
    ├─ On correction/preference: interaction_log(type="correction", ...)
    │
    ├─ On task completion: work_log(title, type, description)
    │
    └─ On significant decision: memory_write(name, type="project", ...)

Session End
    │
    ├─ session_log(summary, work_done, key_decisions)
    │
    └─ Daily note updated with session events

Nightly (3am cron)
    │
    ├─ conversation-distill.py: JSONL sessions → memories table
    └─ rag-embed.py: memories + facts → vec_memories + vec_facts
```

---

## What Agents Write

Agents are expected to write memory during a session, not just read it. The general rule:

| Trigger | What to write | Where |
|---|---|---|
| James states a durable preference | `memory_write(type="feedback")` | memories table |
| James corrects behavior | `interaction_log(type="correction")` | interactions table |
| Project status changes | `memory_write(type="project")` | memories table |
| Task completed | `work_log(title, type)` | work_items table |
| Session ends | `session_log(summary, ...)` | sessions table |
| New entity discovered | `entity_upsert(name, type, facts)` | entities + facts tables |

---

## Memory Retrieval Patterns

### Pattern 1: Keyword Search (fast, exact)
```
memory_search(query="github private repos", type="feedback")
```
Used for: looking up known rules, known preferences, known project state.

### Pattern 2: Deterministic Lookup (no fuzzy)
```
profile_get(category="agent", key="clarence.name")
```
Used for: identity facts that must be exact — agent name, user timezone, API endpoints.

### Pattern 3: Semantic Search (slower, fuzzy)
Run `rag-query.py` or query vec_memories directly:
```sql
SELECT m.name, m.body, vm.distance
FROM vec_memories vm
JOIN memories m ON m.id = vm.memory_id
WHERE vm.embedding MATCH <query_vector>
  AND m.status = 'active'
  AND k = 5
ORDER BY vm.distance
```
Used for: "what does James think about X?" when you don't know the exact memory name.

### Pattern 4: Entity Graph Traversal
```
entity_get(name="ipad-synthesizer")
→ { entity, facts: [{key: "status", value: "in development"}, ...] }
```
Used for: getting all known facts about a project, person, or tool.

---

## Memory Hygiene Rules

1. **Write immediately.** Don't plan to write later — context windows fill.
2. **Use specific names.** `feedback:no-mock-db-tests` beats `db-testing-preference`.
3. **Corrections invalidate old memories.** When James says "no, that's wrong", call `memory_invalidate` on the old record before writing the correction.
4. **Don't write ephemeral state.** "Currently debugging X" shouldn't be a memory — it'll be stale in an hour.
5. **Distillation handles bulk.** The nightly distillation pipeline picks up anything you missed. Don't batch-write memories at session end — write them when you learn them.
