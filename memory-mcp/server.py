#!/usr/bin/env python3
"""
Clarence Memory MCP Server
Gives all agents read/write access to the shared SQLite knowledge database.
"""
import json
import sqlite3
import sys
import os
from datetime import datetime

import struct

DB_PATH = os.path.expanduser("~/.openclaw/workspace/memory/clarence.db")
MODEL_NAME = "BAAI/bge-base-en-v1.5"

# Lazy-loaded at first semantic search call
_embedding_model = None

def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        from sentence_transformers import SentenceTransformer
        _embedding_model = SentenceTransformer(MODEL_NAME)
    return _embedding_model

def _serialize(vector):
    return struct.pack(f"{len(vector)}f", *vector)

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def get_vec_conn():
    """Get a connection with sqlite-vec loaded for vector queries."""
    import sqlite_vec
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

# ── MCP Protocol ────────────────────────────────────────────────────────────

def send(obj):
    print(json.dumps(obj), flush=True)

def respond(id, result):
    send({"jsonrpc": "2.0", "id": id, "result": result})

def error(id, code, message):
    send({"jsonrpc": "2.0", "id": id, "error": {"code": code, "message": message}})

# ── Tool Implementations ─────────────────────────────────────────────────────

def memory_search(query: str, type: str = None, limit: int = 20):
    """Full-text search across memories."""
    conn = get_conn()
    q = f"%{query}%"
    if type:
        rows = conn.execute(
            "SELECT * FROM memories WHERE type=? AND (name LIKE ? OR description LIKE ? OR body LIKE ?) ORDER BY updated_at DESC LIMIT ?",
            (type, q, q, q, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM memories WHERE name LIKE ? OR description LIKE ? OR body LIKE ? ORDER BY updated_at DESC LIMIT ?",
            (q, q, q, limit)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def memory_write(name: str, type: str, description: str, body: str, tags: list = None):
    """Write a new memory record."""
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO memories (name, type, description, body, tags) VALUES (?,?,?,?,?)",
            (name, type, description, body, json.dumps(tags or []))
        )
        conn.commit()
        result = {"status": "created", "name": name}
    except sqlite3.IntegrityError:
        # Update if exists
        conn.execute(
            "UPDATE memories SET type=?, description=?, body=?, tags=?, updated_at=unixepoch() WHERE name=?",
            (type, description, body, json.dumps(tags or []), name)
        )
        conn.commit()
        result = {"status": "updated", "name": name}
    conn.close()
    return result

def memory_update(name: str, body: str = None, description: str = None):
    """Partially update an existing memory."""
    conn = get_conn()
    updates, params = [], []
    if body is not None:
        updates.append("body=?"); params.append(body)
    if description is not None:
        updates.append("description=?"); params.append(description)
    updates.append("updated_at=unixepoch()")
    params.append(name)
    conn.execute(f"UPDATE memories SET {', '.join(updates)} WHERE name=?", params)
    conn.commit()
    conn.close()
    return {"status": "updated", "name": name}

def memory_list(type: str = None):
    """List all memories, optionally filtered by type."""
    conn = get_conn()
    if type:
        rows = conn.execute(
            "SELECT name, type, description, updated_at FROM memories WHERE type=? ORDER BY type, name",
            (type,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT name, type, description, updated_at FROM memories ORDER BY type, name"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def session_log(summary: str, work_done: list = None, key_decisions: list = None, session_id: str = None):
    """Log a session summary."""
    conn = get_conn()
    sid = session_id or f"session_{int(datetime.now().timestamp())}"
    conn.execute(
        "INSERT OR REPLACE INTO sessions (session_id, started_at, ended_at, summary, key_decisions, work_done) VALUES (?,?,?,?,?,?)",
        (sid, int(datetime.now().timestamp()), int(datetime.now().timestamp()),
         summary, json.dumps(key_decisions or []), json.dumps(work_done or []))
    )
    conn.commit()
    conn.close()
    return {"status": "logged", "session_id": sid}

def work_log(title: str, type: str, description: str = None, status: str = "done", entity_name: str = None):
    """Log a work item."""
    conn = get_conn()
    entity_id = None
    if entity_name:
        row = conn.execute("SELECT id FROM entities WHERE name=?", (entity_name,)).fetchone()
        if row:
            entity_id = row["id"]
    conn.execute(
        "INSERT INTO work_items (title, type, description, status, entity_id) VALUES (?,?,?,?,?)",
        (title, type, description, status, entity_id)
    )
    conn.commit()
    conn.close()
    return {"status": "logged", "title": title}

def entity_upsert(name: str, type: str, description: str = None, facts: dict = None, obsidian_path: str = None):
    """Create or update an entity and optionally set facts."""
    conn = get_conn()
    row = conn.execute("SELECT id FROM entities WHERE name=?", (name,)).fetchone()
    if row:
        entity_id = row["id"]
        conn.execute(
            "UPDATE entities SET type=?, description=?, obsidian_path=?, updated_at=unixepoch() WHERE id=?",
            (type, description, obsidian_path, entity_id)
        )
    else:
        cur = conn.execute(
            "INSERT INTO entities (name, type, description, obsidian_path) VALUES (?,?,?,?)",
            (name, type, description, obsidian_path)
        )
        entity_id = cur.lastrowid

    if facts:
        for key, value in facts.items():
            existing = conn.execute(
                "SELECT id FROM facts WHERE entity_id=? AND key=?", (entity_id, key)
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE facts SET value=?, updated_at=unixepoch() WHERE id=?",
                    (str(value), existing["id"])
                )
            else:
                conn.execute(
                    "INSERT INTO facts (entity_id, key, value) VALUES (?,?,?)",
                    (entity_id, key, str(value))
                )
    conn.commit()
    conn.close()
    return {"status": "upserted", "entity_id": entity_id, "name": name}

def entity_get(name: str):
    """Get an entity and all its facts."""
    conn = get_conn()
    entity = conn.execute("SELECT * FROM entities WHERE name=?", (name,)).fetchone()
    if not entity:
        return {"error": f"Entity '{name}' not found"}
    facts = conn.execute(
        "SELECT key, value, source, confidence FROM facts WHERE entity_id=?",
        (entity["id"],)
    ).fetchall()
    conn.close()
    return {**dict(entity), "facts": [dict(f) for f in facts]}

def interaction_log(type: str, content: str, context: str = None, applied_rule: str = None):
    """Log a James interaction (correction, confirmation, preference)."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO interactions (type, content, context, applied_rule) VALUES (?,?,?,?)",
        (type, content, context, applied_rule)
    )
    conn.commit()
    conn.close()
    return {"status": "logged"}

def work_recent(limit: int = 20):
    """Get recently logged work items."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT title, type, status, description, created_at FROM work_items ORDER BY created_at DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def profile_get(category: str, key: str = None):
    """Deterministic lookup for agent names, user prefs, project constants. No fuzzy search."""
    conn = get_conn()
    if key:
        row = conn.execute(
            "SELECT category, key, value, notes FROM profiles WHERE category=? AND key=?",
            (category, key)
        ).fetchone()
        conn.close()
        return dict(row) if row else {"error": f"No profile entry for {category}/{key}"}
    else:
        rows = conn.execute(
            "SELECT category, key, value, notes FROM profiles WHERE category=? ORDER BY key",
            (category,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

def profile_set(category: str, key: str, value: str, notes: str = None, source: str = "agent"):
    """Set a profile entry. Creates or updates — never deletes."""
    conn = get_conn()
    conn.execute(
        "INSERT INTO profiles (category, key, value, notes, source, updated_at) VALUES (?,?,?,?,?,unixepoch()) "
        "ON CONFLICT(category, key) DO UPDATE SET value=excluded.value, notes=COALESCE(excluded.notes, notes), "
        "source=excluded.source, updated_at=unixepoch()",
        (category, key, value, notes, source)
    )
    conn.commit()
    conn.close()
    return {"status": "set", "category": category, "key": key, "value": value}

def memory_invalidate(name: str, reason: str = None, author_agent: str = "clarence"):
    """Mark a memory as invalid (soft delete). Creates a superseding record if reason given."""
    conn = get_conn()
    row = conn.execute("SELECT id FROM memories WHERE name=?", (name,)).fetchone()
    if not row:
        conn.close()
        return {"error": f"Memory '{name}' not found"}
    conn.execute(
        "UPDATE memories SET status='invalid', updated_at=unixepoch() WHERE name=?", (name,)
    )
    conn.commit()
    conn.close()
    return {"status": "invalidated", "name": name, "reason": reason}

def memory_semantic_search(query: str, top_k: int = 5):
    """Semantic search across memories and facts using vector similarity."""
    model = _get_embedding_model()
    q_vec = model.encode([query])[0]
    q_bytes = _serialize(q_vec.tolist())

    conn = get_vec_conn()

    memory_results = conn.execute("""
        SELECT m.name, m.type, m.description, m.body, vm.distance
        FROM vec_memories vm
        JOIN memories m ON m.id = vm.memory_id
        WHERE vm.embedding MATCH ?
          AND m.status = 'active'
          AND k = ?
        ORDER BY vm.distance
    """, (q_bytes, top_k)).fetchall()

    fact_results = conn.execute("""
        SELECT e.name AS entity, f.key, f.value, vf.distance
        FROM vec_facts vf
        JOIN facts f ON f.id = vf.fact_id
        JOIN entities e ON f.entity_id = e.id
        WHERE vf.embedding MATCH ?
          AND f.status = 'active'
          AND k = ?
        ORDER BY vf.distance
    """, (q_bytes, top_k)).fetchall()

    conn.close()

    results = []
    for r in memory_results:
        results.append({
            "type": "memory", "name": r["name"], "memory_type": r["type"],
            "description": r["description"], "body": r["body"][:500],
            "distance": r["distance"]
        })
    for r in fact_results:
        results.append({
            "type": "fact", "entity": r["entity"], "key": r["key"],
            "value": r["value"][:500], "distance": r["distance"]
        })
    results.sort(key=lambda x: x["distance"])
    return results[:top_k * 2]

# ── Tool Registry ─────────────────────────────────────────────────────────────

TOOLS = {
    "memory_search": {
        "description": "Search the Clarence knowledge database for memories by keyword. Optionally filter by type (user|feedback|project|reference).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search term"},
                "type": {"type": "string", "description": "Optional: user | feedback | project | reference"},
                "limit": {"type": "integer", "description": "Max results (default 20)"}
            },
            "required": ["query"]
        }
    },
    "memory_write": {
        "description": "Write a new memory record to the knowledge database (or update if name already exists).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string", "description": "user | feedback | project | reference"},
                "description": {"type": "string"},
                "body": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}}
            },
            "required": ["name", "type", "description", "body"]
        }
    },
    "memory_update": {
        "description": "Partially update an existing memory by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "body": {"type": "string"},
                "description": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    "memory_list": {
        "description": "List all memories in the database, optionally filtered by type.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "Optional: user | feedback | project | reference"}
            }
        }
    },
    "session_log": {
        "description": "Log a session summary with work done and key decisions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "summary": {"type": "string"},
                "work_done": {"type": "array", "items": {"type": "string"}},
                "key_decisions": {"type": "array", "items": {"type": "string"}},
                "session_id": {"type": "string"}
            },
            "required": ["summary"]
        }
    },
    "work_log": {
        "description": "Log a completed work item (feature, fix, research, design, build, infra).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "type": {"type": "string", "description": "feature | fix | research | design | build | infra"},
                "description": {"type": "string"},
                "status": {"type": "string", "description": "done | todo | in_progress | blocked"},
                "entity_name": {"type": "string", "description": "Optional: name of related entity"}
            },
            "required": ["title", "type"]
        }
    },
    "entity_upsert": {
        "description": "Create or update an entity (person, project, tool, agent, concept) with optional facts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string", "description": "person | project | tool | agent | concept"},
                "description": {"type": "string"},
                "facts": {"type": "object", "description": "Key-value pairs of facts about this entity"},
                "obsidian_path": {"type": "string", "description": "Relative path in ~/vault/ if linked"}
            },
            "required": ["name", "type"]
        }
    },
    "entity_get": {
        "description": "Get an entity and all its associated facts by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    "interaction_log": {
        "description": "Log a James interaction — correction, confirmation, preference, or question.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "description": "correction | confirmation | preference | question"},
                "content": {"type": "string"},
                "context": {"type": "string"},
                "applied_rule": {"type": "string"}
            },
            "required": ["type", "content"]
        }
    },
    "work_recent": {
        "description": "Get recently logged work items.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max results (default 20)"}
            }
        }
    },
    "profile_get": {
        "description": "Deterministic lookup for agent names, user preferences, and project constants. Use this — not memory_search — for identity facts. Pass category only to list all keys in that category.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "agent | user | project | system"},
                "key": {"type": "string", "description": "Optional: specific key (e.g. 'clarence.name'). Omit to list all in category."}
            },
            "required": ["category"]
        }
    },
    "profile_set": {
        "description": "Set a profile entry (agent name, user preference, project constant). Creates or updates — never deletes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "category": {"type": "string", "description": "agent | user | project | system"},
                "key": {"type": "string"},
                "value": {"type": "string"},
                "notes": {"type": "string"},
                "source": {"type": "string", "description": "user | agent | inferred (default: agent)"}
            },
            "required": ["category", "key", "value"]
        }
    },
    "memory_invalidate": {
        "description": "Soft-delete a memory by marking it invalid. Never hard-deletes — preserves audit trail.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "reason": {"type": "string"},
                "author_agent": {"type": "string"}
            },
            "required": ["name"]
        }
    },
    "memory_semantic_search": {
        "description": "Semantic search across memories and facts using vector similarity. Use this when you don't know exact keywords but know what concept you're looking for.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural language query"},
                "top_k": {"type": "integer", "description": "Number of results (default 5)"}
            },
            "required": ["query"]
        }
    }
}

DISPATCH = {
    "memory_search": lambda a: memory_search(**a),
    "memory_write": lambda a: memory_write(**a),
    "memory_update": lambda a: memory_update(**a),
    "memory_list": lambda a: memory_list(**a),
    "session_log": lambda a: session_log(**a),
    "work_log": lambda a: work_log(**a),
    "entity_upsert": lambda a: entity_upsert(**a),
    "entity_get": lambda a: entity_get(**a),
    "interaction_log": lambda a: interaction_log(**a),
    "work_recent": lambda a: work_recent(**a),
    "profile_get": lambda a: profile_get(**a),
    "profile_set": lambda a: profile_set(**a),
    "memory_invalidate": lambda a: memory_invalidate(**a),
    "memory_semantic_search": lambda a: memory_semantic_search(**a),
}

# ── Main Loop ─────────────────────────────────────────────────────────────────

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = msg.get("method", "")
        id = msg.get("id")

        if method == "initialize":
            respond(id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "clarence-memory", "version": "1.1.0"}
            })

        elif method == "tools/list":
            respond(id, {
                "tools": [
                    {"name": k, "description": v["description"], "inputSchema": v["inputSchema"]}
                    for k, v in TOOLS.items()
                ]
            })

        elif method == "tools/call":
            name = msg.get("params", {}).get("name")
            args = msg.get("params", {}).get("arguments", {})
            if name in DISPATCH:
                try:
                    result = DISPATCH[name](args)
                    respond(id, {
                        "content": [{"type": "text", "text": json.dumps(result, indent=2)}]
                    })
                except Exception as e:
                    error(id, -32000, str(e))
            else:
                error(id, -32601, f"Unknown tool: {name}")

        elif method == "notifications/initialized":
            pass  # no response needed

        elif id is not None:
            error(id, -32601, f"Method not found: {method}")

if __name__ == "__main__":
    main()
