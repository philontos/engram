-- migration 003: agent execution trace store
--
-- Each agent turn produces a sequence of events:
--   - llm_round  : one LLM call (with full request/response captured)
--   - tool_call  : one tool execution (with full args/result captured)
-- All events for a (session_id, turn_index) share a global seq order so the
-- timeline can be replayed exactly. request_json / response_json are full
-- payloads (capped to 512KB each via the recorder layer).

CREATE TABLE IF NOT EXISTS query_traces (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT    NOT NULL,
    turn_index      INTEGER NOT NULL,
    round_num       INTEGER,
    seq             INTEGER NOT NULL,
    event_type      TEXT    NOT NULL CHECK(event_type IN ('llm_round','tool_call')),
    tool_name       TEXT,
    request_json    TEXT,
    response_json   TEXT,
    latency_ms      INTEGER,
    error           TEXT,
    created_at      TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_query_traces_session_turn ON query_traces(session_id, turn_index, seq);
CREATE INDEX IF NOT EXISTS idx_query_traces_created     ON query_traces(created_at);
