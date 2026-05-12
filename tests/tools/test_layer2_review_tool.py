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
    for idx in range(2, 5):
        store.record_event(
            event_type="strengthen",
            canonical_text="Repository uses uv",
            source_ref="test:repo",
            source_event_id=f"evt-uv-{idx}",
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


def test_layer2_review_blocks_promotion_when_l1_pressure_is_high(tmp_path, monkeypatch):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Repository uses uv",
        kind="env_fact",
        proposed_target="memory",
        source_ref="test:repo",
        source_event_id="evt-uv-1",
    )
    for idx in range(2, 5):
        store.record_event(
            event_type="strengthen",
            canonical_text="Repository uses uv",
            source_ref="test:repo",
            source_event_id=f"evt-uv-{idx}",
        )

    added = []

    class FakeMemoryStore:
        def __init__(self):
            self.memory_entries = ["x" * 2150]
            self.user_entries = []
            self.memory_char_limit = 2200
            self.user_char_limit = 2200

        def load_from_disk(self):
            pass

        def add(self, target, content):
            added.append((target, content))
            return {"success": True}

    monkeypatch.setattr("tools.layer2_review_tool.MemoryStore", FakeMemoryStore)

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

    assert result["success"] is False
    assert result["promotion_decision"]["reason"] == "l1_pressure_too_high"
    assert result["promotion_decision"]["recommended_action"] == "keep_in_layer2"
    assert added == []
    assert store.get_candidate("Repository uses uv")["status"] == "active"


def test_layer2_review_health_report_returns_actionable_queues(tmp_path):
    store = Layer2Store(tmp_path / "layer2.sqlite3")
    for idx in range(4):
        store.record_event(
            event_type="strengthen" if idx else "create",
            canonical_text="High value user preference",
            kind="preference",
            proposed_target="user",
            source_ref=f"test:{idx}",
            source_event_id=f"evt-user-{idx}",
        )
    store.record_event(
        event_type="create",
        canonical_text="Contradicted rule",
        kind="heuristic",
        proposed_target="memory",
        source_ref="test:c1",
        source_event_id="evt-c1",
    )
    store.record_event(
        event_type="contradict",
        canonical_text="Contradicted rule",
        source_ref="test:c2",
        source_event_id="evt-c2",
    )

    result = json.loads(layer2_review_tool(action="health_report", store=store, max_items=5))

    assert result["success"] is True
    assert result["counts_by_status"]["active"] == 2
    assert result["promotion_candidates"][0]["canonical_text"] == "High value user preference"
    assert result["contradiction_candidates"][0]["canonical_text"] == "Contradicted rule"
    assert "## Layer-2 Health" in result["markdown"]
