def test_artifact_delivery_deduper_scopes_hash_by_destination_and_request():
    from agent.visual.delivery_dedupe import ArtifactDeliveryDeduper

    deduper = ArtifactDeliveryDeduper(ttl_seconds=60)

    assert deduper.mark_if_new("sha256:a", "slack:C1:T1", "vrq_1") is True
    assert deduper.mark_if_new("sha256:a", "slack:C1:T1", "vrq_1") is False
    assert deduper.mark_if_new("sha256:a", "slack:C1:T1", "vrq_2") is True
    assert deduper.mark_if_new("sha256:a", "slack:C2:T1", "vrq_1") is True
