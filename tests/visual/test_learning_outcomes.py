def test_learning_outcomes_keep_provider_quality_and_feedback_separate(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.learning.outcomes import aggregate_visual_strategy_outcomes

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        status="completed",
        metadata={"intent_signature": "visig_glamour"},
        normalized_intent={"kind": "visual_package"},
    )
    attempt_a = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine",
        status="completed",
    )
    attempt_b = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-imagine",
        status="failed",
        error_type="content_moderation",
        error_message="content moderation",
    )
    artifact_a = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_a,
        kind="image",
        local_path="/tmp/a.png",
        content_hash="sha256:a",
        freshness_status="fresh",
    )
    ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_b,
        kind="image",
        local_path="/tmp/b.png",
        content_hash="sha256:b",
        freshness_status="fresh",
    )
    ledger.record_delivery(
        request_id=request_id,
        attempt_id=attempt_a,
        artifact_id=artifact_a,
        platform="slack",
        destination_id="C123",
        delivery_status="sent",
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_a,
        artifact_id=artifact_a,
        judge_name="visual_quality_judge",
        score=0.88,
        verdict="pass",
        details={"scores": {"composition": 0.9}},
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_a,
        feedback_text="不錯",
        polarity=1.0,
        parsed={"signals": ["positive"]},
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_a,
        decision="post",
        scores={"reward": {"final_score": 0.82}},
        metadata={
            "strategy_signature": "vstrat_glamour",
            "active_learning": {"action": "auto_post"},
            "strategy_plan": {"strategy_signature": "vstrat_glamour"},
        },
    )

    report = aggregate_visual_strategy_outcomes(tmp_path / "visual.sqlite3")
    outcome = report["outcomes"][0]

    assert report["bucket_count"] == 1
    assert report["strategy_count"] == 1
    assert outcome["bucket"] == "visig_glamour"
    assert outcome["strategy_signature"] == "vstrat_glamour"
    assert outcome["provider_health"]["attempt_count"] == 2
    assert outcome["provider_health"]["generation_success_rate"] == 0.5
    assert outcome["provider_health"]["policy_failure_rate"] == 0.5
    assert outcome["delivery"]["successful_delivery_count"] == 1
    assert outcome["quality"]["average_confidence"] == 0.88
    assert outcome["human_feedback"]["average_polarity"] == 1.0
    assert outcome["active_learning"]["ask_user_rate"] == 0.0
    assert 0.0 < outcome["confidence"] <= 1.0


def test_learning_outcomes_capture_retry_and_disagreement(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.learning.outcomes import aggregate_visual_strategy_outcomes

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        status="completed",
        metadata={"intent_signature": "visig_portrait"},
    )
    original_attempt = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-video",
        status="failed",
        error_type="provider_timeout",
    )
    retry_attempt = ledger.record_attempt(
        request_id=request_id,
        provider="xai",
        model="grok-video",
        status="completed",
        metadata={"retry_of": 0},
    )
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=retry_attempt,
        kind="video",
        local_path="/tmp/retry.mp4",
        content_hash="sha256:retry",
        freshness_status="fresh",
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=retry_attempt,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.86,
        verdict="pass",
        details={},
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="臉不自然，退貨",
        polarity=-1.0,
        parsed={"veto": True},
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_id,
        decision="ask",
        scores={},
        metadata={
            "strategy_signature": "vstrat_portrait",
            "active_learning": {"action": "ask_user"},
        },
    )

    report = aggregate_visual_strategy_outcomes(tmp_path / "visual.sqlite3")
    outcome = report["outcomes"][0]

    assert outcome["retry"]["retry_attempt_count"] == 1
    assert outcome["retry"]["retry_success_count"] == 1
    assert outcome["active_learning"]["ask_user_rate"] == 1.0
    assert outcome["human_feedback"]["human_veto_count"] == 1
    assert outcome["disagreement"]["judge_human_disagreement_rate"] == 1.0
    assert outcome["confidence"] < 0.5


def test_learning_outcomes_can_filter_bucket(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.learning.outcomes import aggregate_visual_strategy_outcomes

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    keep_request = ledger.record_request(status="completed", metadata={"intent_signature": "visig_keep"})
    skip_request = ledger.record_request(status="completed", metadata={"intent_signature": "visig_skip"})
    for request_id, strategy_signature in (
        (keep_request, "vstrat_keep"),
        (skip_request, "vstrat_skip"),
    ):
        ledger.record_ranking(
            request_id=request_id,
            selected_artifact_id=None,
            decision="ask",
            scores={},
            metadata={"strategy_signature": strategy_signature},
        )

    report = aggregate_visual_strategy_outcomes(tmp_path / "visual.sqlite3", bucket="visig_keep")

    assert [item["bucket"] for item in report["outcomes"]] == ["visig_keep"]


def test_learning_outcomes_joins_legacy_artifact_ids(tmp_path):
    import sqlite3

    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.learning.outcomes import aggregate_visual_strategy_outcomes

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
            CREATE TABLE visual_judgments (
                judgment_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                artifact_id TEXT NOT NULL,
                judge_name TEXT NOT NULL,
                judge_version TEXT NOT NULL,
                score_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                verdict TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE visual_rankings (
                ranking_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                selected_artifact_id TEXT,
                ranker_version TEXT NOT NULL,
                score_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                decision TEXT NOT NULL,
                rationale_json TEXT,
                created_at TEXT NOT NULL
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
        normalized_intent={"intent_signature": "visig_legacy"},
        modality="package",
        operation="visual_package_generate",
        status="completed",
    )
    attempt_id = ledger.record_attempt(request_id=request_id, provider="fixture", model="legacy")
    artifact_id = ledger.record_artifact(
        request_id=request_id,
        attempt_id=attempt_id,
        kind="image",
        local_path="/tmp/legacy.png",
        content_hash="sha256:legacy",
        freshness_status="fresh",
        is_stable=True,
    )
    ledger.record_judgment(
        request_id=request_id,
        attempt_id=attempt_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.77,
        verdict="pass",
    )
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="good",
        polarity=1.0,
    )
    ledger.record_ranking(
        request_id=request_id,
        selected_artifact_id=artifact_id,
        decision="post",
        scores={},
        metadata={"strategy_signature": "vstrat_legacy"},
    )

    outcome = aggregate_visual_strategy_outcomes(db_path)["outcomes"][0]

    assert outcome["quality"]["judgment_count"] == 1
    assert outcome["human_feedback"]["feedback_count"] == 1
