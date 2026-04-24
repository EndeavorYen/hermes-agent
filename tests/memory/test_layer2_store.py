import json


def test_layer2_store_is_available_from_shared_memory_package(tmp_path):
    from memory.layer2_store import Layer2Store, apply_layer2_payload

    store = Layer2Store(tmp_path / "layer2.sqlite3")
    audit = apply_layer2_payload(
        {"id": "shared-layer2-job", "memory_pipeline": {"enabled": True}},
        {
            "candidate_events": [
                {
                    "action": "create",
                    "canonical_text": "Shared Layer-2 store import works",
                    "kind": "env_fact",
                    "proposed_target": "memory",
                    "source_event_id": "evt-shared-1",
                }
            ]
        },
        source_ref="test:shared-layer2",
        store=store,
    )

    assert audit[0]["audit_label"] == "candidate_created"
    candidate = store.get_candidate("Shared Layer-2 store import works")
    assert candidate["support_count"] == 1


def test_cron_layer2_memory_is_compatibility_facade_for_shared_store():
    import cron.layer2_memory as cron_layer2
    import memory.layer2_store as shared_layer2

    assert cron_layer2.Layer2Store is shared_layer2.Layer2Store
    assert cron_layer2.apply_layer2_payload is shared_layer2.apply_layer2_payload
    assert cron_layer2.parse_layer2_payload is shared_layer2.parse_layer2_payload
    assert cron_layer2.format_layer2_audit_section is shared_layer2.format_layer2_audit_section


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
