def test_provider_reliability_counts_success_policy_and_delivery_separately(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.provider_stats import compute_provider_reliability

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    good_attempt = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="image",
        status="completed",
    )
    bad_attempt = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="image",
        status="failed",
        error_type="content_moderation",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=good_attempt,
        kind="image",
        content_hash="abc",
        mime_type="image/png",
        freshness_status="fresh",
        is_stable=True,
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=good_attempt,
        artifact_id=artifact_id,
        delivery_status="sent",
    )

    stats = compute_provider_reliability(ledger, bucket="visig_demo")

    assert stats["xai:image"]["attempt_count"] == 2
    assert stats["xai:image"]["generation_success_rate"] == 0.5
    assert stats["xai:image"]["delivery_success_rate"] == 1.0
    assert stats["xai:image"]["policy_failure_rate"] == 0.5


def test_visual_evidence_report_includes_provider_reliability(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from scripts.visual_evidence_report import build_visual_evidence_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="image",
        status="completed",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/current.png",
        content_hash="abc",
        mime_type="image/png",
        freshness_status="fresh",
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        destination="slack:C:T",
        delivery_status="sent",
    )

    report = build_visual_evidence_report(tmp_path / "visual.sqlite3", request_id=request_id)

    assert report["provider_reliability"]["top"] == [
        {
            "provider_model": "xai:image",
            "attempt_count": 1,
            "generation_success_rate": 1.0,
            "delivery_success_rate": 1.0,
            "policy_failure_rate": 0.0,
        }
    ]


def test_top_provider_reliability_tie_breaks_by_provider_model(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.provider_stats import top_provider_reliability

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    for provider, model in (("fixture", "video"), ("fixture", "image")):
        attempt_id = ledger.record_attempt(
            request_id=request_id,
            provider=provider,
            model=model,
            status="completed",
        )
        artifact_id = ledger.record_artifact(
            request_id=request_id,
            attempt_id=attempt_id,
            kind="image",
            content_hash=f"{provider}:{model}",
            freshness_status="fresh",
        )
        ledger.record_delivery(
            request_id=request_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            delivery_status="sent",
        )

    top = top_provider_reliability(ledger)

    assert [row["provider_model"] for row in top] == [
        "fixture:image",
        "fixture:video",
    ]
