"""Contract tests for process_events stage-event schema."""

import json

from app.lib import process_events


def test_emitter_publishes_well_formed_start_event():
    entry_id = 9001
    process_events.init(entry_id)
    emit = process_events.make_emitter(entry_id, started_perf=0.0)

    emit("slice:mbti", "start")

    ch = process_events._channels[entry_id]
    assert len(ch.events) == 1
    ev = ch.events[0]
    assert ev["type"] == "stage"
    assert ev["stage"] == "slice:mbti"
    assert ev["status"] == "start"
    assert "elapsed_ms" in ev and isinstance(ev["elapsed_ms"], int)
    assert "summary" not in ev  # only on done
    assert "payload" not in ev


def test_emitter_publishes_done_event_with_summary_and_payload():
    entry_id = 9002
    process_events.init(entry_id)
    emit = process_events.make_emitter(entry_id, started_perf=0.0)

    payload = {"E_I": {"score": 15, "confidence": 0.6}}
    emit("slice:mbti", "done",
         summary="E_I=15, S_N=null",
         payload=payload)

    ch = process_events._channels[entry_id]
    assert len(ch.events) == 1
    ev = ch.events[0]
    assert ev["status"] == "done"
    assert ev["summary"] == "E_I=15, S_N=null"
    assert ev["payload"] == payload


def test_emitter_truncates_oversize_payload():
    entry_id = 9003
    process_events.init(entry_id)
    emit = process_events.make_emitter(entry_id, started_perf=0.0)

    big_list = [{"label": f"node_{i}", "description": "x" * 100} for i in range(100)]
    emit("node_extract:psychology", "done",
         summary="big payload",
         payload={"candidates": big_list})

    ch = process_events._channels[entry_id]
    ev = ch.events[0]
    serialized = json.dumps(ev["payload"], ensure_ascii=False)
    assert len(serialized) <= 4096
    assert ev["payload"].get("truncated") is True


def test_emitter_passes_through_error_field():
    entry_id = 9004
    process_events.init(entry_id)
    emit = process_events.make_emitter(entry_id, started_perf=0.0)

    emit("slice:facts", "error", error={"type": "LLMError", "message": "..."})

    ch = process_events._channels[entry_id]
    ev = ch.events[0]
    assert ev["status"] == "error"
    assert ev["error"] == {"type": "LLMError", "message": "..."}
