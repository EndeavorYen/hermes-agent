from __future__ import annotations


def test_allows_same_artifact_for_different_request_but_not_same_request_destination():
    from agent.visual.delivery_dedupe import ArtifactDeliveryDeduper

    dedupe = ArtifactDeliveryDeduper(ttl_seconds=3600)
    assert dedupe.mark_if_new("sha256:a", "slack:C1:T1", "vrq_1") is True
    assert dedupe.mark_if_new("sha256:a", "slack:C1:T1", "vrq_1") is False
    assert dedupe.mark_if_new("sha256:a", "slack:C1:T1", "vrq_2") is True


def test_rejects_missing_artifact_hash():
    from agent.visual.delivery_dedupe import ArtifactDeliveryDeduper

    dedupe = ArtifactDeliveryDeduper()
    assert dedupe.mark_if_new("", "slack:C1:T1", "vrq_1") is False


def test_expires_old_entries_with_injected_clock():
    from agent.visual.delivery_dedupe import ArtifactDeliveryDeduper

    now = [100.0]
    dedupe = ArtifactDeliveryDeduper(ttl_seconds=10, now=lambda: now[0])

    assert dedupe.mark_if_new("sha256:a", "slack:C1:T1", "vrq_1") is True
    assert dedupe.mark_if_new("sha256:a", "slack:C1:T1", "vrq_1") is False

    now[0] = 111.0
    assert dedupe.mark_if_new("sha256:a", "slack:C1:T1", "vrq_1") is True
