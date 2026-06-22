def test_preference_profile_uses_feedback_ewma_by_issue_and_signal(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.preference_profile import build_preference_profile

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    artifact_id = ledger.record_artifact(request_id=request_id, kind="image", content_hash="abc")
    ledger.record_feedback(
        request_id=request_id,
        artifact_id=artifact_id,
        feedback_text="A 不錯，有美腿，但臉不自然",
        polarity=0.4,
        parsed={"signals": ["legs_positive"], "issues": ["face_unnatural"]},
    )

    profile = build_preference_profile(ledger, bucket="visig_demo")

    assert profile["bucket"] == "visig_demo"
    assert profile["signals"]["legs_positive"]["weight"] > 0
    assert profile["issues"]["face_unnatural"]["penalty"] > 0
    assert profile["sample_count"] == 1


def test_preference_profile_is_private_safe_and_low_confidence_with_sparse_data(tmp_path):
    import json

    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.preference_profile import build_preference_profile

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    ledger.record_feedback(
        request_id=request_id,
        feedback_text="private raw feedback: G4 比較好",
        polarity=0.7,
        parsed={"signals": ["composition_positive"], "issues": []},
    )

    profile = build_preference_profile(ledger, bucket="visig_demo")

    serialized = json.dumps(profile, ensure_ascii=False)
    assert "private raw feedback" not in serialized
    assert profile["confidence"] < 1.0
    assert profile["minimum_confidence_sample_count"] == 5


def test_preference_profile_tracks_stocking_quality_penalty(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.feedback import parse_visual_feedback
    from agent.visual.preference_profile import build_preference_profile

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    parsed = parse_visual_feedback("人物太醜，絲襪太醜")
    ledger.record_feedback(
        request_id=request_id,
        feedback_text=parsed.text,
        polarity=parsed.polarity,
        parsed=parsed.parsed,
    )

    profile = build_preference_profile(ledger, bucket="visig_demo")

    assert profile["issues"]["subject_not_attractive"]["penalty"] > 0
    assert profile["issues"]["stockings_bad"]["penalty"] > 0


def test_preference_profile_uses_quality_judgments_as_weak_self_supervised_labels(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.preference_profile import build_preference_profile

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    artifact_id = ledger.record_artifact(request_id=request_id, kind="image", content_hash="weak-bad")
    ledger.record_judgment(
        request_id=request_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.42,
        verdict="review",
        details={
            "quality_issues": ["subject_not_attractive"],
            "preference_dimensions": {
                "subject_beauty": 0.24,
                "face_naturalness": 0.31,
                "glamour_impact": 0.38,
                "fashion_material_quality": 0.44,
            },
        },
    )

    profile = build_preference_profile(ledger, bucket="visig_demo")

    assert profile["explicit_feedback_sample_count"] == 0
    assert profile["self_supervised_sample_count"] == 1
    assert profile["effective_sample_count"] < profile["sample_count"]
    assert profile["issues"]["subject_not_attractive"]["penalty"] > 0
    assert profile["issues"]["face_unnatural"]["penalty"] > 0
    assert profile["issues"]["not_glamorous"]["penalty"] > 0
    assert profile["issues"]["stockings_bad"]["penalty"] > 0


def test_preference_profile_learns_positive_signals_from_high_quality_judgments(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.preference_profile import build_preference_profile

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    artifact_id = ledger.record_artifact(request_id=request_id, kind="image", content_hash="weak-good")
    ledger.record_judgment(
        request_id=request_id,
        artifact_id=artifact_id,
        judge_name="visual_quality_judge",
        score=0.91,
        verdict="pass",
        details={
            "quality_issues": [],
            "preference_dimensions": {
                "subject_beauty": 0.86,
                "face_naturalness": 0.88,
                "glamour_impact": 0.82,
                "fashion_material_quality": 0.8,
                "pose_composition": 0.84,
            },
        },
    )

    profile = build_preference_profile(ledger, bucket="visig_demo")

    assert profile["self_supervised_sample_count"] == 1
    assert profile["effective_sample_count"] == 0.25
    assert profile["issues"] == {}
    assert profile["signals"]["subject_beauty_positive"]["weight"] > 0
    assert profile["signals"]["face_naturalness_positive"]["weight"] > 0
    assert profile["signals"]["glamour_positive"]["weight"] > 0
    assert profile["signals"]["fashion_material_positive"]["weight"] > 0
    assert profile["signals"]["composition_positive"]["weight"] > 0


def test_preference_profile_downweights_self_supervised_labels_when_judge_disagrees_with_human_feedback(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.preference_profile import build_preference_profile

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    for index in range(6):
        artifact_id = ledger.record_artifact(request_id=request_id, kind="image", content_hash=f"bad-{index}")
        ledger.record_judgment(
            request_id=request_id,
            artifact_id=artifact_id,
            judge_name="visual_quality_judge",
            score=0.91,
            verdict="pass",
            details={
                "quality_issues": [],
                "preference_dimensions": {
                    "subject_beauty": 0.86,
                    "face_naturalness": 0.88,
                    "glamour_impact": 0.82,
                },
            },
        )
        ledger.record_feedback(
            request_id=request_id,
            artifact_id=artifact_id,
            feedback_text="private negative feedback",
            polarity=-1.0,
            parsed={"issues": ["subject_not_attractive"], "signals": []},
        )

    profile = build_preference_profile(ledger, bucket="visig_demo")

    assert profile["calibration"]["judge_human_disagreement_rate"] == 1.0
    assert profile["calibration"]["self_supervised_weight_multiplier"] == 0.0
    assert profile["explicit_feedback_sample_count"] == 6
    assert profile["self_supervised_sample_count"] == 6
    assert profile["effective_sample_count"] == 6.0
    assert "subject_not_attractive" in profile["issues"]
    assert "subject_beauty_positive" not in profile["signals"]
    assert "glamour_positive" not in profile["signals"]
    assert "private negative feedback" not in str(profile)


def test_preference_profile_does_not_learn_from_non_quality_judges(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.preference_profile import build_preference_profile

    ledger = VisualAttemptLedger(tmp_path / "visual.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(status="completed", metadata={"intent_signature": "visig_demo"})
    artifact_id = ledger.record_artifact(request_id=request_id, kind="image", content_hash="weak-bad")
    ledger.record_judgment(
        request_id=request_id,
        artifact_id=artifact_id,
        judge_name="debug_judge",
        score=0.1,
        verdict="review",
        details={"quality_issues": ["subject_not_attractive"]},
    )

    profile = build_preference_profile(ledger, bucket="visig_demo")

    assert profile["sample_count"] == 0
    assert profile["self_supervised_sample_count"] == 0
    assert profile["issues"] == {}


def test_preference_profile_filters_legacy_quality_judgments_without_request_id(tmp_path):
    import json
    import sqlite3

    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.preference_profile import build_preference_profile

    db_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE visual_requests (
                request_id TEXT PRIMARY KEY,
                policy_context_json TEXT
            );
            CREATE TABLE visual_artifacts (
                artifact_id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                kind TEXT
            );
            CREATE TABLE visual_judgments (
                judgment_id TEXT PRIMARY KEY,
                artifact_id TEXT NOT NULL,
                attempt_id TEXT NOT NULL,
                judge_name TEXT NOT NULL,
                score_json TEXT NOT NULL,
                confidence REAL NOT NULL,
                created_at TEXT
            );
            """
        )
        conn.execute(
            "INSERT INTO visual_requests (request_id, policy_context_json) VALUES (?, ?)",
            ("vrq_legacy", json.dumps({"intent_signature": "visig_demo"})),
        )
        conn.execute(
            "INSERT INTO visual_artifacts (artifact_id, request_id, attempt_id, kind) VALUES (?, ?, ?, ?)",
            ("var_legacy", "vrq_legacy", "vat_legacy", "image"),
        )
        conn.execute(
            """
            INSERT INTO visual_judgments (
                judgment_id, artifact_id, attempt_id, judge_name, score_json, confidence, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "vjd_legacy",
                "var_legacy",
                "vat_legacy",
                "visual_quality_judge",
                json.dumps(
                    {
                        "quality_issues": ["subject_not_attractive"],
                        "preference_dimensions": {"face_naturalness": 0.2},
                    }
                ),
                0.3,
                "2026-06-22T00:00:00+00:00",
            ),
        )

    profile = build_preference_profile(VisualAttemptLedger(db_path), bucket="visig_demo")

    assert profile["self_supervised_sample_count"] == 1
    assert profile["issues"]["subject_not_attractive"]["penalty"] > 0
    assert profile["issues"]["face_unnatural"]["penalty"] > 0
