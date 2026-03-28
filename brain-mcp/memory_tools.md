# Brain MCP Tools

The brain MCP server provides higher-level aggregation tools — bundled context for session startup, daily summaries, and cross-table queries. It complements the memory MCP server (which handles raw CRUD).

---

## Tool Reference

### `brain_context_bundle`
Returns a structured bundle of recent context suitable for injecting into an agent's session startup prompt.

**Parameters:**
- `hours_back` (optional) — how far back to look, default 48

**Returns:**
```json
{
  "recent_work": [...],
  "recent_sessions": [...],
  "project_memories": [...],
  "recent_interactions": [...]
}
```

**Use at session start** to avoid having agents re-read multiple tables manually.

---

### `brain_daily_summary`
Get the daily log entry for a specific date.

**Parameters:**
- `date` (optional) — `YYYY-MM-DD`, defaults to today

**Returns:** `{date, summary, highlights, blockers}` from the `daily_logs` table.

---

## Architecture Notes

The brain layer sits above the memory layer:

```
Agent
  ↓ MCP calls
brain-mcp/server.py       ← higher-level, aggregated reads
memory-mcp/server.py      ← full CRUD: memories, entities, facts, sessions
  ↓ SQLite
clarence.db
```

In practice, the memory MCP server handles most operations. The brain server is useful when agents need a "what happened recently" summary without issuing 4 separate tool calls.

For the full tool set (memory_search, entity_upsert, work_log, etc.), see `memory-mcp/memory_tools.md`.
