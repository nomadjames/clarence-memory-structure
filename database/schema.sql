-- Clarence Memory Database Schema
-- SQLite + sqlite-vec
-- Empty tables only — no data
-- Generated from ~/.openclaw/workspace/memory/clarence.db

PRAGMA foreign_keys = ON;

-- ── Core Knowledge Tables ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS entities (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,          -- person | project | tool | agent | concept
    name        TEXT NOT NULL UNIQUE,
    description TEXT,
    created_at  INTEGER DEFAULT (unixepoch()),
    updated_at  INTEGER DEFAULT (unixepoch()),
    obsidian_path TEXT                  -- relative path in ~/vault/ if linked
);

CREATE TABLE IF NOT EXISTS facts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    key         TEXT NOT NULL,
    value       TEXT NOT NULL,
    source      TEXT DEFAULT 'agent',   -- agent | user | obsidian
    confidence  REAL DEFAULT 1.0,
    created_at  INTEGER DEFAULT (unixepoch()),
    updated_at  INTEGER DEFAULT (unixepoch()),
    author_agent TEXT DEFAULT 'clarence',
    status      TEXT NOT NULL DEFAULT 'active',
    supersedes  INTEGER REFERENCES facts(id)
);

CREATE TABLE IF NOT EXISTS memories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    type         TEXT NOT NULL,          -- user | feedback | project | reference
    description  TEXT,
    body         TEXT NOT NULL,
    tags         TEXT,                   -- JSON array of strings
    created_at   INTEGER DEFAULT (unixepoch()),
    updated_at   INTEGER DEFAULT (unixepoch()),
    obsidian_path TEXT,
    status       TEXT NOT NULL DEFAULT 'active',
    supersedes   INTEGER REFERENCES memories(id),
    author_agent TEXT DEFAULT 'clarence',
    confidence   REAL DEFAULT 1.0
);

-- ── Session & Work Tracking ────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS sessions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT UNIQUE,
    started_at   INTEGER,
    ended_at     INTEGER,
    summary      TEXT,
    key_decisions TEXT,                  -- JSON array
    work_done    TEXT,                   -- JSON array
    obsidian_path TEXT
);

CREATE TABLE IF NOT EXISTS work_items (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    type        TEXT NOT NULL,           -- feature | fix | research | design | build | infra
    status      TEXT DEFAULT 'done',     -- todo | in_progress | done | blocked
    description TEXT,
    session_id  TEXT,
    entity_id   INTEGER REFERENCES entities(id),
    created_at  INTEGER DEFAULT (unixepoch()),
    updated_at  INTEGER DEFAULT (unixepoch()),
    obsidian_path TEXT,
    author_agent TEXT DEFAULT 'clarence',
    error_message TEXT,
    attempted_fix TEXT
);

CREATE TABLE IF NOT EXISTS interactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    type        TEXT NOT NULL,           -- correction | confirmation | preference | question
    content     TEXT NOT NULL,
    context     TEXT,
    applied_rule TEXT,
    created_at  INTEGER DEFAULT (unixepoch()),
    author_agent TEXT DEFAULT 'clarence'
);

-- ── Profile / Identity Store ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS profiles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    category    TEXT NOT NULL,   -- agent | user | project | system
    key         TEXT NOT NULL,   -- e.g. 'name', 'role', 'preference'
    value       TEXT NOT NULL,
    notes       TEXT,
    source      TEXT DEFAULT 'user',   -- user | agent | inferred
    created_at  INTEGER DEFAULT (unixepoch()),
    updated_at  INTEGER DEFAULT (unixepoch()),
    UNIQUE(category, key)
);

-- ── Obsidian Vault Integration ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS obsidian_sync (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_path  TEXT NOT NULL UNIQUE,
    table_name  TEXT NOT NULL,
    row_id      INTEGER,
    last_synced INTEGER DEFAULT (unixepoch()),
    direction   TEXT NOT NULL            -- vault_to_db | db_to_vault
);

CREATE TABLE IF NOT EXISTS vault_notes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path   TEXT UNIQUE,
    topic       TEXT,
    project     TEXT,
    date        TEXT,
    status      TEXT,
    tags        TEXT,
    title       TEXT,
    summary     TEXT,
    updated     TEXT,
    indexed_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS vault_fact_extraction (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_note_id   INTEGER NOT NULL,
    extracted_at    INTEGER DEFAULT (unixepoch()),
    entities_created INTEGER DEFAULT 0,
    UNIQUE(vault_note_id)
);

-- ── Daily Logs ─────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS daily_logs (
    date      TEXT PRIMARY KEY,
    summary   TEXT,
    highlights TEXT,
    blockers  TEXT
);

-- ── Distillation Pipeline Tracking ────────────────────────────────────────

CREATE TABLE IF NOT EXISTS conversation_distills (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_file    TEXT NOT NULL,
    file_hash       TEXT NOT NULL,
    distilled_at    INTEGER DEFAULT (unixepoch()),
    entries_created INTEGER DEFAULT 0,
    window_start    TEXT,
    window_end      TEXT
);

CREATE TABLE IF NOT EXISTS distill_batch_progress (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_file    TEXT NOT NULL,
    file_hash       TEXT NOT NULL,
    batch_index     INTEGER NOT NULL,
    total_batches   INTEGER NOT NULL,
    entries_created INTEGER DEFAULT 0,
    processed_at    INTEGER DEFAULT (unixepoch()),
    UNIQUE(session_file, file_hash, batch_index)
);

-- ── RAG Metadata ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS rag_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

-- ── Vector Tables (sqlite-vec extension required) ──────────────────────────
-- These use the vec0 virtual table module from sqlite-vec.
-- Load the extension before creating: conn.enable_load_extension(True); sqlite_vec.load(conn)

CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories
    USING vec0(
        memory_id INTEGER PRIMARY KEY,
        embedding FLOAT[384]
    );

CREATE VIRTUAL TABLE IF NOT EXISTS vec_facts
    USING vec0(
        fact_id INTEGER PRIMARY KEY,
        embedding FLOAT[384]
    );

-- Note: vec0 virtual tables automatically create companion tables:
--   vec_memories_info, vec_memories_chunks, vec_memories_rowids, vec_memories_vector_chunks00
--   vec_facts_info, vec_facts_chunks, vec_facts_rowids, vec_facts_vector_chunks00
-- Do not create these manually — they are managed by the vec0 module.

-- ── Indexes ────────────────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_memories_type        ON memories(type);
CREATE INDEX IF NOT EXISTS idx_memories_status      ON memories(status);
CREATE INDEX IF NOT EXISTS idx_memories_supersedes  ON memories(supersedes);
CREATE INDEX IF NOT EXISTS idx_facts_entity         ON facts(entity_id);
CREATE INDEX IF NOT EXISTS idx_facts_status         ON facts(status);
CREATE INDEX IF NOT EXISTS idx_work_items_status    ON work_items(status);
CREATE INDEX IF NOT EXISTS idx_sessions_started     ON sessions(started_at);
CREATE INDEX IF NOT EXISTS idx_profiles_category    ON profiles(category);
CREATE INDEX IF NOT EXISTS idx_profiles_key         ON profiles(category, key);
