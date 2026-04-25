import json

from memory.layer2_store import Layer2Store
from tools.layer2_review_tool import layer2_review_tool


def test_layer2_review_lists_candidates_with_counts_and_filters(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Repository uses uv",
        kind="env_fact",
        proposed_target="memory",
        source_ref="test:repo",
        source_event_id="evt-uv",
        subject_scope="repo",
        subject_id="hermes-agent",
    )
    store.record_event(
        event_type="create",
        canonical_text="User prefers concise answers",
        kind="preference",
        proposed_target="user",
        source_ref="test:user",
        source_event_id="evt-user",
        subject_scope="user",
        subject_id="simon",
    )

    result = json.loads(
        layer2_review_tool(
            action="list_candidates",
            store=store,
            query_text="uv repo",
            subject_scope="repo",
            subject_id="hermes-agent",
        )
    )

    assert result["success"] is True
    assert [item["canonical_text"] for item in result["candidates"]] == ["Repository uses uv"]
    assert result["candidates"][0]["support_count"] == 1
    assert "Repository uses uv" in result["markdown"]


def test_layer2_review_can_list_stale_candidates_by_status(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Stale candidate",
        kind="fact",
        proposed_target="memory",
        status="stale",
        source_ref="test:stale",
        source_event_id="evt-stale",
    )
    store.record_event(
        event_type="create",
        canonical_text="Active candidate",
        kind="fact",
        proposed_target="memory",
        source_ref="test:active",
        source_event_id="evt-active",
    )

    result = json.loads(layer2_review_tool(action="list_candidates", status="stale", store=store))

    assert result["success"] is True
    assert [item["canonical_text"] for item in result["candidates"]] == ["Stale candidate"]


def test_layer2_review_inspects_candidate_event_history(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Inspectable candidate",
        kind="fact",
        proposed_target="memory",
        source_ref="test:inspect",
        source_event_id="evt-1",
    )
    store.record_event(
        event_type="strengthen",
        canonical_text="Inspectable candidate",
        source_ref="test:inspect",
        source_event_id="evt-2",
        event_ts="2026-04-26T00:00:00+00:00",
    )

    result = json.loads(
        layer2_review_tool(action="inspect_candidate", canonical_text="Inspectable candidate", store=store)
    )

    assert result["success"] is True
    assert result["candidate"]["canonical_text"] == "Inspectable candidate"
    assert result["event_count"] == 2
    assert [event["source_event_id"] for event in result["events"]] == ["evt-1", "evt-2"]


def test_layer2_review_prunes_candidate_without_deleting_history(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Stale candidate",
        kind="fact",
        proposed_target="memory",
        source_ref="test:stale",
        source_event_id="evt-stale",
    )

    result = json.loads(
        layer2_review_tool(
            action="prune_candidate",
            store=store,
            canonical_text="Stale candidate",
            notes="operator rejected",
            source_ref="operator:test",
        )
    )

    assert result["success"] is True
    assert result["audit_event"]["audit_label"] == "candidate_pruned"
    assert store.get_candidate("Stale candidate")["status"] == "pruned"
    events = store.list_events("Stale candidate")
    assert [event["event_type"] for event in events] == ["create", "prune"]


def test_layer2_review_promotes_allowlisted_candidate_to_memory_store(tmp_path, monkeypatch):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Repository uses uv",
        kind="env_fact",
        proposed_target="memory",
        source_ref="test:repo",
        source_event_id="evt-uv",
    )

    added = []

    class FakeMemoryStore:
        def load_from_disk(self):
            pass

        def add(self, target, content):
            added.append((target, content))
            return {"success": True}

    monkeypatch.setattr("memory.layer2_store.MemoryStore", FakeMemoryStore)

    result = json.loads(
        layer2_review_tool(
            action="promote_candidate",
            store=store,
            canonical_text="Repository uses uv",
            target="memory",
            content="Repository uses uv",
            source_ref="operator:test",
        )
    )

    assert result["success"] is True
    assert added == [("memory", "Repository uses uv")]
    assert any(event["audit_label"] == "durable_write" for event in result["audit_events"])
    assert store.get_candidate("Repository uses uv")["status"] == "promoted"
