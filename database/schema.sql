CREATE TABLE entities (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            type        TEXT NOT NULL,          -- person | project | tool | agent | concept
            name        TEXT NOT NULL UNIQUE,
            description TEXT,
            created_at  INTEGER DEFAULT (unixepoch()),
            updated_at  INTEGER DEFAULT (unixepoch()),
            obsidian_path TEXT                  -- relative path in ~/vault/ if linked
        );
CREATE TABLE sqlite_sequence(name,seq);
CREATE TABLE facts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_id   INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
            key         TEXT NOT NULL,
            value       TEXT NOT NULL,
            source      TEXT DEFAULT 'agent',   -- agent | user | obsidian
            confidence  REAL DEFAULT 1.0,
            created_at  INTEGER DEFAULT (unixepoch()),
            updated_at  INTEGER DEFAULT (unixepoch())
        , author_agent TEXT DEFAULT 'clarence', status TEXT NOT NULL DEFAULT 'active', supersedes INTEGER REFERENCES facts(id));
CREATE TABLE memories (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL UNIQUE,
            type         TEXT NOT NULL,          -- user | feedback | project | reference
            description  TEXT,
            body         TEXT NOT NULL,
            tags         TEXT,                   -- JSON array of strings
            created_at   INTEGER DEFAULT (unixepoch()),
            updated_at   INTEGER DEFAULT (unixepoch()),
            obsidian_path TEXT
        , status TEXT NOT NULL DEFAULT 'active', supersedes INTEGER REFERENCES memories(id), author_agent TEXT DEFAULT 'clarence', confidence REAL DEFAULT 1.0);
CREATE TABLE sessions (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   TEXT UNIQUE,
            started_at   INTEGER,
            ended_at     INTEGER,
            summary      TEXT,
            key_decisions TEXT,                  -- JSON array
            work_done    TEXT,                   -- JSON array
            obsidian_path TEXT
        );
CREATE TABLE work_items (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            type        TEXT NOT NULL,           -- feature | fix | research | design | build | infra
            status      TEXT DEFAULT 'done',     -- todo | in_progress | done | blocked
            description TEXT,
            session_id  TEXT,
            entity_id   INTEGER REFERENCES entities(id),
            created_at  INTEGER DEFAULT (unixepoch()),
            updated_at  INTEGER DEFAULT (unixepoch()),
            obsidian_path TEXT
        , author_agent TEXT DEFAULT 'clarence', error_message TEXT, attempted_fix TEXT);
CREATE TABLE interactions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            type        TEXT NOT NULL,           -- correction | confirmation | preference | question
            content     TEXT NOT NULL,
            context     TEXT,
            applied_rule TEXT,
            created_at  INTEGER DEFAULT (unixepoch())
        , author_agent TEXT DEFAULT 'clarence');
CREATE TABLE obsidian_sync (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_path  TEXT NOT NULL UNIQUE,
            table_name  TEXT NOT NULL,
            row_id      INTEGER,
            last_synced INTEGER DEFAULT (unixepoch()),
            direction   TEXT NOT NULL            -- vault_to_db | db_to_vault
        );
CREATE INDEX idx_memories_type ON memories(type);
CREATE INDEX idx_facts_entity ON facts(entity_id);
CREATE INDEX idx_work_items_status ON work_items(status);
CREATE INDEX idx_sessions_started ON sessions(started_at);
CREATE TABLE profiles (
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
CREATE INDEX idx_profiles_category ON profiles(category);
CREATE INDEX idx_profiles_key ON profiles(category, key);
CREATE INDEX idx_memories_status ON memories(status);
CREATE INDEX idx_memories_supersedes ON memories(supersedes);
CREATE INDEX idx_facts_status ON facts(status);
CREATE TABLE rag_meta (
            key TEXT PRIMARY KEY,
            value TEXT
        );
CREATE TABLE vault_notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_path TEXT UNIQUE,
    topic TEXT,
    project TEXT,
    date TEXT,
    status TEXT,
    tags TEXT,
    title TEXT,
    summary TEXT,
    updated TEXT,
    indexed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE daily_logs (date TEXT PRIMARY KEY, summary TEXT, highlights TEXT, blockers TEXT);
CREATE TABLE conversation_distills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_file TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            distilled_at INTEGER DEFAULT (unixepoch()),
            entries_created INTEGER DEFAULT 0,
            window_start TEXT,
            window_end TEXT
        );
CREATE TABLE vault_fact_extraction (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vault_note_id INTEGER NOT NULL,
            extracted_at INTEGER DEFAULT (unixepoch()),
            entities_created INTEGER DEFAULT 0,
            UNIQUE(vault_note_id)
        );
CREATE TABLE distill_batch_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_file TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            batch_index INTEGER NOT NULL,
            total_batches INTEGER NOT NULL,
            entries_created INTEGER DEFAULT 0,
            processed_at INTEGER DEFAULT (unixepoch()),
            UNIQUE(session_file, file_hash, batch_index)
        );
CREATE TABLE entity_relations (id INTEGER PRIMARY KEY AUTOINCREMENT, from_entity INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE, relation TEXT NOT NULL, to_entity INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE, context TEXT, created_at INTEGER DEFAULT (unixepoch()), author_agent TEXT DEFAULT 'clarence', status TEXT NOT NULL DEFAULT 'active', UNIQUE(from_entity, relation, to_entity));
CREATE INDEX idx_relations_from ON entity_relations(from_entity);
CREATE INDEX idx_relations_to ON entity_relations(to_entity);
CREATE VIRTUAL TABLE vec_memories
        USING vec0(
            memory_id INTEGER PRIMARY KEY,
            embedding FLOAT[768]
        );
CREATE TABLE IF NOT EXISTS "vec_memories_info" (key text primary key, value any);
CREATE VIRTUAL TABLE vec_facts
        USING vec0(
            fact_id INTEGER PRIMARY KEY,
            embedding FLOAT[768]
        );
CREATE TABLE IF NOT EXISTS "vec_facts_info" (key text primary key, value any);
CREATE VIRTUAL TABLE vec_memories_new
        USING vec0(memory_id INTEGER PRIMARY KEY, embedding FLOAT[384]);
CREATE TABLE IF NOT EXISTS "vec_memories_new_info" (key text primary key, value any);
CREATE TABLE IF NOT EXISTS "vec_memories_new_chunks"(chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,size INTEGER NOT NULL,validity BLOB NOT NULL,rowids BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS "vec_memories_new_rowids"(rowid INTEGER PRIMARY KEY AUTOINCREMENT,id,chunk_id INTEGER,chunk_offset INTEGER);
CREATE TABLE IF NOT EXISTS "vec_memories_new_vector_chunks00"(rowid PRIMARY KEY,vectors BLOB NOT NULL);
CREATE VIRTUAL TABLE vec_memories_384
    USING vec0(memory_id INTEGER PRIMARY KEY, embedding FLOAT[384]);
CREATE TABLE IF NOT EXISTS "vec_memories_384_info" (key text primary key, value any);
CREATE TABLE IF NOT EXISTS "vec_memories_384_chunks"(chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,size INTEGER NOT NULL,validity BLOB NOT NULL,rowids BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS "vec_memories_384_rowids"(rowid INTEGER PRIMARY KEY AUTOINCREMENT,id,chunk_id INTEGER,chunk_offset INTEGER);
CREATE TABLE IF NOT EXISTS "vec_memories_384_vector_chunks00"(rowid PRIMARY KEY,vectors BLOB NOT NULL);
CREATE VIRTUAL TABLE vec_facts_384
    USING vec0(fact_id INTEGER PRIMARY KEY, embedding FLOAT[384]);
CREATE TABLE IF NOT EXISTS "vec_facts_384_info" (key text primary key, value any);
CREATE TABLE IF NOT EXISTS "vec_facts_384_chunks"(chunk_id INTEGER PRIMARY KEY AUTOINCREMENT,size INTEGER NOT NULL,validity BLOB NOT NULL,rowids BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS "vec_facts_384_rowids"(rowid INTEGER PRIMARY KEY AUTOINCREMENT,id,chunk_id INTEGER,chunk_offset INTEGER);
CREATE TABLE IF NOT EXISTS "vec_facts_384_vector_chunks00"(rowid PRIMARY KEY,vectors BLOB NOT NULL);
