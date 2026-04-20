import json

from agent.reflection import (
    affordance_gap_log_path,
    append_background_review_event,
    append_reflection_record,
    build_reflection_record,
    extract_affordance_gap_entry,
    reflection_log_path,
    should_emit_reflection,
)


def test_build_reflection_record_captures_tools_and_affordance_signals():
    messages = [
        {"role": "user", "content": "inspect and patch"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {"function": {"name": "read_file"}},
                {"function": {"name": "patch"}},
            ],
        },
        {"role": "tool", "content": json.dumps({"success": False, "error": "boom"})},
        {"role": "assistant", "content": "Done"},
    ]

    record = build_reflection_record(
        messages=messages,
        user_message="inspect and patch",
        final_response="Done",
        session_id="sess-1",
        parent_session_id=None,
        model="test-model",
        provider="test-provider",
        platform="cli",
        completed=False,
        interrupted=False,
        partial=False,
        max_user_message_chars=50,
        max_final_response_chars=50,
        post_response_review={"memory": True, "skills": False, "queued": False},
    )

    assert record["session_id"] == "sess-1"
    assert record["tools"]["called"] == 2
    assert record["tools"]["unique"] == ["read_file", "patch"]
    assert record["tools"]["failed"] == 1
    assert "tool_use" in record["affordance"]["needs"]
    assert "workspace_mutation" in record["affordance"]["needs"]
    assert "reflection" in record["affordance"]["needs"]
    assert len(record["prompt"]["task_hash"]) == 64
    assert record["post_response_review"] == {"memory": True, "skills": False, "queued": False}


def test_append_reflection_record_writes_under_hermes_home(tmp_path):
    record = {
        "version": 1,
        "timestamp": "2026-04-20T00:00:00+00:00",
        "session_id": "sess-2",
        "platform": "cli",
        "model": "test-model",
        "provider": "test-provider",
        "prompt": {"user_message": "hello", "task_hash": "abc"},
        "outcome": {"completed": False, "failed": True, "interrupted": False, "partial": False},
        "tools": {"unique": ["read_file"], "failed": 1},
        "affordance": {"needs": ["tool_use", "reflection"], "evidence": ["boom"], "suggested_next": ["inspect"]},
    }
    out_path = append_reflection_record(record, hermes_home=tmp_path)

    assert out_path == reflection_log_path(tmp_path)
    assert out_path.exists()
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["session_id"] == "sess-2"

    gap_path = affordance_gap_log_path(tmp_path)
    assert gap_path.exists()
    gap_lines = gap_path.read_text(encoding="utf-8").splitlines()
    assert len(gap_lines) == 1
    assert json.loads(gap_lines[0])["gap_signals"] == ["reflection"]


def test_extract_affordance_gap_entry_returns_none_for_clean_success():
    record = {
        "outcome": {"completed": True, "failed": False, "interrupted": False, "partial": False},
        "tools": {"failed": 0},
        "affordance": {"needs": ["tool_use"], "evidence": [], "suggested_next": []},
    }

    assert extract_affordance_gap_entry(record) is None


def test_append_background_review_event_writes_under_hermes_home(tmp_path):
    event = {"session_id": "sess-bg", "actions": ["Memory updated"], "summary": "Memory updated"}

    out_path = append_background_review_event(event, hermes_home=tmp_path)

    assert out_path.exists()
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["session_id"] == "sess-bg"


def test_should_emit_reflection_gates_successful_simple_turns():
    simple_messages = [{"role": "assistant", "content": "done"}]
    tool_messages = [
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": "read_file"}}],
        }
    ]

    assert not should_emit_reflection(
        enabled=True,
        messages=simple_messages,
        completed=True,
        interrupted=False,
        partial=False,
        min_tool_turns=2,
    )
    assert should_emit_reflection(
        enabled=True,
        messages=tool_messages,
        completed=False,
        interrupted=False,
        partial=False,
        min_tool_turns=2,
    )
    assert should_emit_reflection(
        enabled=True,
        messages=tool_messages,
        completed=True,
        interrupted=False,
        partial=False,
        min_tool_turns=1,
    )
