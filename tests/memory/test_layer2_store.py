import json


def test_layer2_store_is_available_from_shared_memory_package(tmp_path):
    from memory.layer2_store import Layer2Store, apply_layer2_payload

    store = Layer2Store(tmp_path / "layer2.sqlite3")
    audit = apply_layer2_payload(
        {"id": "shared-layer2-job", "memory_pipeline": {"enabled": True}},
        {
            "observations": [
                {
                    "observation_text": "Shared Layer-2 store import works was directly observed.",
                    "source_event_id": "evt-shared-1",
                }
            ],
            "candidate_events": [
                {
                    "action": "create",
                    "canonical_text": "Shared Layer-2 store import works",
                    "kind": "env_fact",
                    "proposed_target": "memory",
                    "source_event_id": "evt-shared-1",
                }
            ],
        },
        source_ref="test:shared-layer2",
        store=store,
    )

    assert audit[0]["audit_label"] == "candidate_created"
    candidate = store.get_candidate("Shared Layer-2 store import works")
    assert candidate["support_count"] == 1


def test_query_candidates_for_pack_uses_query_text_and_scope_filters(tmp_path):
    from memory.layer2_store import Layer2Store

    store = Layer2Store(tmp_path / "layer2.sqlite3")
    store.record_event(
        event_type="create",
        canonical_text="Repository uses uv for Python dependency management",
        kind="env_fact",
        proposed_target="memory",
        source_ref="test:repo",
        source_event_id="repo-evt-1",
        subject_scope="repo",
        subject_id="hermes-agent",
    )
    store.record_event(
        event_type="strengthen",
        canonical_text="Unrelated high-support user preference",
        kind="preference",
        proposed_target="user",
        source_ref="test:user",
        source_event_id="user-evt-1",
        subject_scope="user",
        subject_id="other-user",
    )
    store.record_event(
        event_type="strengthen",
        canonical_text="Unrelated high-support user preference",
        kind="preference",
        proposed_target="user",
        source_ref="test:user",
        source_event_id="user-evt-2",
        subject_scope="user",
        subject_id="other-user",
    )
    store.record_event(
        event_type="strengthen",
        canonical_text="Unrelated high-support user preference",
        kind="preference",
        proposed_target="user",
        source_ref="test:user",
        source_event_id="user-evt-3",
        subject_scope="user",
        subject_id="other-user",
    )

    results = store.query_candidates_for_pack(
        destinations=["prior", "user"],
        query_text="uv dependency setup",
        subject_scope="repo",
        subject_id="hermes-agent",
        max_items=5,
        min_support_count=1,
    )

    assert [item["canonical_text"] for item in results] == [
        "Repository uses uv for Python dependency management"
    ]


def test_cron_layer2_memory_is_compatibility_facade_for_shared_store():
    import cron.layer2_memory as cron_layer2
    import memory.layer2_store as shared_layer2

    assert cron_layer2.Layer2Store is shared_layer2.Layer2Store
    assert cron_layer2.apply_layer2_payload is shared_layer2.apply_layer2_payload
    assert cron_layer2.parse_layer2_payload is shared_layer2.parse_layer2_payload
    assert cron_layer2.format_layer2_audit_section is shared_layer2.format_layer2_audit_section


def test_layer2_payload_demotes_recurrence_without_linked_observation(tmp_path):
    from memory.layer2_store import Layer2Store, apply_layer2_payload

    store = Layer2Store(tmp_path / "layer2.sqlite3")
    audit = apply_layer2_payload(
        {"id": "evidence-job", "memory_pipeline": {"enabled": True}},
        {
            "candidate_events": [
                {
                    "action": "create",
                    "canonical_text": "Unbacked synthesis should not count as recurrence",
                    "kind": "heuristic",
                    "proposed_target": "memory",
                    "counts_for_recurrence": True,
                    "source_event_id": "candidate-only",
                }
            ]
        },
        source_ref="cron:evidence-job:run-1",
        store=store,
    )

    candidate = store.get_candidate("Unbacked synthesis should not count as recurrence")
    events = store.list_events("Unbacked synthesis should not count as recurrence")
    assert audit[0]["audit_label"] == "unbacked_candidate_demoted"
    assert candidate["support_count"] == 0
    assert events[0]["counts_for_recurrence"] == 0
    assert events[0]["support_delta"] == 0


def test_layer2_payload_counts_recurrence_with_linked_observation(tmp_path):
    from memory.layer2_store import Layer2Store, apply_layer2_payload

    store = Layer2Store(tmp_path / "layer2.sqlite3")
    audit = apply_layer2_payload(
        {"id": "evidence-job", "memory_pipeline": {"enabled": True}},
        {
            "observations": [
                {
                    "observation_text": "Raw source showed the heuristic affected a later decision.",
                    "source_event_id": "raw-evidence-1",
                }
            ],
            "candidate_events": [
                {
                    "action": "create",
                    "canonical_text": "Candidates should count only when linked to raw evidence",
                    "kind": "heuristic",
                    "proposed_target": "memory",
                    "counts_for_recurrence": True,
                    "source_event_id": "candidate-1",
                    "evidence_source_event_id": "raw-evidence-1",
                }
            ],
        },
        source_ref="cron:evidence-job:run-1",
        store=store,
    )

    candidate = store.get_candidate("Candidates should count only when linked to raw evidence")
    events = store.list_events("Candidates should count only when linked to raw evidence")
    labels = [item["audit_label"] for item in audit]
    assert "observation_stored" in labels
    assert "candidate_created" in labels
    assert candidate["support_count"] == 1
    assert events[0]["counts_for_recurrence"] == 1
    assert events[0]["support_delta"] == 1


def test_shared_layer2_payload_keeps_promotion_guardrails(tmp_path):
    from memory.layer2_store import Layer2Store, apply_layer2_payload

    store = Layer2Store(tmp_path / "layer2.sqlite3")
    audit = apply_layer2_payload(
        {"id": "candidate-only", "memory_pipeline": {"enabled": True, "allow_durable_promotion_targets": []}},
        {
            "promotions": [
                {
                    "canonical_text": "Do not promote without allowlist",
                    "target": "memory",
                    "content": "Do not promote without allowlist",
                    "source_event_id": "evt-blocked-promotion",
                }
            ]
        },
        source_ref="test:blocked-promotion",
        store=store,
    )

    assert audit == []
    assert store.get_candidate("Do not promote without allowlist") is None


def test_layer2_candidate_recurrence_requires_matching_observation_evidence(tmp_path):
    from memory.layer2_store import Layer2Store, apply_layer2_payload

    store = Layer2Store(tmp_path / "layer2.sqlite3")
    audit = apply_layer2_payload(
        {"id": "evidence-job", "memory_pipeline": {"enabled": True}},
        {
            "observations": [
                {
                    "observation_text": "Directly checked source supports the rule",
                    "source_event_id": "obs-direct-1",
                }
            ],
            "candidate_events": [
                {
                    "action": "create",
                    "canonical_text": "Evidence-linked candidates can count",
                    "kind": "heuristic",
                    "proposed_target": "memory",
                    "source_event_id": "cand-1",
                    "evidence_source_event_id": "obs-direct-1",
                    "counts_for_recurrence": True,
                }
            ],
        },
        source_ref="test:evidence-linked",
        store=store,
    )

    candidate = store.get_candidate("Evidence-linked candidates can count")
    events = store.list_events("Evidence-linked candidates can count")
    assert any(item["audit_label"] == "candidate_created" for item in audit)
    assert candidate["support_count"] == 1
    assert events[-1]["counts_for_recurrence"] == 1


def test_layer2_candidate_without_observation_evidence_is_demoted(tmp_path):
    from memory.layer2_store import Layer2Store, apply_layer2_payload

    store = Layer2Store(tmp_path / "layer2.sqlite3")
    audit = apply_layer2_payload(
        {"id": "evidence-job", "memory_pipeline": {"enabled": True}},
        {
            "candidate_events": [
                {
                    "action": "create",
                    "canonical_text": "Unbacked candidates should not count",
                    "kind": "heuristic",
                    "proposed_target": "memory",
                    "source_event_id": "cand-unbacked",
                    "counts_for_recurrence": True,
                }
            ]
        },
        source_ref="test:evidence-linked",
        store=store,
    )

    candidate = store.get_candidate("Unbacked candidates should not count")
    events = store.list_events("Unbacked candidates should not count")
    assert audit[0]["audit_label"] == "unbacked_candidate_demoted"
    assert candidate["support_count"] == 0
    assert events[-1]["counts_for_recurrence"] == 0
    assert events[-1]["support_delta"] == 0
