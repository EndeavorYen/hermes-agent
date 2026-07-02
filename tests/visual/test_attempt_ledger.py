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


def test_attempt_ledger_finds_latest_delivered_prompt_context_by_thread(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger = VisualAttemptLedger(tmp_path / "attempts.sqlite3")
    ledger.initialize()

    request_id = ledger.record_request(user_prompt="first user prompt", status="completed")
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine",
        prompt_original="first original prompt",
        prompt_mediated="first provider prompt",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/first.png",
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        platform="slack",
        destination_id="D1",
        thread_id="T1",
        delivery_status="sent",
    )

    other_request_id = ledger.record_request(user_prompt="other thread prompt", status="completed")
    other_attempt_id = ledger.record_attempt(
        request_id=other_request_id,
        provider="openai",
        model="image2",
        prompt_original="other original prompt",
        prompt_mediated="other provider prompt",
    )
    other_artifact_id = ledger.record_artifact(
        request_id=other_request_id,
        attempt_id=other_attempt_id,
        kind="image",
        local_path="/tmp/other.png",
    )
    ledger.record_delivery(
        request_id=other_request_id,
        attempt_id=other_attempt_id,
        artifact_id=other_artifact_id,
        platform="slack",
        destination_id="D1",
        thread_id="T2",
        delivery_status="sent",
    )

    latest_request_id = ledger.record_request(user_prompt="latest user prompt", status="completed")
    latest_attempt_id = ledger.record_attempt(
        request_id=latest_request_id,
        provider="xai",
        model="grok-imagine-quality",
        prompt_original="latest original prompt",
        prompt_mediated="latest provider prompt",
    )
    latest_artifact_id = ledger.record_artifact(
        request_id=latest_request_id,
        attempt_id=latest_attempt_id,
        kind="image",
        local_path="/tmp/latest.png",
    )
    ledger.record_delivery(
        request_id=latest_request_id,
        attempt_id=latest_attempt_id,
        artifact_id=latest_artifact_id,
        platform="slack",
        destination_id="D1",
        thread_id="T1",
        delivery_status="sent",
    )

    context = ledger.latest_delivered_prompt_context(
        platform="slack",
        destination_id="D1",
        thread_id="T1",
    )

    assert context == {
        "request_id": latest_request_id,
        "attempt_id": latest_attempt_id,
        "artifact_id": latest_artifact_id,
        "delivery_id": context["delivery_id"],
        "user_prompt": "latest user prompt",
        "prompt_original": "latest original prompt",
        "prompt_mediated": "latest provider prompt",
        "provider": "xai",
        "model": "grok-imagine-quality",
        "platform": "slack",
        "destination_id": "D1",
        "thread_id": "T1",
        "created_at": context["created_at"],
    }


def test_attempt_ledger_finds_prompt_context_via_artifact_when_delivery_attempt_missing(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger = VisualAttemptLedger(tmp_path / "attempts.sqlite3")
    ledger.initialize()

    request_id = ledger.record_request(user_prompt="raw prompt", status="completed")
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine-quality",
        prompt_original="clean user prompt",
        prompt_mediated="provider-ready visual prompt",
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/generated.png",
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=None,
        artifact_id=artifact_id,
        platform="slack",
        destination_id="D1",
        thread_id="T1",
        delivery_status="sent",
    )

    context = ledger.latest_delivered_prompt_context(
        platform="slack",
        destination_id="D1",
        thread_id="T1",
    )

    assert context is not None
    assert context["attempt_id"] == attempt_id
    assert context["prompt_original"] == "clean user prompt"
    assert context["prompt_mediated"] == "provider-ready visual prompt"


def test_attempt_ledger_updates_request_status(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger = VisualAttemptLedger(tmp_path / "attempts.sqlite3")
    ledger.initialize()

    request_id = ledger.record_request(
        normalized_intent={"kind": "visual_package"},
        modality="package",
        operation="visual_package_generate",
        status="started",
    )

    ledger.update_request_status(request_id, "completed")

    assert ledger.get_request(request_id)["status"] == "completed"


def test_attempt_ledger_records_input_artifacts_for_reference_conditioning(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger

    ledger = VisualAttemptLedger(tmp_path / "attempts.sqlite3")
    ledger.initialize()

    request_id = ledger.record_request(
        normalized_intent={"modality": "image"},
        modality="image",
        operation="reference_image_edit",
        status="started",
    )
    attempt_id = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine-image-quality",
        input_artifacts=[
            {
                "index": 1,
                "role_hint": "character_identity",
                "uri": "/tmp/first-upload.png",
                "source": "user_visible_upload_order",
            },
            {
                "index": 2,
                "role_hint": "pose_composition",
                "uri": "/tmp/second-upload.png",
                "source": "user_visible_upload_order",
            },
        ],
    )

    assert ledger.get_attempt(attempt_id)["input_artifacts_json"] == [
        {
            "index": 1,
            "role_hint": "character_identity",
            "uri": "/tmp/first-upload.png",
            "source": "user_visible_upload_order",
        },
        {
            "index": 2,
            "role_hint": "pose_composition",
            "uri": "/tmp/second-upload.png",
            "source": "user_visible_upload_order",
        },
    ]


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
                duration_ms INTEGER,
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
        duration_seconds=4.25,
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
    assert ledger.get_artifact(artifact_id)["duration_seconds"] == 4.25
    assert ledger.get_delivery(delivery_id)["delivery_status"] == "sent"
    assert ledger.get_feedback(feedback_id)["parsed_json"] == {"selection_hint": 1}


def test_attempt_ledger_migrates_legacy_delivery_without_created_at(tmp_path):
    import sqlite3

    from agent.visual.attempt_ledger import VisualAttemptLedger

    db_path = tmp_path / "legacy_delivery.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE visual_requests (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                user_prompt TEXT,
                normalized_intent TEXT,
                modality TEXT,
                operation TEXT,
                status TEXT
            );
            CREATE TABLE visual_deliveries (
                delivery_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                attempt_id TEXT,
                artifact_id TEXT,
                platform TEXT,
                destination_id TEXT,
                thread_id TEXT,
                delivery_status TEXT
            );
            INSERT INTO visual_requests (id, user_prompt) VALUES ('vrq_legacy', 'prompt');
            INSERT INTO visual_deliveries (
                delivery_id, request_id, artifact_id, platform, destination_id, delivery_status
            ) VALUES (
                'vdel_legacy', 'vrq_legacy', 'var_legacy', 'slack', 'D_TEST', 'sent'
            );
            """
        )

    ledger = VisualAttemptLedger(db_path)
    ledger.initialize()

    deliveries = ledger.list_deliveries(request_id="vrq_legacy")

    assert deliveries[0]["delivery_status"] == "sent"
    assert deliveries[0]["created_at"]


def test_attempt_ledger_writes_legacy_delivery_with_null_attempt_id(tmp_path):
    import sqlite3

    from agent.visual.attempt_ledger import VisualAttemptLedger

    db_path = tmp_path / "legacy_delivery_not_null.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE visual_requests (
                id TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                user_prompt TEXT,
                normalized_intent TEXT,
                modality TEXT,
                operation TEXT,
                status TEXT
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
            INSERT INTO visual_requests (id, user_prompt) VALUES ('vrq_legacy', 'prompt');
            """
        )

    ledger = VisualAttemptLedger(db_path)
    ledger.initialize()
    delivery_id = ledger.record_delivery(
        request_id="vrq_legacy",
        attempt_id=None,
        artifact_id="var_legacy",
        platform="slack",
        destination_id="D_TEST",
        delivery_status="sent",
    )

    delivery = ledger.get_delivery(delivery_id)
    assert delivery["attempt_id"] == ""
    assert delivery["delivery_status"] == "sent"
