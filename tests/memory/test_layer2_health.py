from memory.layer2_health import build_layer2_health_report
from memory.layer2_store import Layer2Store


def test_build_layer2_health_report_surfaces_actionable_queues(tmp_path):
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

    report = build_layer2_health_report(store=store, max_items=5)

    assert report.counts_by_status["active"] == 2
    assert report.promotion_candidates[0]["canonical_text"] == "High value user preference"
    assert report.contradiction_candidates[0]["canonical_text"] == "Contradicted rule"
    assert "High value user preference" in report.markdown
