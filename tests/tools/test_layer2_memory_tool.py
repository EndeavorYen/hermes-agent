"""Tests for tools/layer2_memory_tool.py — chat-accessible Layer-2 ledger writes."""

import json

import pytest

from memory.layer2_store import Layer2Store
from tools.layer2_memory_tool import LAYER2_MEMORY_SCHEMA, layer2_memory_tool


@pytest.fixture()
def store(tmp_path):
    return Layer2Store(tmp_path / "layer2.sqlite3")


class TestLayer2MemoryTool:
    def test_unknown_action_returns_error(self, store):
        result = json.loads(layer2_memory_tool(action="nope", store=store))
        assert result["success"] is False
        assert "unknown action" in result["error"].lower()

    def test_write_requires_object_payload(self, store):
        result = json.loads(layer2_memory_tool(action="write", payload=None, store=store))
        assert result["success"] is False
        assert "payload" in result["error"].lower()

    def test_rejects_promotions_on_chat_path(self, store):
        result = json.loads(
            layer2_memory_tool(
                action="write",
                payload={"promotions": [{"target": "memory", "content": "nope"}]},
                store=store,
            )
        )
        assert result["success"] is False
        assert "promotions" in result["error"].lower()
        assert result["issues"][0]["code"] == "promotions_not_allowed"

    def test_records_candidate_event_with_session_provenance(self, store):
        result = json.loads(
            layer2_memory_tool(
                action="write",
                payload={
                    "candidate_events": [
                        {
                            "action": "create",
                            "canonical_text": "需求模糊時先定驗收條件",
                            "kind": "heuristic",
                            "proposed_target": "memory",
                        }
                    ]
                },
                store=store,
                source_ref="chat:slack:s1:tc1",
                session_id="s1",
                tool_call_id="tc1",
            )
        )
        assert result["success"] is True
        assert result["applied_count"] == 1
        candidate = store.get_candidate("需求模糊時先定驗收條件")
        assert candidate is not None
        events = store.list_events("需求模糊時先定驗收條件")
        assert events[0]["session_id"] == "s1"
        assert events[0]["source_ref"] == "chat:slack:s1:tc1"

    def test_records_observation_without_durable_write(self, store, monkeypatch):
        called = {"memory": False}

        def _boom(*args, **kwargs):
            called["memory"] = True
            raise AssertionError("memory tool should not be called")

        monkeypatch.setattr("memory.layer2_store.MemoryStore", _boom)
        result = json.loads(
            layer2_memory_tool(
                action="write",
                payload={
                    "observations": [
                        {
                            "observation_text": "User said 學起來 after a painful debugging lesson",
                            "kind": "chat_observation",
                        }
                    ]
                },
                store=store,
                source_ref="chat:slack:s1:tc2",
                session_id="s1",
                tool_call_id="tc2",
            )
        )
        assert result["success"] is True
        assert called["memory"] is False


class TestLayer2MemoryToolSchema:
    def test_schema_has_write_action(self):
        props = LAYER2_MEMORY_SCHEMA["parameters"]["properties"]
        assert props["action"]["enum"] == ["write"]
        assert "payload" in props
