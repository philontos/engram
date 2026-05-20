-- 004_contacts.sql — Day-1 contacts root（伏笔/承诺账 anchor）
-- forward-only & idempotent。

CREATE TABLE IF NOT EXISTS contacts (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    display_name             TEXT    NOT NULL,
    aliases_json             TEXT    NOT NULL DEFAULT '[]',
    status                   TEXT    NOT NULL DEFAULT 'candidate'
                                 CHECK(status IN ('candidate','confirmed','merged')),
    merged_into_id           INTEGER REFERENCES contacts(id),
    relationship_kind        TEXT    CHECK(
        relationship_kind IS NULL OR
        relationship_kind IN ('friend','colleague','family','romantic','mentor','client','acquaintance')
    ),
    kind_locked              INTEGER NOT NULL DEFAULT 0 CHECK(kind_locked IN (0,1)),
    field_locks_json         TEXT    NOT NULL DEFAULT '{}',
    active_status            TEXT    CHECK(
        active_status IS NULL OR
        active_status IN ('active','dormant','severed')
    ),
    intimacy_score           REAL    CHECK(intimacy_score IS NULL OR (intimacy_score >= 0 AND intimacy_score <= 1)),
    first_seen_entry_id      INTEGER REFERENCES entries(id),
    last_seen_entry_id       INTEGER REFERENCES entries(id),
    last_interaction_at      DATETIME,
    context_summary          TEXT    NOT NULL DEFAULT '',
    metadata_json            TEXT    NOT NULL DEFAULT '{}',
    created_at               DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at               DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contacts_status             ON contacts(status);
CREATE INDEX IF NOT EXISTS idx_contacts_display_name       ON contacts(display_name);
CREATE INDEX IF NOT EXISTS idx_contacts_last_interaction   ON contacts(last_interaction_at);
CREATE INDEX IF NOT EXISTS idx_contacts_first_seen_entry   ON contacts(first_seen_entry_id);

CREATE TABLE IF NOT EXISTS contact_evidence (
    id                            INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id                    INTEGER REFERENCES contacts(id),
    entry_id                      INTEGER NOT NULL REFERENCES entries(id),
    mention_text                  TEXT    NOT NULL DEFAULT '',
    excerpt                       TEXT    NOT NULL DEFAULT '',
    confidence                    REAL    NOT NULL DEFAULT 0.0,
    suggested_kind                TEXT    CHECK(
        suggested_kind IS NULL OR
        suggested_kind IN ('friend','colleague','family','romantic','mentor','client','acquaintance')
    ),
    ambiguous_candidate_ids_json  TEXT    NOT NULL DEFAULT '[]',
    interaction_observed          INTEGER NOT NULL DEFAULT 0 CHECK(interaction_observed IN (0,1)),
    created_at                    DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_contact_evidence_contact ON contact_evidence(contact_id);
CREATE INDEX IF NOT EXISTS idx_contact_evidence_entry   ON contact_evidence(entry_id);
