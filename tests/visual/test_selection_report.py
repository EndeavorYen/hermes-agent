def test_visual_selection_report_counts_retry_suppression_and_rank_reason(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.selection_report import build_visual_selection_report

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed")
    first_attempt = ledger.record_attempt(
        request_id=request_id,
        status="failed",
        provider="fixture",
        model="image",
        metadata={"failure": {"failure_class": "empty_response"}},
    )
    retry_attempt = ledger.record_attempt(
        request_id=request_id,
        status="completed",
        provider="fixture",
        model="image",
        metadata={"retry_of": 0},
    )
    selected = ledger.record_artifact(
        request_id=request_id,
        attempt_id=retry_attempt,
        kind="image",
        content_hash="same-hash",
        freshness_status="fresh",
        is_stable=True,
    )
    ledger.record_artifact(
        request_id=request_id,
        attempt_id=first_attempt,
        kind="image",
        content_hash="same-hash",
        freshness_status="fresh",
        is_stable=True,
    )
    ledger.record_artifact(
        request_id=request_id,
        attempt_id=first_attempt,
        kind="image",
        content_hash="stale-hash",
        freshness_status="stale",
        is_stable=False,
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=selected,
        decision="post",
        scores={"ranked_artifact_ids": [selected]},
        metadata={"modality": "image", "active_learning": {"decision": "auto_deliver"}},
    )

    report = build_visual_selection_report(tmp_path / "visual.sqlite3", request_id=request_id)

    assert report["success"] is True
    assert report["request_id"] == request_id
    assert report["counts"]["generated_candidates"] == 3
    assert report["counts"]["retry_count"] == 1
    assert report["counts"]["suppressed_duplicate"] == 1
    assert report["counts"]["suppressed_stale"] == 1
    assert report["selected_artifact_ids"] == [selected]
    assert report["failure_classes"] == {"empty_response": 1}
    assert report["rank_reasons"] == ["post"]


def test_visual_selection_report_missing_ledger_is_success(tmp_path):
    from agent.visual.selection_report import build_visual_selection_report

    report = build_visual_selection_report(tmp_path / "missing.sqlite3")

    assert report["success"] is True
    assert report["counts"]["generated_candidates"] == 0
