def test_feedback_parser_extracts_selection_and_quality_signal():
    from agent.visual.feedback import parse_visual_feedback

    feedback = parse_visual_feedback("第 2 張不錯，腿部構圖更好，但臉有點不自然")

    assert feedback.selection_hint == 2
    assert feedback.polarity > 0
    assert "composition_positive" in feedback.parsed["signals"]
    assert "face_unnatural" in feedback.parsed["issues"]


def test_feedback_parser_extracts_negative_issues_without_learning_update():
    from agent.visual.feedback import parse_visual_feedback

    feedback = parse_visual_feedback("全部退貨，臉不像 reference，也不夠性感")

    assert feedback.selection_hint is None
    assert feedback.polarity < 0
    assert "reference_identity_drift" in feedback.parsed["issues"]
    assert "not_sexy_enough" in feedback.parsed["issues"]
    assert "strategy_update" not in feedback.parsed


def test_feedback_parser_extracts_subject_and_stocking_quality_issues():
    from agent.visual.feedback import parse_visual_feedback

    feedback = parse_visual_feedback("幾個問題：人物太醜，絲襪太醜")

    assert feedback.polarity < 0
    assert "subject_not_attractive" in feedback.parsed["issues"]
    assert "stockings_bad" in feedback.parsed["issues"]


def test_record_parsed_visual_feedback_maps_selection_to_artifact(tmp_path):
    from agent.visual.attempt_ledger import VisualAttemptLedger
    from agent.visual.feedback import record_parsed_visual_feedback

    ledger = VisualAttemptLedger(tmp_path / "attempts.sqlite3")
    ledger.initialize()
    request_id = ledger.record_request(
        normalized_intent={"kind": "image_batch"},
        modality="image",
        operation="text_to_image",
    )
    first_id = ledger.record_artifact(request_id=request_id, kind="image", content_hash="sha256:first")
    second_id = ledger.record_artifact(request_id=request_id, kind="image", content_hash="sha256:second")

    feedback_id = record_parsed_visual_feedback(
        ledger,
        request_id=request_id,
        feedback_text="第 2 張不錯，但臉有點不自然",
        artifact_ids_by_index=[first_id, second_id],
    )

    feedback = ledger.get_feedback(feedback_id)
    assert feedback["artifact_id"] == second_id
    assert feedback["parsed"]["selection_hint"] == 2
    assert "face_unnatural" in feedback["parsed"]["issues"]
