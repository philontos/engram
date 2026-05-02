import sqlite3
import os
from pathlib import Path

DB_PATH = os.getenv("DB_PATH", "./data/cognitive.db")


def get_conn() -> sqlite3.Connection:
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.executescript("""
            -- 第 0 层：原始输入
            CREATE TABLE IF NOT EXISTS entries (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
                type              TEXT NOT NULL,
                raw               TEXT,
                summary           TEXT,
                tags              TEXT,
                mood              TEXT,
                vector_id         INTEGER,
                source            TEXT DEFAULT 'api',
                memory_type       TEXT DEFAULT 'thought',
                importance        INTEGER DEFAULT 3,
                context_json      TEXT DEFAULT '{}',
                metadata_json     TEXT DEFAULT '{}',
                processing_status TEXT DEFAULT 'captured'
            );

            -- 第 1 层：人格切片（per-entry，永久不可变）
            CREATE TABLE IF NOT EXISTS slices (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id   INTEGER NOT NULL REFERENCES entries(id),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS slice_features (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                slice_id     INTEGER NOT NULL REFERENCES slices(id),
                dimension    TEXT NOT NULL,
                content_json TEXT NOT NULL,
                confidence   REAL NOT NULL DEFAULT 0.0,
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- 第 2 层：稳定画像（全量融合态）
            CREATE TABLE IF NOT EXISTS profile_dimensions (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                dimension    TEXT NOT NULL UNIQUE,
                content_json TEXT NOT NULL,
                sample_count INTEGER NOT NULL DEFAULT 0,
                updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- 第 3 层：知识主干网节点
            CREATE TABLE IF NOT EXISTS backbone_nodes (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                domain                TEXT NOT NULL,
                node_type             TEXT NOT NULL,
                label                 TEXT NOT NULL,
                description           TEXT DEFAULT '',
                embedding_json        TEXT,
                origin                TEXT NOT NULL DEFAULT 'internal'
                                          CHECK(origin IN ('internal','external')),
                strength              REAL NOT NULL DEFAULT 0.0,
                hit_count             INTEGER NOT NULL DEFAULT 0,
                last_hit_at           DATETIME,
                source_entry_ids      TEXT NOT NULL DEFAULT '[]',
                current_activation_id INTEGER,
                content_cache_json    TEXT,
                created_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at            DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(domain, label)
            );

            -- 第 3 层：知识主干网关系
            CREATE TABLE IF NOT EXISTS backbone_edges (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                from_node_id        INTEGER NOT NULL REFERENCES backbone_nodes(id),
                to_node_id          INTEGER NOT NULL REFERENCES backbone_nodes(id),
                relation_type       TEXT NOT NULL,
                edge_source         TEXT NOT NULL DEFAULT 'llm'
                                        CHECK(edge_source IN ('llm','algo')),
                weight              REAL NOT NULL DEFAULT 0.0,
                confidence          REAL NOT NULL DEFAULT 0.5,
                last_reinforced_at  DATETIME,
                source_entry_ids    TEXT NOT NULL DEFAULT '[]',
                created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(from_node_id, to_node_id, relation_type)
            );

            -- 节点激活记录（user_relevance 的载体，每次激活追加一条）
            CREATE TABLE IF NOT EXISTS backbone_activations (
                id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                node_id               INTEGER NOT NULL REFERENCES backbone_nodes(id),
                entry_id              INTEGER NOT NULL REFERENCES entries(id),
                user_relevance        TEXT NOT NULL DEFAULT '',
                profile_match_score   REAL NOT NULL DEFAULT 0.0,
                profile_snapshot_json TEXT NOT NULL DEFAULT '{}',
                created_at            DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- 画像快照（每条 entry 处理后保存一次全量 profile 状态，用于演化分析）
            CREATE TABLE IF NOT EXISTS profile_snapshots (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id     INTEGER NOT NULL REFERENCES entries(id),
                snapshot_json TEXT NOT NULL DEFAULT '{}',
                created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            -- 管线运行追踪（每条 entry 一条，可覆盖）
            CREATE TABLE IF NOT EXISTS pipeline_traces (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                entry_id   INTEGER NOT NULL UNIQUE REFERENCES entries(id),
                trace_json TEXT NOT NULL DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_entries_created_at          ON entries(created_at);
            CREATE INDEX IF NOT EXISTS idx_slices_entry_id             ON slices(entry_id);
            CREATE INDEX IF NOT EXISTS idx_slice_features_slice_id     ON slice_features(slice_id);
            CREATE INDEX IF NOT EXISTS idx_slice_features_dimension    ON slice_features(dimension);
            CREATE INDEX IF NOT EXISTS idx_backbone_nodes_domain       ON backbone_nodes(domain);
            CREATE INDEX IF NOT EXISTS idx_backbone_nodes_origin       ON backbone_nodes(origin);
            CREATE INDEX IF NOT EXISTS idx_backbone_nodes_strength     ON backbone_nodes(strength);
            CREATE INDEX IF NOT EXISTS idx_backbone_edges_from         ON backbone_edges(from_node_id);
            CREATE INDEX IF NOT EXISTS idx_backbone_edges_to           ON backbone_edges(to_node_id);
            CREATE INDEX IF NOT EXISTS idx_backbone_edges_relation     ON backbone_edges(relation_type);
            CREATE INDEX IF NOT EXISTS idx_backbone_activations_node   ON backbone_activations(node_id);
            CREATE INDEX IF NOT EXISTS idx_backbone_activations_entry  ON backbone_activations(entry_id);
            CREATE INDEX IF NOT EXISTS idx_pipeline_traces_entry       ON pipeline_traces(entry_id);
            CREATE INDEX IF NOT EXISTS idx_profile_snapshots_entry     ON profile_snapshots(entry_id);
            CREATE INDEX IF NOT EXISTS idx_profile_snapshots_created   ON profile_snapshots(created_at);

            -- 查询记录（一次会话一条，多轮追加到 turns_json）
            CREATE TABLE IF NOT EXISTS query_logs (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id    TEXT,
                question      TEXT NOT NULL,
                mode          TEXT NOT NULL DEFAULT 'full',
                seeds_json    TEXT NOT NULL DEFAULT '[]',
                opposites_json TEXT NOT NULL DEFAULT '[]',
                blindspots_json TEXT NOT NULL DEFAULT '[]',
                q1_text       TEXT NOT NULL DEFAULT '',
                q2_text       TEXT NOT NULL DEFAULT '',
                q3_text       TEXT NOT NULL DEFAULT '',
                q4_text       TEXT NOT NULL DEFAULT '',
                turns_json    TEXT NOT NULL DEFAULT '[]',
                updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
                created_at    DATETIME DEFAULT CURRENT_TIMESTAMP
            );

            CREATE INDEX IF NOT EXISTS idx_query_logs_created ON query_logs(created_at);
        """)
        # 存量表迁移
        pt_cols = {row[1] for row in conn.execute("PRAGMA table_info(pipeline_traces)").fetchall()}
        if "rollback_json" not in pt_cols:
            conn.execute("ALTER TABLE pipeline_traces ADD COLUMN rollback_json TEXT")

        existing = {row[1] for row in conn.execute("PRAGMA table_info(query_logs)").fetchall()}
        for col, ddl in [
            ("session_id", "ALTER TABLE query_logs ADD COLUMN session_id TEXT"),
            ("turns_json", "ALTER TABLE query_logs ADD COLUMN turns_json TEXT NOT NULL DEFAULT '[]'"),
            ("updated_at", "ALTER TABLE query_logs ADD COLUMN updated_at DATETIME DEFAULT NULL"),
        ]:
            if col not in existing:
                conn.execute(ddl)
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_query_logs_session ON query_logs(session_id)")

        # situation_json 迁移：从 slice_features 移动到 entries
        entry_cols = {row[1] for row in conn.execute("PRAGMA table_info(entries)").fetchall()}
        if "situation_json" not in entry_cols:
            conn.execute("ALTER TABLE entries ADD COLUMN situation_json TEXT DEFAULT NULL")
            # 将存量 slice_features.situation 迁移过来
            conn.execute("""
                UPDATE entries SET situation_json = (
                    SELECT sf.content_json
                    FROM slices s
                    JOIN slice_features sf ON sf.slice_id = s.id
                    WHERE s.entry_id = entries.id AND sf.dimension = 'situation'
                    LIMIT 1
                )
                WHERE id IN (
                    SELECT DISTINCT s.entry_id FROM slices s
                    JOIN slice_features sf ON sf.slice_id = s.id
                    WHERE sf.dimension = 'situation'
                )
            """)
            conn.execute("DELETE FROM slice_features WHERE dimension = 'situation'")
