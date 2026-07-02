-- Drydock schema v1 (flattened from orbit-public migrations 0001-0022, adapted to SQLite).
-- Authoritative over the DESIGN.md sketch. Applied via PRAGMA user_version.

-- ────────────────────────────── PM plane (ported) ──────────────────────────────

CREATE TABLE projects (
    id            TEXT PRIMARY KEY,
    slug          TEXT NOT NULL UNIQUE,
    name          TEXT NOT NULL,
    description   TEXT,
    root_path     TEXT,
    git_remote    TEXT,
    ticket_prefix TEXT NOT NULL DEFAULT 'TCK',
    ticket_seq    INTEGER NOT NULL DEFAULT 0,
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at    TEXT NOT NULL
);

CREATE TABLE repos (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    path       TEXT NOT NULL,
    name       TEXT NOT NULL,
    git_remote TEXT,
    is_primary INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX idx_repos_project ON repos(project_id);

CREATE TABLE tickets (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    key        TEXT NOT NULL,                  -- e.g. TCK-102 (project prefix + seq)
    title      TEXT NOT NULL,
    body       TEXT,
    status     TEXT NOT NULL DEFAULT 'open'
               CHECK (status IN ('open','ready','in_progress','review','done','archived')),
    priority   INTEGER NOT NULL DEFAULT 2,     -- 0=P0 .. 3=P3
    assignee_agent_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (project_id, key)
);
CREATE INDEX idx_tickets_project_status ON tickets(project_id, status);

CREATE TABLE work_items (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ticket_id  TEXT REFERENCES tickets(id) ON DELETE SET NULL,
    type       TEXT NOT NULL DEFAULT 'task',
    title      TEXT NOT NULL,
    body       TEXT,
    status     TEXT NOT NULL DEFAULT 'open'
               CHECK (status IN ('open','in_progress','blocked','review','done','archived')),
    priority   INTEGER NOT NULL DEFAULT 2,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_work_items_project_status ON work_items(project_id, status);
CREATE INDEX idx_work_items_ticket ON work_items(ticket_id);

CREATE TABLE memories (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL DEFAULT 'episodic',   -- episodic|semantic|procedural|reference
    title         TEXT,
    body          TEXT NOT NULL,
    tags_json     TEXT NOT NULL DEFAULT '[]',
    source        TEXT,
    source_trust  TEXT NOT NULL DEFAULT 'inferred',   -- user_asserted|inferred|imported
    importance    REAL NOT NULL DEFAULT 0.5,
    pinned        INTEGER NOT NULL DEFAULT 0,
    tier          TEXT NOT NULL DEFAULT 'hot',        -- hot|warm|cold
    valid_to      TEXT,                               -- NULL = still valid
    chroma_id     TEXT,                               -- set when embedded
    last_accessed TEXT,
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_memories_project ON memories(project_id, pinned, tier);

CREATE TABLE decisions (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    title         TEXT NOT NULL,
    rationale     TEXT,
    alternatives_json TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','superseded')),
    supersedes_id TEXT REFERENCES decisions(id),
    ticket_id     TEXT REFERENCES tickets(id) ON DELETE SET NULL,
    created_at    TEXT NOT NULL
);
CREATE INDEX idx_decisions_project_status ON decisions(project_id, status);

CREATE TABLE handoffs (
    id            TEXT PRIMARY KEY,
    project_id    TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    summary       TEXT,
    current_state TEXT,
    next_steps_json TEXT NOT NULL DEFAULT '[]',
    blockers_json TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','consumed')),
    run_id        TEXT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE INDEX idx_handoffs_project_status ON handoffs(project_id, status);

CREATE TABLE attempts (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    work_item_id TEXT REFERENCES work_items(id) ON DELETE SET NULL,
    what_tried   TEXT NOT NULL,
    outcome      TEXT NOT NULL,
    why          TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE entities (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,                        -- file|module|concept|agent
    name       TEXT NOT NULL,
    meta_json  TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    UNIQUE (project_id, kind, name)
);

CREATE TABLE relationships (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    src_type   TEXT NOT NULL,                        -- memory|work_item|ticket|entity|decision
    src_id     TEXT NOT NULL,
    dst_type   TEXT NOT NULL,
    dst_id     TEXT NOT NULL,
    relation   TEXT NOT NULL,                        -- mentions|co_changed|part_of|scopes|plan_for
    weight     REAL NOT NULL DEFAULT 1.0,
    valid_to   TEXT,                                 -- NULL = live edge (temporal graph)
    created_at TEXT NOT NULL
);
CREATE UNIQUE INDEX idx_rel_live ON relationships(project_id, src_type, src_id, dst_type, dst_id, relation)
    WHERE valid_to IS NULL;
CREATE INDEX idx_rel_dst ON relationships(project_id, dst_type, dst_id, relation);

CREATE TABLE skills (
    id          TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    body        TEXT,
    steps_json  TEXT NOT NULL DEFAULT '[]',
    level       TEXT NOT NULL DEFAULT 'skill' CHECK (level IN ('macro','skill','sub_agent')),
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    UNIQUE (project_id, name)
);

-- ────────────────────────────── agents & runtime ──────────────────────────────

CREATE TABLE agents (
    id            TEXT PRIMARY KEY,
    project_id    TEXT REFERENCES projects(id) ON DELETE CASCADE,   -- NULL = global
    name          TEXT NOT NULL,
    description   TEXT,
    definition_md TEXT,                              -- full markdown source
    definition_json TEXT NOT NULL DEFAULT '{}',      -- parsed frontmatter
    model         TEXT,
    tools_json    TEXT NOT NULL DEFAULT '[]',
    policy_yaml   TEXT,                              -- compiled aegis policy
    version       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    UNIQUE (project_id, name)
);

CREATE TABLE runs (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_id     TEXT REFERENCES agents(id),
    ticket_id    TEXT REFERENCES tickets(id),
    work_item_id TEXT REFERENCES work_items(id),
    workspace_id TEXT,
    status       TEXT NOT NULL DEFAULT 'queued'
                 CHECK (status IN ('queued','running','waiting','done','failed','killed')),
    runner       TEXT NOT NULL DEFAULT 'native',    -- native|claude|codex|shell
    tier         INTEGER NOT NULL DEFAULT 0,
    model        TEXT,
    started_at   TEXT,
    ended_at     TEXT,
    tokens_in    INTEGER NOT NULL DEFAULT 0,
    tokens_out   INTEGER NOT NULL DEFAULT 0,
    cost_cents   INTEGER NOT NULL DEFAULT 0,
    summary      TEXT
);
CREATE INDEX idx_runs_project_status ON runs(project_id, status);

CREATE TABLE run_events (
    id      TEXT PRIMARY KEY,
    run_id  TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    seq     INTEGER NOT NULL,
    type    TEXT NOT NULL,        -- message|tool_call|tool_result|decision|status
    payload_json TEXT NOT NULL DEFAULT '{}',
    ts      TEXT NOT NULL,
    UNIQUE (run_id, seq)
);

CREATE TABLE workspaces (
    id           TEXT PRIMARY KEY,
    project_id   TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    run_id       TEXT,
    tier         INTEGER NOT NULL DEFAULT 0,
    kind         TEXT NOT NULL DEFAULT 'worktree',   -- worktree|dir|wsl|container
    path         TEXT,
    wsl_distro   TEXT,
    container_id TEXT,
    base_commit  TEXT,
    branch       TEXT,
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active','merged','discarded')),
    created_at   TEXT NOT NULL
);

-- ────────────────────────────── governance (aegis sink) ──────────────────────────────

CREATE TABLE audit (
    id             TEXT PRIMARY KEY,
    run_id         TEXT,                             -- native runtime runs
    ext_session_id TEXT,                             -- external hook capture (Claude Code)
    ts             TEXT NOT NULL,
    event          TEXT,
    tool           TEXT,
    action         TEXT,
    decision       TEXT NOT NULL CHECK (decision IN ('allow','deny','ask')),
    rule           TEXT,
    message        TEXT,
    args_json      TEXT NOT NULL DEFAULT '{}',
    identity       TEXT,
    tokens_json    TEXT
);
CREATE INDEX idx_audit_run ON audit(run_id);
CREATE INDEX idx_audit_ts ON audit(ts);

CREATE TABLE asks (
    id          TEXT PRIMARY KEY,
    run_id      TEXT NOT NULL,
    audit_id    TEXT NOT NULL REFERENCES audit(id),
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','approved_once','always','denied','expired')),
    resolved_by TEXT,
    resolved_at TEXT,
    expires_at  TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX idx_asks_status ON asks(status);

CREATE TABLE policy_grants (
    id         TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    agent_id   TEXT REFERENCES agents(id),
    rule       TEXT NOT NULL,
    scope_json TEXT NOT NULL DEFAULT '{}',
    created_by TEXT,
    created_at TEXT NOT NULL
);

-- ambient capture (orbit events table; optional hook integration Phase 2)
CREATE TABLE events (
    id         TEXT PRIMARY KEY,
    project_id TEXT REFERENCES projects(id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    tool       TEXT,
    args_json  TEXT,
    outcome    TEXT,
    session_id TEXT,
    created_at TEXT NOT NULL
);

-- ────────────────────────────── FTS5 (hybrid recall, lexical leg) ──────────────────────────────

CREATE VIRTUAL TABLE memories_fts USING fts5(
    title, body, content='memories', content_rowid='rowid'
);
CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, title, body) VALUES (new.rowid, new.title, new.body);
END;
CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, title, body) VALUES ('delete', old.rowid, old.title, old.body);
END;
CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, title, body) VALUES ('delete', old.rowid, old.title, old.body);
    INSERT INTO memories_fts(rowid, title, body) VALUES (new.rowid, new.title, new.body);
END;

CREATE VIRTUAL TABLE tickets_fts USING fts5(
    key, title, body, content='tickets', content_rowid='rowid'
);
CREATE TRIGGER tickets_ai AFTER INSERT ON tickets BEGIN
    INSERT INTO tickets_fts(rowid, key, title, body) VALUES (new.rowid, new.key, new.title, new.body);
END;
CREATE TRIGGER tickets_ad AFTER DELETE ON tickets BEGIN
    INSERT INTO tickets_fts(tickets_fts, rowid, key, title, body) VALUES ('delete', old.rowid, old.key, old.title, old.body);
END;
CREATE TRIGGER tickets_au AFTER UPDATE ON tickets BEGIN
    INSERT INTO tickets_fts(tickets_fts, rowid, key, title, body) VALUES ('delete', old.rowid, old.key, old.title, old.body);
    INSERT INTO tickets_fts(rowid, key, title, body) VALUES (new.rowid, new.key, new.title, new.body);
END;

CREATE VIRTUAL TABLE decisions_fts USING fts5(
    title, rationale, content='decisions', content_rowid='rowid'
);
CREATE TRIGGER decisions_ai AFTER INSERT ON decisions BEGIN
    INSERT INTO decisions_fts(rowid, title, rationale) VALUES (new.rowid, new.title, new.rationale);
END;
CREATE TRIGGER decisions_ad AFTER DELETE ON decisions BEGIN
    INSERT INTO decisions_fts(decisions_fts, rowid, title, rationale) VALUES ('delete', old.rowid, old.title, old.rationale);
END;
CREATE TRIGGER decisions_au AFTER UPDATE ON decisions BEGIN
    INSERT INTO decisions_fts(decisions_fts, rowid, title, rationale) VALUES ('delete', old.rowid, old.title, old.rationale);
    INSERT INTO decisions_fts(rowid, title, rationale) VALUES (new.rowid, new.title, new.rationale);
END;
