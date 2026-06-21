def test_attempt_ledger_records_request_attempt_artifact_and_delivery(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger = VisualAttemptLedger(tmp_path / "attempts.sqlite3")
    ledger.initialize()

    request_id = ledger.record_request(
        user_prompt="redacted user prompt",
        normalized_intent={"modality": "image", "operation": "text_to_image"},
        modality="image",
        operation="text_to_image",
        platform="slack",
        channel_id="C123",
        thread_id="T123",
        user_id="U123",
        message_id="M123",
        conversation_id="slack:C123",
        status="completed",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        candidate_index=0,
        provider="xai",
        model="grok-imagine-image",
        prompt_original="redacted user prompt",
        prompt_mediated="compiled prompt",
        parameters_requested={"aspect_ratio": "16:9"},
        parameters_effective={"aspect_ratio": "16:9"},
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/generated.png",
        content_hash="sha256:test",
        mime_type="image/png",
        bytes=12,
        width=1280,
        height=720,
        is_stable=True,
        freshness_status="fresh",
    )
    delivery_id = ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        platform="slack",
        destination_id="C123",
        thread_id="T123",
        message_id="M456",
        delivery_status="sent",
    )

    assert ledger.get_request(request_id)["platform"] == "slack"
    assert ledger.get_request(request_id)["normalized_intent"] == {
        "modality": "image",
        "operation": "text_to_image",
    }
    assert ledger.get_attempt(attempt_id)["provider"] == "xai"
    assert ledger.get_attempt(attempt_id)["parameters_effective"] == {
        "aspect_ratio": "16:9",
    }
    assert ledger.get_artifact(artifact_id)["freshness_status"] == "fresh"
    assert ledger.get_artifact(artifact_id)["is_stable"] is True
    assert ledger.get_delivery(delivery_id)["delivery_status"] == "sent"


def test_attempt_ledger_records_judgment_ranking_and_feedback(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger = VisualAttemptLedger(tmp_path / "attempts.sqlite3")
    ledger.initialize()

    request_id = ledger.record_request(
        normalized_intent={"modality": "image"},
        modality="image",
        operation="text_to_image",
        status="completed",
    )
    attempt_id = ledger.record_attempt(request_id=request_id, provider="xai")
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        content_hash="sha256:test",
    )
    judgment_id = ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="deterministic_judge.v0.1",
        score=0.8,
        verdict="pass",
        details={"fresh": True},
    )
    ranking_id = ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_id,
        decision="post",
        scores={"deterministic": 0.8},
    )
    feedback_id = ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="good composition",
        polarity=1.0,
        parsed={"signals": ["composition_positive"]},
    )

    assert ledger.get_judgment(judgment_id)["details"] == {"fresh": True}
    assert ledger.get_ranking(ranking_id)["scores"] == {"deterministic": 0.8}
    assert ledger.get_feedback(feedback_id)["parsed"] == {
        "signals": ["composition_positive"],
    }


def test_attempt_ledger_writes_legacy_runtime_schema(tmp_path):
    import sqlite3

    from agent.visual.attempt_ledger import VisualAttemptLedger

    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE visual_requests (
                request_id TEXT PRIMARY KEY,
                user_prompt TEXT NOT NULL,
                normalized_intent_json TEXT NOT NULL,
                modality TEXT NOT NULL,
                operation TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE visual_attempts (
                attempt_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                candidate_index INTEGER NOT NULL,
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                prompt_original TEXT NOT NULL,
                prompt_mediated TEXT NOT NULL,
                parameters_requested_json TEXT,
                parameters_effective_json TEXT,
                provider_error_type TEXT,
                provider_error_message TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE visual_artifacts (
                artifact_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                local_path TEXT,
                source_url TEXT,
                content_hash TEXT,
                mime_type TEXT,
                is_stable INTEGER NOT NULL,
                freshness_status TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE visual_deliveries (
                delivery_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                destination_id TEXT NOT NULL,
                thread_id TEXT,
                delivery_status TEXT NOT NULL,
                created_at TEXT
            );
            CREATE TABLE visual_feedback (
                feedback_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                artifact_id TEXT,
                feedback_type TEXT NOT NULL,
                polarity REAL,
                raw_text TEXT,
                parsed_json TEXT,
                created_at TEXT NOT NULL
            );
            """
        )

    ledger = VisualAttemptLedger(db_path)
    ledger.initialize()
    request_id = ledger.record_request(
        user_prompt="redacted",
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="completed",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="fixture",
        model="fixture-model",
        prompt_original="redacted",
        prompt_mediated="redacted",
        parameters_requested={"aspect_ratio": "16:9"},
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/current.png",
        content_hash="sha256:current",
        freshness_status="fresh",
        is_stable=True,
    )
    delivery_id = ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        platform="slack",
        destination_id="C123",
        delivery_status="sent",
    )
    feedback_id = ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="第 1 張不錯",
        polarity=1.0,
        parsed={"selection_hint": 1},
        metadata={"source": "slack_feedback_ingestion"},
    )

    assert ledger.get_request(request_id)["normalized_intent_json"] == {"kind": "visual_package"}
    assert ledger.get_attempt(attempt_id)["parameters_requested_json"] == {"aspect_ratio": "16:9"}
    assert ledger.get_artifact(artifact_id)["source_url"] is None
    assert ledger.get_delivery(delivery_id)["delivery_status"] == "sent"
    assert ledger.get_feedback(feedback_id)["parsed_json"] == {"selection_hint": 1}
