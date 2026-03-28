# Memory MCP Tools

The memory MCP server (`server.py`) exposes the Clarence knowledge database to any connected agent via the Model Context Protocol (stdio transport). All reads and writes go through this interface.

---

## Tool Reference

### `memory_search`
Full-text search across the `memories` table.

**Parameters:**
- `query` (required) — search term (LIKE match against name, description, body)
- `type` (optional) — filter to `user | feedback | project | reference`
- `limit` (optional) — max results, default 20

**Returns:** Array of memory records sorted by `updated_at` desc.

**Use when:** You need to find what Clarence knows about a topic. E.g., "what are James's preferences about code style?"

---

### `memory_write`
Create or update a named memory record.

**Parameters:**
- `name` (required) — unique kebab-case identifier
- `type` (required) — `user | feedback | project | reference`
- `description` (required) — one-line summary used for index display
- `body` (required) — full content
- `tags` (optional) — JSON array of tag strings

**Behavior:** If name exists, updates all fields. If new, inserts.

**Use when:** Distilling a durable insight from conversation that should persist.

---

### `memory_update`
Partial update of an existing memory (body and/or description only).

**Parameters:**
- `name` (required) — must already exist
- `body` (optional) — new body text
- `description` (optional) — new description

**Use when:** Appending to or correcting an existing memory without full rewrite.

---

### `memory_list`
List all memories, optionally filtered by type.

**Parameters:**
- `type` (optional) — `user | feedback | project | reference`

**Returns:** Array of `{name, type, description, updated_at}` — no body content (use `memory_search` to read full bodies).

**Use when:** Building a summary index or checking what's in the DB.

---

### `memory_invalidate`
Soft-delete a memory. Sets `status = 'invalid'`. Never hard-deletes.

**Parameters:**
- `name` (required)
- `reason` (optional) — why it's being invalidated
- `author_agent` (optional) — which agent is invalidating it

**Use when:** A memory is stale, superseded, or was written in error.

---

### `session_log`
Log a session summary to the `sessions` table.

**Parameters:**
- `summary` (required) — narrative description of what happened
- `work_done` (optional) — JSON array of completed items
- `key_decisions` (optional) — JSON array of decisions made
- `session_id` (optional) — if omitted, auto-generates `session_<timestamp>`

---

### `work_log`
Log a completed (or in-progress) work item.

**Parameters:**
- `title` (required)
- `type` (required) — `feature | fix | research | design | build | infra`
- `description` (optional)
- `status` (optional) — `done | todo | in_progress | blocked` (default: done)
- `entity_name` (optional) — link to a related entity by name

---

### `work_recent`
Get recently logged work items.

**Parameters:**
- `limit` (optional) — default 20

**Returns:** Array of `{title, type, status, description, created_at}` sorted newest first.

---

### `entity_upsert`
Create or update an entity (person, project, tool, agent, concept) with optional key-value facts.

**Parameters:**
- `name` (required) — unique identifier
- `type` (required) — `person | project | tool | agent | concept`
- `description` (optional)
- `facts` (optional) — `{key: value}` dict of facts to set
- `obsidian_path` (optional) — relative path in `~/vault/` if linked

---

### `entity_get`
Get an entity and all its associated facts.

**Parameters:**
- `name` (required)

**Returns:** Entity record + `facts` array.

---

### `interaction_log`
Log a discrete James interaction — corrections, confirmations, preferences, or questions.

**Parameters:**
- `type` (required) — `correction | confirmation | preference | question`
- `content` (required) — what was said or observed
- `context` (optional) — surrounding context
- `applied_rule` (optional) — which rule/memory this applies to

**Use when:** James corrects Clarence's behavior. These drive the feedback memory system.

---

### `profile_get`
Deterministic lookup for identity facts — agent names, user preferences, project constants.

**Parameters:**
- `category` (required) — `agent | user | project | system`
- `key` (optional) — specific key. If omitted, returns all entries in category.

**Returns:** Single record or array of `{category, key, value, notes}`.

**Use this instead of `memory_search` for identity facts** — profiles are indexed by exact key, no fuzzy matching.

---

### `profile_set`
Create or update a profile entry.

**Parameters:**
- `category` (required)
- `key` (required)
- `value` (required)
- `notes` (optional)
- `source` (optional) — `user | agent | inferred` (default: agent)

---

## Memory Types

| Type | Purpose | Examples |
|---|---|---|
| `user` | Facts about the user's role, goals, knowledge | James is a UX student; prefers Sonnet for coding |
| `feedback` | How Clarence should behave; corrections | Don't mock DB in tests; stop summarizing after responses |
| `project` | Ongoing work, decisions, status | fortune-telling app: using I Ching hexagrams |
| `reference` | Pointers to external systems/resources | Pipeline bugs tracked in Linear "INGEST" project |

## Soft Delete Pattern

Memories are never hard-deleted. `status` field:
- `active` — normal, visible to search
- `invalid` — marked stale, excluded from search results

The `supersedes` field can point from new memory to the old one, creating an audit chain.
