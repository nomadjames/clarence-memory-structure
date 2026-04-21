# Agent Memory Loop

How Clarence interacts with memory during a session.

This document reflects the current split between a write-capable internal lane and a bounded read-only lane.

---

## Session lifecycle

```
Session start
    │
    ├─ 1. Load static context
    │      SOUL.md, USER.md, AGENTS.md, and other curated files
    │
    ├─ 2. Load recent timeline context
    │      Daily notes, working state, or other lightweight history
    │
    ├─ 3. Use memory tools on demand
    │      - memory_search
    │      - memory_list
    │      - memory_semantic_search
    │      - entity_get
    │      - entity_relations_get
    │      - profile_get
    │      - work_recent
    │
    └─ Session active

During session
    │
    ├─ Read-only clients retrieve context and inspect state
    │
    ├─ Hermes may log durable corrections, work items, sessions,
    │  memory updates, or entity changes when appropriate
    │
    └─ Scheduled pipelines distill and embed new durable knowledge
```

---

## Two operating modes

### 1. Hermes writer lane

Hermes owns the write-capable path in the live deployment.

Typical write-capable operations:
- `memory_write`
- `memory_update`
- `memory_invalidate`
- `session_log`
- `work_log`
- `interaction_log`
- `entity_upsert`
- `entity_relate`
- `profile_set`

Use this lane when durable system state should actually change.

### 2. Bounded read-only lane

Read-only clients inspect the memory system without mutating it.

Typical read-only operations:
- `memory_search`
- `memory_list`
- `memory_semantic_search`
- `entity_get`
- `entity_relations_get`
- `profile_get`
- `work_recent`

Use this lane when the goal is recall, context gathering, or verification.

If a read-only client discovers something that should become durable memory, it should hand that finding back to Hermes rather than writing directly.

---

## Retrieval patterns

### Pattern 1: Keyword search

```text
memory_search(query="github private repos", type="feedback")
```

Use when you need exact known rules, preferences, or project state.

### Pattern 2: Deterministic lookup

```text
profile_get(category="agent", key="clarence.name")
```

Use for identity facts that must be exact, such as names, timezones, or project constants.

### Pattern 3: Semantic search

```text
memory_semantic_search(query="How does the system separate public read access from internal writes?", top_k=5)
```

Use when the concept is known but the exact wording is not.

### Pattern 4: Entity inspection

```text
entity_get(name="mobile-instrument-prototype")
→ { entity, facts: [{key: "status", value: "in development"}, ...] }
```

Use when you need the known facts for a project, tool, person, or concept.

### Pattern 5: Relationship inspection

```text
entity_relations_get(name="mobile-instrument-prototype")
```

Use when the connection between entities matters more than isolated facts.

---

## Write boundary rules

| Trigger | Read-only lane | Hermes writer lane |
|---|---|---|
| Need context for the current task | Search and inspect | Not needed |
| James states a durable preference | Capture finding only | `memory_write(type="feedback")` |
| James corrects behavior | Capture finding only | `interaction_log(type="correction")`, then durable update if needed |
| Project status changes | Capture finding only | `memory_write(type="project")` or `entity_upsert(...)` |
| Task completed | Inspect recent work only | `work_log(title, type)` |
| Session wraps up with durable decisions | Inspect prior context | `session_log(summary, ...)` |

Not every session should write memory. A large share of good memory hygiene is knowing when *not* to write.

---

## Memory hygiene rules

1. **Write only what should stay true.** Ephemeral debugging state is not durable memory.
2. **Prefer exact tools for exact facts.** Use `profile_get` for identity constants, not fuzzy search.
3. **Invalidate stale memory instead of silently overwriting meaning.** Preserve history.
4. **Keep public examples sanitized.** Public documentation should not leak private entity names.
5. **Let scheduled distillation do the bulk work.** Session tools handle important explicit updates, not every transient detail.

---

## Practical summary

The old mental model was "every connected agent writes memory." The live model is stricter:

- many clients can read
- the bounded lane stays read-only
- Hermes owns durable writes

That boundary keeps the memory system useful without turning it into a free-for-all.
